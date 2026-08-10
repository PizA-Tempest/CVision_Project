"""
eval_matching.py — measure whether programming listings outrank kitchen ones

    python eval_matching.py                     # score every CV, current settings
    python eval_matching.py --detail 9fdbda17   # full ranked table for one CV
    python eval_matching.py --sweep             # try candidate constants
    python eval_matching.py --labels-only       # regenerate labels.json and stop

WHAT IT MEASURES
================
Every CV in the corpus is a software/IT CV, so the correct ranking puts all
13 developer listings above all kitchen listings. The headline number is:

    margin = min(score of dev listings) - max(score of chef listings)

Positive means every developer role outranks every kitchen role for that CV.
The goal is margin > 0 for all 12 CVs, with a buffer.

Margin is used rather than nDCG because the goal is about the boundary, not
the top of the list: a single chef role at rank 4 barely moves nDCG@5 but is
exactly the failure being chased.

`inversions` counts (chef, dev) pairs ranked the wrong way round. Margin says
how bad the worst case is; inversions says how widespread it is. A change can
improve one and worsen the other, which is worth seeing.

READ-ONLY
=========
Calls the real compare_* and calculate_match_score against the real database,
so what it measures is what the app does. It does NOT call
match_cv_against_listings, because that writes to job_match — this script
never writes anything, and can be run against a live database safely.

GROUND TRUTH
============
`labels.json` maps job_listing.id -> dev | chef, generated on first run by
title matching and then kept as a file you can hand-correct. Regenerate with
--labels-only after scraping new listings; anything unrecognised is reported
rather than guessed at.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

from dotenv import load_dotenv

load_dotenv()

import cv_data_adapter
import match_service

LABELS_FILE = "labels.json"

# CVs excluded from the headline count, by agreement, because they fail for
# reasons no scorer setting can reach. Matched on filename prefix. They are
# still scored and still printed — hiding them would be the wrong kind of
# convenience — but the target is 11/12, not 12/12, and letting these two
# steer a parameter choice fits the tuning to their defects.
KNOWN_HARD = {
    "Cv- Thirapat": "lists only Figma and Trello — no programming skills, and "
                    "its CV vector sits closer to kitchen listings (0.364) "
                    "than developer ones (0.302)",
    "Resume_Business_Analyst_Intern_Natpapha": "dates did not parse, so "
                    "experience scores 0.0 against every listing — an "
                    "extraction defect, not a ranking one",
}


def is_known_hard(name):
    return any(name.startswith(prefix) for prefix in KNOWN_HARD)

# Titles that are kitchen roles. Substring match, lowercased. Deliberately
# narrow — a title this does not recognise is reported as "unlabelled" rather
# than silently counted as a developer role, which would flatter the score.
CHEF_MARKERS = ("chef", "cook", "kitchen", "culinary", "pastry", "baker",
                "sous", "commis", "แม่ครัว", "กุ๊ก", "เชฟ")
DEV_MARKERS = ("developer", "programmer", "engineer", "software", "frontend",
               "front-end", "front end", "backend", "back-end", "back end",
               "full stack", "full-stack", "web", ".net", "mobile", "ai ",
               "โปรแกรมเมอร์", "พัฒนาระบบ", "ซอฟต์แวร์")


def build_labels(listings):
    labels, unlabelled = {}, []
    for row in listings:
        title = (row.get("job_title") or "").lower()
        if any(m in title for m in CHEF_MARKERS):
            labels[row["id"]] = "chef"
        elif any(m in title for m in DEV_MARKERS):
            labels[row["id"]] = "dev"
        else:
            unlabelled.append((row["id"], row.get("job_title")))
    return labels, unlabelled


def load_labels(listings):
    if os.path.isfile(LABELS_FILE):
        stored = json.load(open(LABELS_FILE, encoding="utf-8"))
        missing = [r for r in listings if r["id"] not in stored]
        if missing:
            print(f"  note: {len(missing)} listing(s) not in {LABELS_FILE}; "
                  "run --labels-only to regenerate")
        return stored
    labels, unlabelled = build_labels(listings)
    json.dump(labels, open(LABELS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"  wrote {LABELS_FILE} ({Counter(labels.values())})")
    if unlabelled:
        print("  UNLABELLED — add these by hand, they are excluded from scoring:")
        for jid, title in unlabelled:
            print(f"    {jid}  {title}")
    return labels


def load_cvs():
    """
    Every CV in Feature 3's registry that has extracted data.

    Read through cv_data_adapter, the same entry point matching uses, so a CV
    this script can score is one the app can score.
    """
    registry = json.load(open(cv_data_adapter.CV_REGISTRY_FILE, encoding="utf-8"))
    out = []
    for record in registry:
        cv_id = record.get("id")
        try:
            data = cv_data_adapter.get_extracted_cv_data(cv_id)
        except Exception as ex:
            print(f"  skipped {record.get('original_filename')}: {type(ex).__name__}")
            continue
        out.append((cv_id, record.get("original_filename") or cv_id, data))
    return out


def score_cv(cv_data, listings, labels, cv_vector=None):
    """Scores one CV against every labelled listing. No writes."""
    available = cv_data_adapter.available_categories(cv_data)

    # Same two-pass shape as match_cv_against_listings: normalisation needs
    # the whole pool before any one listing can be gated.
    semantics = [match_service._semantic_for(cv_vector, r) for r in listings]
    if match_service.SEMANTIC_NORMALIZE:
        semantics = match_service.normalise_semantics(semantics)

    rows = []
    for index, listing in enumerate(listings):
        label = labels.get(listing["id"])
        if label is None:
            continue
        skill = match_service.compare_skills(cv_data["skills"], listing.get("skills"))
        education = match_service.compare_education(
            cv_data["education"],
            listing.get("education_requirement") or listing.get("education"),
        )
        experience = match_service.compare_experience(
            cv_data["work_experience"], listing.get("experience_years")
        )
        semantic = semantics[index]
        blended = match_service._BlendedSkillResult(
            skill, match_service.blend_skill_ratio(skill.ratio, semantic)
        )
        total = match_service.calculate_match_score(
            blended, education, experience, available
        )
        total = match_service.apply_semantic_gate(total, semantic)
        rows.append({
            "title": listing.get("job_title"), "label": label, "score": total,
            "skills": round(skill.ratio, 3),
            "semantic": round(semantic, 3) if semantic is not None else None,
            "education": round(education.ratio, 3),
            "experience": round(experience.ratio, 3),
        })
    rows.sort(key=lambda r: -r["score"])
    return rows, available


def summarise(rows):
    dev = [r["score"] for r in rows if r["label"] == "dev"]
    chef = [r["score"] for r in rows if r["label"] == "chef"]
    if not dev or not chef:
        return None
    inversions = sum(1 for c in chef for d in dev if c > d)
    return {
        "margin": round(min(dev) - max(chef), 3),
        "inversions": inversions,
        # Listings scoring exactly zero. A high SEMANTIC_FLOOR at a high
        # SEMANTIC_GATE drives scores to 0 outright, which *improves* the
        # margin and inversion figures while destroying the ranking — at
        # floor 0.35 the median reached +0.000 with the lowest inversion
        # count in the sweep and not one CV separated, because margins tied
        # at zero rather than turning positive. Counted so that failure
        # cannot hide behind a good-looking number.
        "zeroed": sum(1 for r in rows if r["score"] == 0.0),
        "pairs": len(dev) * len(chef),
        "worst_dev": round(min(dev), 3),
        "best_chef": round(max(chef), 3),
        "top_is_dev": rows[0]["label"] == "dev",
    }


def encode_all(cvs):
    """
    Vectors for every CV, once. None throughout when semantic scoring is off
    or sentence-transformers is missing — the harness then measures exactly
    what it measured before.
    """
    if match_service.SEMANTIC_WEIGHT <= 0.0 and match_service.SEMANTIC_GATE <= 0.0:
        return {cv_id: None for cv_id, _, _ in cvs}
    try:
        import cv_embedding
    except Exception as ex:
        print(f"  semantic scoring unavailable: {ex}")
        return {cv_id: None for cv_id, _, _ in cvs}
    print("  loading the embedding model (first run downloads ~400 MB)...")
    out = {}
    for cv_id, name, data in cvs:
        try:
            out[cv_id] = cv_embedding.encode_cv(data)
        except Exception as ex:
            print(f"  could not encode {name}: {ex}")
            out[cv_id] = None
    covered = sum(1 for v in out.values() if v)
    print(f"  encoded {covered}/{len(cvs)} CVs")
    return out


def report_vector_coverage(listings):
    """How many listings carry a vector this build can actually use."""
    try:
        import cv_embedding
    except Exception:
        return
    usable = sum(1 for r in listings if cv_embedding.listing_vector(r))
    print(f"Listings with a usable embedding: {usable}/{len(listings)}"
          + ("" if usable == len(listings) else
             "  <-- the rest fall back to token overlap alone"))


def semantic_report(listings, labels, cvs):
    """
    Raw cosines, before any rescaling, split by ground-truth label.

    Answers the one question the sweep cannot: is the embedding signal absent,
    or present but compressed? If dev and chef cosines overlap, the embeddings
    genuinely do not distinguish these listings and no rescaling helps. If
    they separate but both sit high, the signal is there and the [0,1] rescale
    in cv_embedding is throwing it away.

    `gap` is the number that matters — mean dev cosine minus mean chef cosine,
    per CV. `overlap` counts chef listings whose raw cosine beats the *worst*
    dev listing, which is the failure the margin metric is built around.
    """
    import cv_embedding

    match_service.SEMANTIC_WEIGHT = 1.0
    vectors = encode_all(cvs)
    match_service.SEMANTIC_WEIGHT = 0.0

    print(f"\n{'CV':<38}{'dev mean':>10}{'chef mean':>11}{'gap':>8}"
          f"{'worst dev':>11}{'best chef':>11}{'overlap':>9}")
    print("-" * 98)
    gaps, overlaps = [], []
    for cv_id, name, _ in cvs:
        vector = vectors.get(cv_id)
        if not vector:
            continue
        dev, chef = [], []
        for listing in listings:
            label = labels.get(listing["id"])
            other = cv_embedding.listing_vector(listing)
            if label is None or not other:
                continue
            # Raw cosine, deliberately NOT the rescaled semantic_score.
            dot = sum(a * b for a, b in zip(vector, other))
            na = sum(a * a for a in vector) ** 0.5
            nb = sum(b * b for b in other) ** 0.5
            raw = dot / (na * nb) if na and nb else 0.0
            (dev if label == "dev" else chef).append(raw)
        if not dev or not chef:
            continue
        gap = sum(dev) / len(dev) - sum(chef) / len(chef)
        over = sum(1 for c in chef if c > min(dev))
        gaps.append(gap)
        overlaps.append(over)
        print(f"{name[:37]:<38}{sum(dev)/len(dev):>10.3f}{sum(chef)/len(chef):>11.3f}"
              f"{gap:>+8.3f}{min(dev):>11.3f}{max(chef):>11.3f}{over:>6}/{len(chef):<3}")
    if gaps:
        print("-" * 98)
        print(f"  mean gap {sum(gaps)/len(gaps):+.3f} | "
              f"gap positive for {sum(1 for g in gaps if g > 0)}/{len(gaps)} CVs | "
              f"chef-above-worst-dev {sum(overlaps)}/{len(overlaps) * 6}")
        print("\n  Reading it: a clearly positive gap with heavy overlap means the")
        print("  signal exists but the rescale is compressing it. A gap near zero")
        print("  means the embeddings do not distinguish these listings at all.")


def run(listings, labels, cvs, detail=None):
    print(f"\n{'CV':<40}{'margin':>8}{'worst dev':>11}{'best chef':>11}"
          f"{'inv':>6}{'zero':>8}")
    print("-" * 84)
    margins, failing, zeroed, names = [], [], [], []
    vectors = encode_all(cvs)
    for cv_id, name, data in cvs:
        rows, _ = score_cv(data, listings, labels, vectors.get(cv_id))
        s = summarise(rows)
        if s is None:
            print(f"{name[:39]:<40}{'n/a — need both labels':>36}")
            continue
        flag = ("" if s["margin"] > 0
                else ("  <-- known-hard" if is_known_hard(name) else "  <-- FAIL"))
        print(f"{name[:39]:<40}{s['margin']:>8}{s['worst_dev']:>11}"
              f"{s['best_chef']:>11}{s['inversions']:>4}/{s['pairs']:<3}"
              f"{s['zeroed']:>5}/{len(rows):<3}{flag}")
        margins.append(s["margin"])
        names.append(name)
        zeroed.append(s["zeroed"])
        if s["margin"] <= 0:
            failing.append(name)
        if detail and cv_id.startswith(detail):
            print(f"\n  --- {name} ---")
            print(f"  {'':<4}{'listing':<40}{'score':>7}{'skl':>7}{'sem':>7}"
                  f"{'edu':>7}{'exp':>7}")
            for r in rows:
                tag = "DEV " if r["label"] == "dev" else "CHEF"
                sem = "-" if r["semantic"] is None else r["semantic"]
                print(f"  {tag:<4}{str(r['title'])[:39]:<40}{r['score']:>7}"
                      f"{r['skills']:>7}{sem:>7}{r['education']:>7}{r['experience']:>7}")
            print()
    if margins:
        passing = sum(1 for m in margins if m > 0)
        print("-" * 84)
        print(f"  {passing}/{len(margins)} CVs fully separated | "
              f"worst margin {min(margins):+.3f} | median {sorted(margins)[len(margins)//2]:+.3f}")
        scored = [m for n, m in zip(names, margins) if not is_known_hard(n)]
        if scored and len(scored) != len(margins):
            print(f"  excluding {len(margins) - len(scored)} known-hard: "
                  f"{sum(1 for m in scored if m > 0)}/{len(scored)} separated | "
                  f"worst {min(scored):+.3f} | "
                  f"median {sorted(scored)[len(scored)//2]:+.3f}   <-- the target")
        if failing:
            print(f"  failing: {', '.join(n[:28] for n in failing)}")
        if zeroed and sum(zeroed) / len(zeroed) > 2:
            print(f"  WARNING: {sum(zeroed)/len(zeroed):.1f} listings per CV score "
                  "exactly 0.0. Lower SEMANTIC_FLOOR —\n"
                  "           a flattened ranking scores well on margin and "
                  "ranks nothing.")
    return margins


def sweep_skills(listings, labels, cvs):
    """
    Sweeps SKILL_NORMALISE and SKILL_PARTIAL_CREDIT against the adopted
    semantic settings, which are left exactly as configured.

    Also reports `dev zeros` — developer listings scoring 0.0 on the skills
    category — because that is what this change is meant to reduce, and the
    margin columns cannot show whether it did. A setting can improve the
    margin by suppressing kitchen listings rather than by recognising more
    developer skills, and those are different things.
    """
    vectors = encode_all(cvs)
    original = (match_service.SKILL_NORMALISE, match_service.SKILL_PARTIAL_CREDIT)

    print(f"\n{'norm':>5}{'partial':>9}{'separated':>12}{'worst':>9}"
          f"{'median':>9}{'inv':>7}{'dev zeros':>11}{'top':>9}")
    print("-" * 71)
    best = None
    for normalise in (False, True):
        for partial in ((0.0,) if not normalise else (0.0, 0.25, 0.5, 0.75)):
            match_service.SKILL_NORMALISE = normalise
            match_service.SKILL_PARTIAL_CREDIT = partial
            margins, inversions, tops, names, zeros, pairs = [], 0, [], [], 0, 0
            for cv_id, cv_name, data in cvs:
                rows, _ = score_cv(data, listings, labels, vectors.get(cv_id))
                st = summarise(rows)
                if not st:
                    continue
                margins.append(st["margin"])
                names.append(cv_name)
                inversions += st["inversions"]
                tops.append(max(r["score"] for r in rows))
                zeros += sum(1 for r in rows
                             if r["label"] == "dev" and r["skills"] == 0.0)
                pairs += sum(1 for r in rows if r["label"] == "dev")
            if not margins:
                continue
            scored = [m for n, m in zip(names, margins) if not is_known_hard(n)] or margins
            passing = sum(1 for m in scored if m > 0)
            median = sorted(scored)[len(scored) // 2]
            top = sum(tops) / len(tops)
            tag = "  <- exact match only" if not normalise else ""
            print(f"{'Y' if normalise else 'N':>5}{partial:>9}"
                  f"{passing:>8}/{len(scored):<3}{min(scored):>+9.3f}{median:>+9.3f}"
                  f"{inversions:>7}{zeros:>6}/{pairs:<4}{top:>9.3f}{tag}")
            key = (passing, round(median, 3), round(min(scored), 3))
            if best is None or key > best[0]:
                best = (key, normalise, partial)
    match_service.SKILL_NORMALISE, match_service.SKILL_PARTIAL_CREDIT = original
    if best:
        print(f"\n  best: SKILL_NORMALISE={best[1]}, SKILL_PARTIAL_CREDIT={best[2]}")
        print("  Judged on the scoreable CVs. Check `dev zeros` fell — if the")
        print("  margin improved while it did not, the gain came from somewhere")
        print("  other than recognising more skills.")


def sweep(listings, labels, cvs):
    """
    Sweeps SEMANTIC_WEIGHT — how much of the skills category comes from
    embedding similarity rather than token overlap.

    0.0 is the previous behaviour exactly, so the first row is the baseline
    every other row is judged against. Encoding happens once, outside the
    loop: only the blend changes between rows, not the vectors.
    """
    original = match_service.SEMANTIC_WEIGHT
    match_service.SEMANTIC_WEIGHT = 1.0          # force encoding on
    vectors = encode_all(cvs)
    match_service.SEMANTIC_WEIGHT = original
    if not any(vectors.values()):
        match_service.SEMANTIC_WEIGHT = original
        print("\n  No CV could be encoded — nothing to sweep.")
        return

    import cv_embedding
    original_floor = cv_embedding.SEMANTIC_FLOOR

    print(f"\n{'norm':>5}{'gate':>6}{'floor':>7}{'separated':>12}{'worst':>9}"
          f"{'median':>9}{'inv':>7}{'zero/cv':>7}{'top':>9}")
    print("-" * 71)

    # Reference row: everything semantic off. Printed rather than assumed so
    # the table is readable on its own.
    match_service.SEMANTIC_WEIGHT = 0.0
    match_service.SEMANTIC_GATE = 0.0
    base_margins, base_inv = [], 0
    for cv_id, _, data in cvs:
        rows, _ = score_cv(data, listings, labels, vectors.get(cv_id))
        st = summarise(rows)
        if st:
            base_margins.append(st["margin"])
            base_inv += st["inversions"]
    if base_margins:
        print(f"{'-':>5}{0.0:>6}{0.0:>7}"
              f"{sum(1 for m in base_margins if m > 0):>8}/{len(base_margins):<3}"
              f"{min(base_margins):>+9.3f}"
              f"{sorted(base_margins)[len(base_margins)//2]:>+9.3f}"
              f"{base_inv:>7}{'':>7}{'':>9}  <- lexical only")

    best = None
    original_gate = match_service.SEMANTIC_GATE
    # Ranges narrowed by the first sweep. SEMANTIC_WEIGHT was dominated at
    # every gate/floor pair — blending into skills only diluted the token
    # score once the gate was doing the domain work — so it is swept thinly
    # here purely to confirm that holds, and the budget spent on gate and
    # floor, where the trend had not turned when the last sweep hit its
    # ceiling at 0.9.
    original_norm = match_service.SEMANTIC_NORMALIZE
    match_service.SEMANTIC_WEIGHT = 0.0      # dominated in both prior sweeps

    for norm in (True, False):
        match_service.SEMANTIC_NORMALIZE = norm
        # With normalisation on, min-max already floors adaptively at the
        # weakest candidate, so a hand-set floor largely duplicates it.
        for floor in ((0.0, 0.2) if norm else (0.15, 0.2, 0.25)):
            for gate in (0.5, 0.7, 0.8, 0.9, 1.0):
                cv_embedding.SEMANTIC_FLOOR = floor
                match_service.SEMANTIC_GATE = gate
                margins, inversions, zeroed, tops, names = [], 0, 0, [], []
                for cv_id, cv_name, data in cvs:
                    rows, _ = score_cv(data, listings, labels, vectors.get(cv_id))
                    st = summarise(rows)
                    if st:
                        margins.append(st["margin"])
                        names.append(cv_name)
                        inversions += st["inversions"]
                        zeroed += st["zeroed"]
                        tops.append(max(r["score"] for r in rows))
                if not margins:
                    continue
                passing = sum(1 for m in margins if m > 0)
                median = sorted(margins)[len(margins) // 2]
                # Mean top score: the number SRS-055 puts on the card for a
                # person's best match. A setting that ranks perfectly and
                # shows everyone 0.04 is not shippable, and the margin
                # columns cannot see that.
                top = sum(tops) / len(tops)
                print(f"{'Y' if norm else 'N':>5}{gate:>6}{floor:>7}"
                      f"{passing:>8}/{len(margins):<3}{min(margins):>+9.3f}"
                      f"{median:>+9.3f}{inversions:>7}{zeroed/len(margins):>7.1f}"
                      f"{top:>9.3f}")
                # Shippability is a gate on eligibility, not a tiebreak.
                # Ranked purely on separation, a flattened setting wins:
                # driving scores to zero improves margin and inversions
                # while destroying the ranking and the displayed number.
                if top < 0.35 or zeroed / len(margins) > 2.0:
                    continue
                scored = [m for n, m in zip(names, margins) if not is_known_hard(n)]
                if not scored:
                    scored = margins
                key = (sum(1 for m in scored if m > 0),
                       round(sorted(scored)[len(scored) // 2], 3),
                       round(top, 3))
                if best is None or key > best[0]:
                    best = (key, norm, gate, floor, top)
    match_service.SEMANTIC_WEIGHT = original
    match_service.SEMANTIC_GATE = original_gate
    match_service.SEMANTIC_NORMALIZE = original_norm
    cv_embedding.SEMANTIC_FLOOR = original_floor
    if best:
        print(f"\n  best shippable: SEMANTIC_NORMALIZE={best[1]}, "
              f"SEMANTIC_GATE={best[2]}, SEMANTIC_FLOOR={best[3]}")
        print(f"  mean top score {best[4]:.3f} — what the person sees on their "
              "best match.")
        print(f"  Ranked on the {len(cvs) - sum(1 for _, n, _ in cvs if is_known_hard(n))} "
              "scoreable CVs, among settings with top >= 0.35 and under 2")
        print("  zero-scored listings per CV. Settings failing those are excluded,")
        print("  not merely ranked lower — flattening the list improves every")
        print("  margin column while destroying the ranking.")
    else:
        print("\n  No setting met the shippability bar (top >= 0.35, "
              "zero/cv <= 2).")


def main():
    parser = argparse.ArgumentParser(
        description="Measure dev-vs-chef separation in the matching algorithm."
    )
    parser.add_argument("--detail", metavar="CV_ID_PREFIX",
                        help="print the full ranked table for one CV")
    parser.add_argument("--sweep", action="store_true",
                        help="sweep the semantic settings")
    parser.add_argument("--sweep-skills", action="store_true",
                        help="sweep SKILL_NORMALISE and SKILL_PARTIAL_CREDIT")
    parser.add_argument("--semantic", type=float, metavar="W",
                        help="score once at this SEMANTIC_WEIGHT")
    parser.add_argument("--floor", type=float, metavar="F",
                        help="score once at this SEMANTIC_FLOOR")
    parser.add_argument("--gate", type=float, metavar="G",
                        help="score once at this SEMANTIC_GATE")
    parser.add_argument("--semantic-report", action="store_true",
                        help="raw cosines by label, to diagnose the embeddings")
    parser.add_argument("--labels-only", action="store_true",
                        help="regenerate labels.json and exit")
    args = parser.parse_args()

    listings = match_service.retrieve_active_job_listings()
    print(f"Active listings: {len(listings)}")
    if not listings:
        raise SystemExit(
            "No active enriched listings. Run `python enrich_jobs.py`, or "
            "restore 2_data.sql if the enrichment is baked in."
        )

    if args.labels_only:
        labels, unlabelled = build_labels(listings)
        json.dump(labels, open(LABELS_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"  wrote {LABELS_FILE} ({Counter(labels.values())})")
        for jid, title in unlabelled:
            print(f"  UNLABELLED  {jid}  {title}")
        return

    labels = load_labels(listings)
    counts = Counter(labels.get(r["id"]) for r in listings)
    print(f"Labelled: {counts.get('dev', 0)} dev, {counts.get('chef', 0)} chef"
          + (f", {counts.get(None, 0)} unlabelled (excluded)" if counts.get(None) else ""))

    cvs = load_cvs()
    print(f"CVs with extracted data: {len(cvs)}")
    if not cvs:
        raise SystemExit("No usable CVs in the registry.")
    try:
        import cv_embedding
        floor = cv_embedding.SEMANTIC_FLOOR
    except Exception:
        floor = "n/a"
    print(f"Settings: UNSTATED_EDUCATION_RATIO="
          f"{match_service.UNSTATED_EDUCATION_RATIO}, "
          f"UNSTATED_EXPERIENCE_RATIO={match_service.UNSTATED_EXPERIENCE_RATIO}, "
          f"SEMANTIC_WEIGHT={match_service.SEMANTIC_WEIGHT}, "
          f"SEMANTIC_GATE={match_service.SEMANTIC_GATE}, "
          f"SEMANTIC_FLOOR={floor}")
    print(f"          SKILL_NORMALISE={match_service.SKILL_NORMALISE}, "
          f"SKILL_PARTIAL_CREDIT={match_service.SKILL_PARTIAL_CREDIT}")
    report_vector_coverage(listings)

    if args.semantic is not None:
        match_service.SEMANTIC_WEIGHT = args.semantic
        print(f"  SEMANTIC_WEIGHT overridden to {args.semantic}")
    if args.gate is not None:
        match_service.SEMANTIC_GATE = args.gate
        print(f"  SEMANTIC_GATE overridden to {args.gate}")
    if args.floor is not None:
        import cv_embedding
        cv_embedding.SEMANTIC_FLOOR = args.floor
        print(f"  SEMANTIC_FLOOR overridden to {args.floor}")

    if args.semantic_report:
        semantic_report(listings, labels, cvs)
    elif args.sweep_skills:
        sweep_skills(listings, labels, cvs)
    elif args.sweep:
        sweep(listings, labels, cvs)
    else:
        run(listings, labels, cvs, detail=args.detail)


if __name__ == "__main__":
    sys.exit(main())