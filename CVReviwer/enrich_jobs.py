"""
enrich_jobs.py — Feature #2 job enrichment pipeline

Produces the derived data Feature 2 matches against: for every job listing
Feature 1 scraped, an LLM extracts structured fields from the description and
a SentenceTransformer turns title+skills into a vector. Results go to the
`job_enrichment` table.

    python enrich_jobs.py            # enrich listings that have none yet
    python enrich_jobs.py --force    # re-enrich everything
    python enrich_jobs.py --limit 5  # try a handful first

WHY A NEW FILE RATHER THAN EDITING embed.py
===========================================
`embed.py`'s `if __name__ == "__main__"` block does this same job, but reads
`jobs.json` — written by the old `scraper.py`, which Feature 1 replaced. That
block therefore has no input any more.

The plan was to rewire it in place. Writing a separate file is better: the
batch block is not M-numbered, but it lives in an approved file alongside
M-03-07 and M-03-10 through M-03-15, and editing it would mean re-proving that
Feature 3's 125-test suite is unaffected on every future change. This way
`embed.py` stays byte-identical and the enrichment pipeline belongs to the
feature that actually consumes it.

The LLM prompt, the gpt-4o-mini → gpt-5 fallback chain, the `is_bad_result`
criteria and the embed text format are ported from that block deliberately
unchanged. What changed is only where the data comes from and goes to.

Requires OPENAI_API_KEY in the environment (or .env) and the DB_* variables
db.py reads.

Enrichment is a pipeline stage, not a setup step: it runs once per listing,
and any listing without an enrichment row is invisible to matching, because
there is nothing for compareSkills to compare against. Re-running it is cheap
— by default it only picks up listings that have none yet.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

import db

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMBED_BATCH_SIZE = 16
LLM_CONCURRENCY = 2
EMBED_TEXT_LIMIT = 500

# How much of a job description the model sees. Raised from 1,500: several
# real listings open with a page of company boilerplate and only reach the
# actual requirements past the 1,500-character mark, so the model was being
# asked to extract skills from marketing copy. Observed descriptions run to
# 7,500 characters.
DESCRIPTION_CHAR_LIMIT = 4000

# Output budget. Raised from 600: the response schema gained
# education_requirement after that number was chosen, and a truncated reply
# is not valid JSON, so the whole call is wasted.
MAX_OUTPUT_TOKENS = 1500

# Reasoning models (gpt-5, o1, o3) spend completion tokens on internal
# reasoning *before* emitting any output, and return empty content if the
# budget runs out first. 800 was nowhere near enough — every gpt-5 attempt in
# the retry ladder came back empty, which is what "empty response from model"
# meant. They need several times the budget of a normal chat model.
REASONING_MAX_OUTPUT_TOKENS = 6000

MODEL_PRIMARY = "gpt-4o-mini"
# Used only after the primary has failed twice. Set to a stronger model you
# have access to ("gpt-4o", "gpt-5") to escalate; leaving it as the primary
# simply retries, which is usually enough and costs far less.
MODEL_ESCALATION = "gpt-4o-mini"

# Models that reason before answering, and so need the larger budget above.
REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")

_ENRICHMENT_COLUMNS = (
    "skills", "education", "education_requirement", "experience_years",
    "work_mode", "benefits", "translated_description", "embedding",
    "embedding_model", "embedding_dim", "enriched_at",
)

# Canonical degree levels, lowest to highest. The LLM is asked to return one
# of these exact strings for min_degree_level, so match_service compares an
# ordinal rather than guessing from prose.
DEGREE_LEVEL_NAMES = ("high_school", "diploma", "bachelor", "master", "doctorate")


# ---------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------

def fetch_listings(only_missing=True, limit=None):
    """
    Reads job listings to enrich, newest first.

    Note this reads job_listing directly rather than through
    job_service.load_listings (M-01-17): that method combines the manual and
    365-day outdated rules for *display*, and enrichment doesn't care whether
    a listing is outdated — an outdated listing still gets enriched, and it is
    matching (M-02-02 / SRS-048) that filters it out later. Enriching only
    active listings would mean re-enriching from scratch if a listing's
    outdated status ever changed.
    """
    sql = (
        "SELECT l.id, l.url, l.job_title, l.company_name, l.job_location, l.job_details "
        "FROM job_listing l "
    )
    if only_missing:
        sql += "LEFT JOIN job_enrichment e ON e.job_listing_id = l.id WHERE e.job_listing_id IS NULL "
    sql += "ORDER BY l.job_posted_date DESC"
    if limit:
        return db.query(sql + " LIMIT %s", (int(limit),))
    return db.query(sql)


def save_enrichment(job_listing_id, fields):
    """
    Upserts one job_enrichment row. job_listing_id is the primary key, so a
    re-enrichment replaces rather than duplicates.
    """
    db.execute(
        """
        INSERT INTO job_enrichment
            (job_listing_id, skills, education, education_requirement,
             experience_years, work_mode, benefits, translated_description,
             embedding, embedding_model, embedding_dim, enriched_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            skills = VALUES(skills), education = VALUES(education),
            education_requirement = VALUES(education_requirement),
            experience_years = VALUES(experience_years), work_mode = VALUES(work_mode),
            benefits = VALUES(benefits), translated_description = VALUES(translated_description),
            embedding = VALUES(embedding), embedding_model = VALUES(embedding_model),
            embedding_dim = VALUES(embedding_dim), enriched_at = VALUES(enriched_at)
        """,
        (
            job_listing_id,
            json.dumps(fields.get("skills") or [], ensure_ascii=False),
            fields.get("education"),
            json.dumps(fields["education_requirement"], ensure_ascii=False)
                if fields.get("education_requirement") else None,
            fields.get("experience_years"),
            fields.get("work_mode"),
            json.dumps(fields.get("benefits") or [], ensure_ascii=False),
            fields.get("translated_description"),
            json.dumps(fields.get("embedding")) if fields.get("embedding") else None,
            fields.get("embedding_model"),
            fields.get("embedding_dim"),
            datetime.now(timezone.utc),
        ),
    )


# ---------------------------------------------------------------------
# Shaping — ported unchanged from embed.py's batch block
# ---------------------------------------------------------------------

def clean_json(content):
    content = (content or "").strip()
    content = re.sub(r"^```[a-zA-Z]*", "", content)
    content = re.sub(r"```$", "", content)
    return content.strip()


def normalize_output(listing, extracted):
    """
    Maps an LLM result onto the job_enrichment columns.

    Ported from embed.py's `normalize_output`, minus the fields that now live
    in job_listing and must not be overwritten by a model's guess: `location`,
    `salary`, `job_type`, `company`, `title` and `description` are what the
    provider actually returned, and Feature 1 owns them. Only the seven
    genuinely derived fields are kept.

    `job_type` is the clearest case — the LLM is asked to normalise it to
    fulltime/parttime/contract/freelance, but job_listing.job_employment_type
    already holds the provider's own value ("งานประจำ", "Full-time"). Two
    competing answers to one question is worse than one imperfect answer, so
    the provider's wins and the model's is discarded.
    """
    def get_or_null(key, default=None):
        return extracted.get(key) if extracted and key in extracted else default

    experience = get_or_null("experience_years", None)
    if isinstance(experience, str):
        # The model is told "number only" but occasionally returns "3 years".
        digits = re.search(r"\d+", experience)
        experience = int(digits.group()) if digits else None
    elif isinstance(experience, float):
        experience = int(experience)
    elif not isinstance(experience, int):
        experience = None

    return {
        "skills": get_or_null("skills", []) or [],
        "education": get_or_null("education", None),
        "education_requirement": _clean_education_requirement(
            get_or_null("education_requirement", None)
        ),
        "experience_years": experience,
        "work_mode": get_or_null("work_mode", None),
        "benefits": get_or_null("benefits", []) or [],
        "translated_description": get_or_null(
            "translated_description", listing.get("job_details") or ""
        ),
    }


def _clean_education_requirement(raw):
    """
    Validates the model's structured education requirement before storing it.

    The model is asked for an exact `min_degree_level` from a fixed set and a
    list of alternative fields. It mostly complies, but "Bachelor" or
    "bachelor's" comes back often enough to be worth normalising, and an
    unrecognised level is dropped rather than stored — a wrong ordinal scores
    silently wrong, whereas a null falls back to parsing the free text.

    Returns None when nothing usable was extracted, so the column stays NULL
    and compare_education takes the fallback path.
    """
    if not isinstance(raw, dict):
        return None

    level = raw.get("min_degree_level")
    if isinstance(level, str):
        key = re.sub(r"[^a-z_ ]", "", level.strip().lower()).replace(" ", "_").rstrip("s")
        aliases = {
            "high_school": "high_school", "highschool": "high_school", "secondary": "high_school",
            "diploma": "diploma", "associate": "diploma", "vocational": "diploma",
            "bachelor": "bachelor", "bachelor_degree": "bachelor", "undergraduate": "bachelor",
            "master": "master", "master_degree": "master", "postgraduate": "master",
            "doctorate": "doctorate", "doctoral": "doctorate", "phd": "doctorate",
        }
        level = aliases.get(key)
    else:
        level = None

    fields = raw.get("fields")
    if isinstance(fields, str):
        fields = [fields]
    if not isinstance(fields, list):
        fields = []
    cleaned_fields = []
    for entry in fields:
        if isinstance(entry, str) and entry.strip():
            text = " ".join(entry.strip().lower().split())
            if text not in cleaned_fields:
                cleaned_fields.append(text)

    if not level and not cleaned_fields:
        return None
    return {"min_degree_level": level, "fields": cleaned_fields}


def is_bad_result(data):
    """
    Whether a result is worth retrying.

    Relaxed from the ported version, which also rejected any result with an
    empty skills list. That treated a correct extraction as a failure: several
    real listings — the chef and kitchen roles in particular — genuinely list
    no discrete skills, so the model returned [] four times, every retry was
    spent re-deriving the same right answer, and the run ended by discarding
    the good translated_description it had along with it.

    A result now fails only if it is unusable: absent, not a mapping, or with
    no translated_description. An empty skills list is reported by
    `enrich` afterwards rather than retried, since it means the listing will
    match on education and experience alone.
    """
    if not isinstance(data, dict) or not data:
        return True
    if data.get("translated_description") is None:
        return True
    if not isinstance(data.get("skills", []), list):
        return True
    return False


def build_embed_text(title, skills):
    """
    Ported unchanged from embed.py, including the 500-char cap and the
    "general" fallback. Kept byte-identical to that version so vectors stay
    comparable with any produced before this file existed — a different embed
    text yields a different vector for the same job.
    """
    skills_str = " ".join(skills or [])
    if not title and not skills_str:
        return "general"
    return f"Title: {title} | Skills: {skills_str}"[:EMBED_TEXT_LIMIT]


# ---------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------

async def _extract_with_llm(client, text, model="gpt-4o-mini"):
    """Prompt ported verbatim from embed.py so output shape is unchanged."""
    prompt = f"""
    Extract structured job data in English.

    Return ONLY valid JSON (no explanation, no markdown) with this schema:
    {{"location": null, "skills": [], "salary": null, "job_type": null, "work_mode": null, "benefits": [], "experience_years": null, "education": null, "education_requirement": {{"min_degree_level": null, "fields": []}}, "translated_description": ""}}

    Rules:
    - Detect the language automatically
    - Location: Translate to English if not English; keep structure: District, City; Do NOT invent new formats
    - Skills, benefits, education: Translate to English; Do NOT translate technical terms (Python, React, SQL, etc.)
    - translated_description: Translate and summarize in 2-3 sentences
    - job_type: fulltime | parttime | contract | freelance | null
    - work_mode: remote | hybrid | onsite | null
    - experience_years: number only
    - education: the qualification sentence as written, translated to English
    - education_requirement.min_degree_level: exactly one of high_school | diploma | bachelor | master | doctorate, or null if no level is stated. Use the LOWEST level that satisfies the listing ("Bachelor's or higher" -> bachelor, "Bachelor/Master's" -> bachelor)
    - education_requirement.fields: each acceptable field of study as its own entry, in English, singular ("computer science", "information technology"). These are ALTERNATIVES - a candidate matching any one qualifies. Empty list if no field is specified
    - If missing -> null

    Job description:
    \"\"\"{text}\"\"\"
    """
    try:
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a strict JSON generator. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        }
        if model.startswith(REASONING_MODEL_PREFIXES):
            # Reasoning models reject temperature and use a different budget
            # parameter, most of which they spend before writing anything.
            kwargs["max_completion_tokens"] = REASONING_MAX_OUTPUT_TOKENS
        else:
            kwargs["temperature"] = 0
            kwargs["max_tokens"] = MAX_OUTPUT_TOKENS

        response = await asyncio.wait_for(client.chat.completions.create(**kwargs), timeout=60)
        choice = response.choices[0]
        content = choice.message.content
        if not content:
            # Say *why*. "empty response" alone gave no way to tell a
            # truncated reply from a refusal from a reasoning model that spent
            # its whole budget thinking.
            reason = getattr(choice, "finish_reason", "unknown")
            usage = getattr(response, "usage", None)
            detail = f"finish_reason={reason}"
            if usage is not None:
                detail += f", completion_tokens={getattr(usage, 'completion_tokens', '?')}"
                reasoning = getattr(getattr(usage, "completion_tokens_details", None),
                                    "reasoning_tokens", None)
                if reasoning:
                    detail += f", reasoning_tokens={reasoning}"
            print(f"    {model} returned no content ({detail})")
            if reason == "length":
                print(f"      -> the token budget ran out; raise "
                      f"{'REASONING_MAX_OUTPUT_TOKENS' if model.startswith(REASONING_MODEL_PREFIXES) else 'MAX_OUTPUT_TOKENS'}")
            return None
        try:
            return json.loads(clean_json(content))
        except json.JSONDecodeError as ex:
            print(f"    JSON parse error: {ex}")
            return None
    except asyncio.TimeoutError:
        print("    request timed out")
        return None
    except Exception as ex:
        print(f"    LLM error: {ex}")
        return None


async def _extract_with_fallback(client, text, title=None):
    """
    Tries the primary model twice, then escalates once.

    Shorter than the ported four-step ladder because two of those steps were
    gpt-5 calls that could never succeed with the budget they were given.

    Keeps the best result seen rather than returning {} on failure. The old
    version discarded everything when the last attempt failed, so a listing
    whose first call produced a good translation and education requirement —
    and failed only on a strict skills check — was stored with nothing at all.
    A partial extraction is worth more than an empty one.
    """
    text = (text or "")[:DESCRIPTION_CHAR_LIMIT]
    attempts = [(MODEL_PRIMARY, 0.3), (MODEL_PRIMARY, 0.5), (MODEL_ESCALATION, 0.8)]
    best = {}
    for i, (model, pause) in enumerate(attempts):
        await asyncio.sleep(pause)
        data = await _extract_with_llm(client, text, model=model)
        if not is_bad_result(data):
            return data
        if isinstance(data, dict) and data and len(str(data)) > len(str(best)):
            best = data
        if i < len(attempts) - 1:
            print(f"    retry with {attempts[i + 1][0]}... ({title})")
    if best:
        print(f"    keeping the best partial result ({title})")
    else:
        print(f"    all attempts failed ({title})")
    return best


async def _extract_all(client, listings):
    semaphore = asyncio.Semaphore(LLM_CONCURRENCY)

    async def one(listing):
        async with semaphore:
            details = listing.get("job_details") or ""
            if not details.strip():
                return listing["id"], normalize_output(listing, {})
            extracted = await _extract_with_fallback(
                client, details, title=listing.get("job_title")
            )
            return listing["id"], normalize_output(listing, extracted or {})

    return await asyncio.gather(*(one(l) for l in listings))


def enrich(only_missing=True, limit=None):
    listings = fetch_listings(only_missing=only_missing, limit=limit)
    if not listings:
        print("Nothing to enrich — every listing already has enrichment.")
        print("Use --force to regenerate, or run a scraper first.")
        return 0

    print(f"Listings to enrich: {len(listings)}")

    # Imported here rather than at module top: the ML stack takes a while to
    # load, and nothing above needs it. (embed.py imports SentenceTransformer
    # at module level, which is why reaching any M-03 method loads it too —
    # noted in TBD_and_Conflicts.md Part 4.)
    from openai import AsyncOpenAI
    from sentence_transformers import SentenceTransformer
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set. Put it in .env or the environment.", file=sys.stderr)
        return 1

    # The embedding model is loaded BEFORE any API call, not after.
    #
    # It used to be instantiated between extraction and saving, which meant a
    # failure here — a missing torchvision, an unreachable model cache, no
    # disk space — threw away every LLM call the run had just paid for, with
    # nothing written to the database. Everything that can fail for free is
    # now made to fail first.
    print(f"Loading embedding model {MODEL_NAME}...")
    try:
        model = SentenceTransformer(MODEL_NAME)
    except Exception as ex:
        print(f"Could not load the embedding model: {type(ex).__name__}: {ex}",
              file=sys.stderr)
        if "torchvision" in str(ex) or "torchvision" in type(ex).__name__:
            print("\n  sentence-transformers imports torchvision when the model is",
                  file=sys.stderr)
            print("  instantiated, so a missing install only shows up here. Install it:",
                  file=sys.stderr)
            print("      pip install torchvision", file=sys.stderr)
            print("  If pip reports a conflict with your torch version, install both",
                  file=sys.stderr)
            print("  together so it resolves them jointly:", file=sys.stderr)
            print("      pip install --upgrade torch torchvision", file=sys.stderr)
        print("\n  No API calls were made, so nothing has been spent.", file=sys.stderr)
        return 1

    client = AsyncOpenAI(api_key=api_key)
    print("Extracting structured fields...")
    extracted = dict(asyncio.run(_extract_all(client, listings)))

    ids = [l["id"] for l in listings]
    texts = [
        build_embed_text(l.get("job_title"), extracted[l["id"]].get("skills"))
        for l in listings
    ]

    print("Embedding and saving...")
    saved = 0
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch_ids = ids[start:start + EMBED_BATCH_SIZE]
        vectors = model.encode(texts[start:start + EMBED_BATCH_SIZE], show_progress_bar=False)
        for listing_id, vector in zip(batch_ids, vectors):
            fields = dict(extracted[listing_id])
            fields["embedding"] = vector.tolist()
            fields["embedding_model"] = MODEL_NAME
            fields["embedding_dim"] = len(vector)
            # Saved per batch rather than at the end, so an interruption keeps
            # the work already paid for; the next run picks up the rest.
            save_enrichment(listing_id, fields)
            saved += 1
        print(f"  saved {saved}/{len(ids)}")

    # A run used to end with nothing but a scroll-back of retry messages, so
    # the only way to tell how it went was to read them all. Report it.
    by_title = {l["id"]: (l.get("job_title") or l["id"]) for l in listings}
    no_skills = [by_title[i] for i in ids if not extracted[i].get("skills")]
    no_education = [i for i in ids if not extracted[i].get("education_requirement")]
    print(f"\nEnriched {saved} listing(s).")
    print(f"  with skills            {saved - len(no_skills)}/{saved}")
    print(f"  with an education rule {saved - len(no_education)}/{saved}")
    if no_skills:
        print(f"\n  {len(no_skills)} listing(s) have no skills and will match on education")
        print(f"  and experience alone:")
        for title in no_skills[:10]:
            print(f"    - {title}")
        print("\n  That is often correct — many non-technical roles list no discrete")
        print("  skills. If it looks wrong, the description may open with company")
        print("  boilerplate; raise DESCRIPTION_CHAR_LIMIT and re-run with --force.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Enrich job listings for Feature 2 matching.")
    ap.add_argument("--force", action="store_true",
                    help="re-enrich listings that already have enrichment")
    ap.add_argument("--limit", type=int, default=None,
                    help="process at most N listings")
    args = ap.parse_args()

    try:
        return enrich(only_missing=not args.force, limit=args.limit)
    except db.DatabaseError as ex:
        print(f"Database error: {ex}", file=sys.stderr)
        detail = getattr(ex, "detail", None)
        if detail:
            print(f"  {detail}", file=sys.stderr)
        print("\n  Check the DB_* values in .env, that MySQL is running, and "
              "that schema_f2.sql has been applied.", file=sys.stderr)
        return 1
    except FileNotFoundError as ex:
        print(f"File not found: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())