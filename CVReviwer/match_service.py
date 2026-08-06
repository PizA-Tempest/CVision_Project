"""
match_service.py — Feature #2 (Job Matching) business logic

Implements M-02-02 (retrieveActiveJobListings), M-02-03 (compareSkills),
M-02-04 (compareEducation), M-02-05 (compareExperience), M-02-06
(calculateMatchScore), M-02-07 (identifyMatchedSkills), M-02-08
(rankJobMatches) and M-02-09 (storeJobMatchResults) for UC-006.

Layered like Feature 1: no Streamlit here, so every method is directly
testable. Reads job listings and enrichment through db.py (M-01-30/31/32) and
CV data through cv_data_adapter; the controller above adds the use-case
framing and the UI-facing entry points.

TWO THINGS THE DOCUMENT LEAVES OPEN, both recorded in TBD_and_Conflicts.md:

1. **The scoring algorithm is string-based, not semantic.** M-02-03 specifies
   "case-insensitive matching between each Skill.skill_name and the job's
   listed required skills", and M-02-06 combines three category ratios. That
   is what is implemented here. The existing app.py instead ranks by cosine
   similarity over SentenceTransformer embeddings — a different algorithm the
   document never mentions. The embeddings are still produced and stored
   (job_enrichment.embedding), but the documented scoring does not consult
   them. Whether to blend the semantic score in is a design decision for the
   owner, not one to make silently.

2. **Category weights are not specified.** M-02-06 says "weighted results"
   without giving weights. The choice below (skills 0.50, experience 0.30,
   education 0.20) is documented at CATEGORY_WEIGHTS and easy to change.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import db
import cv_data_adapter

# M-02-06's weighting. Not specified by the document — skills weigh most
# because a job match is primarily about capability, experience next because
# a years requirement is a hard filter for many listings, education least
# because it is absent from 5 of 14 sample listings and rarely decisive.
# Renormalised over whatever categories the CV actually has (SRS-058).
CATEGORY_WEIGHTS = {"skills": 0.50, "work_experience": 0.30, "education": 0.20}

SCORE_DECIMAL_PLACES = 3  # job_match.match_score is DECIMAL(4,3)

# Ordered lowest to highest, keyed by the canonical names enrich_jobs.py asks
# the model to return. Used by compareEducation to compare a CV's attained
# level against a listing's stated requirement.
DEGREE_LEVELS = {
    "high_school": (1, ("high school", "secondary school", "vocational certificate", "ปวช")),
    "diploma": (2, ("diploma", "associate degree", "associate's", "ปวส", "high vocational")),
    "bachelor": (3, ("bachelor", "bachelors", "bsc", "b.sc", "bs", "b.s", "ba", "b.a",
                     "beng", "b.eng", "undergraduate", "ปริญญาตรี")),
    "master": (4, ("master", "masters", "msc", "m.sc", "ms", "m.s", "ma", "m.a",
                   "meng", "m.eng", "mba", "postgraduate", "ปริญญาโท")),
    "doctorate": (5, ("doctorate", "doctoral", "phd", "ph.d", "dphil", "ปริญญาเอก")),
}
DEGREE_ORDINALS = {name: rank for name, (rank, _) in DEGREE_LEVELS.items()}

# Dropped when comparing field-of-study text, so "Bachelor's degree in
# Computer Science or related fields" reduces to {computer, science}.
_FIELD_STOPWORDS = {
    "a", "an", "and", "or", "the", "in", "of", "for", "with", "to", "at", "on",
    "degree", "degrees", "bachelor", "bachelors", "master", "masters", "doctorate",
    "phd", "diploma", "associate", "higher", "related", "field", "fields", "study",
    "studies", "equivalent", "any", "other", "similar", "relevant", "required",
    "minimum", "least", "years", "year", "experience", "graduate", "graduated",
    "school", "university", "college", "institute", "certificate",
}


class MatchingCalculationException(Exception):
    """
    Raised by calculate_match_score (M-02-06) when a score cannot be
    computed. Named to match M-02-06's documented Throws clause and mapped by
    M-02-12 to "Job matches could not be generated at this time" (SRS-060).
    """


class DatabaseException(Exception):
    """
    Raised by store_job_match_results (M-02-09) when persistence fails, after
    the transaction has rolled back.

    Named as M-02-09 documents it. Note Feature 1's storage layer raises
    `db.DatabaseError` for the same class of problem — the two names coexist
    because each is the name its own document uses; this one wraps that one.
    """


@dataclass
class SkillComparisonResult:
    """M-02-03's return type: "the overlapping skills and a skill match ratio"."""
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ratio: float = 0.0
    # The split behind the ratio, kept for explainability: a score of 0.2 on a
    # job requiring eight practical skills means something different from 0.2
    # on a job requiring two.
    matched_hard: list[str] = field(default_factory=list)
    matched_soft: list[str] = field(default_factory=list)
    hard_ratio: float = 0.0
    soft_ratio: float = 0.0


@dataclass
class EducationComparisonResult:
    """M-02-04's return type: "a qualification match indicator and an education match ratio"."""
    meets_requirement: bool = False
    ratio: float = 0.0
    detail: str = ""


@dataclass
class ExperienceComparisonResult:
    """M-02-05's return type: "a relevance indicator and an experience match ratio"."""
    is_relevant: bool = False
    ratio: float = 0.0
    cv_years: float = 0.0
    required_years: int | None = None


@dataclass
class JobMatchResult:
    """One scored listing. Consumed by M-02-08 and persisted by M-02-09."""
    job_listing_id: str
    score: float
    matched_skills: list[str] = field(default_factory=list)
    missing_categories: list[str] = field(default_factory=list)
    rank_position: int = 0
    listing: dict = field(default_factory=dict)


# ---------------------------------------------------------------------
# Shape normalisation
# ---------------------------------------------------------------------

def skill_name(skill) -> str:
    """
    Returns a skill's name from any of the shapes it actually arrives in.

    Three sources disagree: M-02-03 expects `Skill.skill_name`,
    `AIExtractionResult.skills` is typed `list[dict[str, Any]]`, and app.py's
    live prompt returns a plain `list[str]` ("skills": ["Python", "SQL"]).
    Rather than pick one and break on the others, every form is accepted —
    a string, or a dict under skill_name / name / skill.
    """
    if isinstance(skill, str):
        return skill.strip()
    if isinstance(skill, dict):
        for key in ("skill_name", "name", "skill", "title"):
            value = skill.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _norm(text) -> str:
    """Case-insensitive, punctuation-tolerant comparison key."""
    return re.sub(r"\s+", " ",
                  re.sub(r"[^a-z0-9+#.\u0e00-\u0e7f ]+", " ",
                         str(text or "").lower())).strip()


# Skills that describe how someone works rather than what they can do.
# Almost every job lists several, so they overlap between any CV and any
# listing and carry very little signal about whether the person can do the
# work. Kept separate from practical skills by compare_skills (SRS-049).
#
# Matched by exact normalised name, not substring: "creative" as a substring
# would classify "Adobe Creative Suite" as a soft skill, and "team" would
# catch "Microsoft Teams". A trailing "skill"/"skills"/"ability"/"abilities"
# is stripped first, so "Communication Skills" and "Communication" are the
# same entry.
SOFT_SKILL_TERMS = frozenset({
    # working with others
    "teamwork", "team work", "collaboration", "collaborative", "cooperation",
    "interpersonal", "communication", "verbal communication",
    "written communication", "presentation", "public speaking", "negotiation",
    "customer service", "customer focus", "client relations", "networking",
    "conflict resolution", "empathy", "emotional intelligence",
    "cultural awareness", "relationship building",
    # leading and organising
    "leadership", "management", "people management", "team management",
    "supervision", "mentoring", "coaching", "delegation", "decision making",
    "strategic thinking", "planning", "organization", "organisation",
    "organizational", "organisational", "time management", "prioritization",
    "prioritisation", "multitasking", "project coordination",
    # thinking
    "problem solving", "critical thinking", "analytical thinking",
    "analytical", "creativity", "innovation", "attention to detail",
    "detail oriented", "research", "logical thinking",
    # disposition
    "adaptability", "flexibility", "resilience", "work ethic", "reliability",
    "responsibility", "accountability", "initiative", "self motivated",
    "self motivation", "proactive", "punctuality", "patience", "positive attitude",
    "willingness to learn", "fast learner", "eagerness to learn", "hardworking",
    "hard working", "dedication", "commitment", "enthusiasm", "motivation",
    "independence", "working independently", "working under pressure",
    "stress management", "teamwork and collaboration",
    # Thai listings sometimes survive translation with these
    "มนุษยสัมพันธ์", "ทำงานเป็นทีม", "ความรับผิดชอบ",
})

# How compare_skills weights the two kinds when a listing has both.
# Practical skills carry nearly all of it: sharing "teamwork" with a job says
# almost nothing, while sharing "Python" says a great deal. Soft skills are
# not scored at zero because they are still a real, if weak, signal — and a
# listing that names only soft skills is scored on them alone.
HARD_SKILL_WEIGHT = 0.85
SOFT_SKILL_WEIGHT = 0.15

# Ceiling for a listing whose enrichment produced only soft skills. Such a
# listing tells us nothing about practical fit, so it should not be able to
# top the ranking on skills alone — but it must still be able to outscore the
# 0.15 a soft-only overlap earns elsewhere, or a candidate would be steered
# away from their own field. Poor enrichment is usually the cause; the
# education and experience categories carry the rest of the score.
SOFT_ONLY_CAP = 0.5

_SKILL_SUFFIXES = (" skills", " skill", " abilities", " ability")


def is_soft_skill(name) -> bool:
    """
    Whether a skill describes a way of working rather than a capability.

    Used by compare_skills to stop generic overlap ("teamwork",
    "communication") from outweighing the skills that decide whether someone
    can actually do the job — a programming CV was scoring higher against
    kitchen roles than against developer roles, because hospitality listings
    enrich to mostly soft skills and every CV matches those.
    """
    normalised = _norm(name)
    for suffix in _SKILL_SUFFIXES:
        if normalised.endswith(suffix):
            normalised = normalised[: -len(suffix)].strip()
            break
    if not normalised:
        return False
    if normalised in SOFT_SKILL_TERMS:
        return True
    # "excellent communication" / "strong leadership" — a qualifier in front
    # of a known term, which the model produces often.
    words = normalised.split()
    if len(words) > 1 and " ".join(words[1:]) in SOFT_SKILL_TERMS:
        if words[0] in {"excellent", "strong", "good", "great", "effective",
                        "outstanding", "solid", "proven", "exceptional"}:
            return True
    return False



def _degree_level(text) -> int:
    """
    Highest degree level mentioned in a piece of text; 0 when none.

    Matches on word boundaries, not substrings. The earlier substring version
    read "Chiang Mai University" as a Master's degree, because "ma" (for M.A.)
    appears inside "Mai" — which promoted essentially every Thai CV by a full
    degree level. "ba" inside "Bangkok" was the same trap. Thai keywords keep
    substring matching, since Thai is written without spaces and \\b does not
    apply.
    """
    lowered = str(text or "").lower()
    best = 0
    for rank, keywords in DEGREE_LEVELS.values():
        for keyword in keywords:
            if keyword.isascii():
                pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
                found = re.search(pattern, lowered)
            else:
                found = keyword in lowered
            if found:
                best = max(best, rank)
                break
    return best


def _required_degree_level(text) -> int:
    """
    The *lowest* degree level a requirement accepts; 0 when none is stated.

    A CV's level is a maximum — the highest degree attained. A requirement's
    is a floor, and requirements routinely name several levels: "Bachelor's or
    higher", "Bachelor/Master's degree". Reading the maximum there made
    "Bachelor/Master's degree in Computer Science" demand a Master's, so a
    Bachelor's graduate scored 0.560 and meets=False against a listing that
    would have accepted them.

    This mirrors the instruction enrich_jobs.py gives the model for
    min_degree_level ("use the LOWEST level that satisfies the listing"), so
    the free-text fallback and the structured path agree.
    """
    lowered = str(text or "").lower()
    found = []
    for rank, keywords in DEGREE_LEVELS.values():
        for keyword in keywords:
            if keyword.isascii():
                hit = re.search(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])", lowered)
            else:
                hit = keyword in lowered
            if hit:
                found.append(rank)
                break
    return min(found) if found else 0


def _singular(word: str) -> str:
    """
    Crude singulariser so "Sciences" matches "Science".

    Without it, "Degree in Computer Sciences or equivalent" scored 0% field
    overlap against a Computer Science degree — a CS graduate failing a CS
    requirement on a trailing letter. Deliberately minimal: enough for the
    plural forms that appear in qualification text, not a real stemmer.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("ses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _field_tokens(text) -> set[str]:
    """Meaningful field-of-study words, stopwords removed and singularised."""
    words = re.findall(r"[a-zA-Z][a-zA-Z+#.]{1,}", str(text or "").lower())
    return {
        _singular(w) for w in words
        if w not in _FIELD_STOPWORDS and len(w) > 2 and _singular(w) not in _FIELD_STOPWORDS
    }


def _split_field_alternatives(requirement) -> list[str]:
    """
    Splits a free-text qualification into the alternative fields it accepts.

    "Bachelor's degree in software engineering, computer engineering, computer
    science or related fields" lists three acceptable fields, any one of which
    qualifies. The earlier version pooled all their words into one required
    set and demanded overlap with the whole pool, so matching one alternative
    perfectly scored only a fraction — which is why a precise requirement
    scored *lower* than a vague "Bachelor's degree". Splitting on commas and
    "or"/"and" restores the intended meaning.

    Only used for rows with no structured education_requirement; enrichment
    now asks the model for these alternatives directly.
    """
    text = str(requirement or "").lower()
    # Drop the degree-level clause so it isn't mistaken for a field.
    text = re.sub(r"\b(bachelor|master|doctorate|diploma|associate|phd)('?s)?\b", " ", text)
    text = re.sub(r"\bor higher\b|\bdegree\b|\bor equivalent\b", " ", text)
    parts = re.split(r",|\bor\b|\band\b|/", text)
    alternatives = []
    for part in parts:
        tokens = _field_tokens(part)
        if tokens:
            alternatives.append(" ".join(sorted(tokens)))
    return alternatives


def _years_from(entry) -> float:
    """
    Duration in years of one work-experience entry.

    CV dates are free text from an LLM — "2020", "Jan 2020", "2020-03",
    "Present". Only 4-digit years are read; an open end ("Present", "Current",
    blank) counts to the current year. Returns 0.0 when no start year can be
    found, so an unparseable entry contributes nothing rather than breaking
    the sum.
    """
    if not isinstance(entry, dict):
        return 0.0
    start = re.search(r"(19|20)\d{2}", str(entry.get("start_date") or entry.get("start_year") or ""))
    if not start:
        return 0.0
    start_year = int(start.group())
    end_raw = str(entry.get("end_date") or entry.get("end_year") or "")
    end = re.search(r"(19|20)\d{2}", end_raw)
    if end:
        end_year = int(end.group())
    elif re.search(r"present|current|now|ปัจจุบัน", end_raw, re.IGNORECASE) or not end_raw.strip():
        end_year = datetime.now(timezone.utc).year
    else:
        return 0.0
    return max(0.0, float(end_year - start_year))


# ---------------------------------------------------------------------
# M-02-02
# ---------------------------------------------------------------------

def retrieve_active_job_listings() -> list[dict]:
    """
    M-02-02 — retrieveActiveJobListings() -> list

    Returns the active, non-outdated job listings available for matching,
    each joined with its Feature 2 enrichment.

    A conflict resolved here, recorded in TBD_and_Conflicts.md: M-02-02's
    description says "Filters out listings where outdated_manual is true",
    but SRS-048 says "active, **non-outdated**", and Feature 1 defines
    outdated as the manual flag OR the 365-day rule (M-01-27
    isSystemOutdated / SRS-029). Filtering on outdated_manual alone would
    offer a Jobseeker a listing posted 400 days ago that Feature 1's own Data
    tab labels "Outdated". This filters on both, matching SRS-048 and Feature
    1's established meaning; M-02-02's narrower wording appears to predate
    the 365-day rule.

    Listings with no enrichment row are excluded: without skills there is
    nothing for M-02-03 to compare, and a listing scoring 0.000 purely
    because the pipeline has not reached it yet would be misleading. Run
    enrich_jobs.py to bring them in.

    Parameters:
        -

    Returns:
        list[dict] — active listings with enrichment attached; [] when none
        qualify.

    Throws:
        -
    """
    rows = db.query(
        """
        SELECT l.id, l.url, l.job_title, l.company_name, l.job_location,
               l.job_details, l.job_employment_type, l.job_posted_date,
               l.salary, l.outdated_manual,
               e.skills, e.education, e.education_requirement,
               e.experience_years, e.work_mode,
               e.benefits, e.translated_description
        FROM job_listing l
        JOIN job_enrichment e ON e.job_listing_id = l.id
        """
    )
    active = []
    for row in rows:
        if bool(row.get("outdated_manual")):
            continue
        # Feature 1's 365-day rule, reused rather than reimplemented.
        if _is_system_outdated(row):
            continue
        row["skills"] = _decode_json(row.get("skills")) or []
        row["benefits"] = _decode_json(row.get("benefits")) or []
        row["education_requirement"] = _decode_json(row.get("education_requirement"))
        active.append(row)
    return active


def _is_system_outdated(row) -> bool:
    """
    Delegates to Feature 1's M-01-27 so the 365-day boundary is defined in
    exactly one place. Imported lazily: job_service pulls in log_service and
    the rest of the Feature 1 stack, which the pure comparison methods below
    have no need of.
    """
    import job_service
    return job_service.is_system_outdated(row)


def _decode_json(value):
    """job_enrichment's JSON columns arrive as strings from mysql-connector."""
    if isinstance(value, (list, dict)) or value is None:
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# M-02-03, M-02-07
# ---------------------------------------------------------------------

def compare_skills(cv_skills, job_skills) -> SkillComparisonResult:
    """
    M-02-03 — compareSkills(cvSkills: list, jobSkills: list) -> SkillComparisonResult

    Case-insensitive comparison of the CV's skills against the listing's
    required skills.

    The ratio is matched / required — the proportion of what the job asks for
    that the CV covers. Not matched / CV-skills, which would punish a broad
    CV for listing skills the job never mentioned.

    Practical and soft skills are scored separately and combined at
    HARD_SKILL_WEIGHT / SOFT_SKILL_WEIGHT. Treating them alike meant a
    programming CV scored higher against kitchen roles than against developer
    roles: hospitality listings enrich to mostly soft skills, every CV matches
    "teamwork" and "communication", and those overlaps outvoted the ones that
    decide whether the person can do the work. A listing naming only soft
    skills is still scored out of 1.0 on them.

    Parameters:
        cv_skills: list — Skills from the CV, in any shape skill_name accepts.
        job_skills: list[str] — Skills the listing requires.

    Returns:
        SkillComparisonResult — matched names (as the job spells them),
        missing names, and the ratio (0.000–1.000). A listing with no listed
        skills yields ratio 0.0 and no matches: nothing was asked for, so
        nothing can be demonstrated.

    Throws:
        -
    """
    job_names = [str(s).strip() for s in (job_skills or []) if str(s).strip()]
    if not job_names:
        return SkillComparisonResult(matched=[], missing=[], ratio=0.0)

    cv_keys = {_norm(skill_name(s)) for s in (cv_skills or []) if skill_name(s)}
    cv_keys.discard("")

    matched = [name for name in job_names if _norm(name) in cv_keys]
    missing = [name for name in job_names if _norm(name) not in cv_keys]

    # Score the two kinds separately, then combine. Pooling them let a CV
    # match a job on "teamwork" and "communication" alone and outscore a job
    # in its own field — see SOFT_SKILL_WEIGHT.
    hard_required = [n for n in job_names if not is_soft_skill(n)]
    soft_required = [n for n in job_names if is_soft_skill(n)]
    matched_hard = [n for n in matched if not is_soft_skill(n)]
    matched_soft = [n for n in matched if is_soft_skill(n)]

    hard_ratio = len(matched_hard) / len(hard_required) if hard_required else 0.0
    soft_ratio = len(matched_soft) / len(soft_required) if soft_required else 0.0

    if hard_required and soft_required:
        ratio = HARD_SKILL_WEIGHT * hard_ratio + SOFT_SKILL_WEIGHT * soft_ratio
    elif hard_required:
        ratio = hard_ratio
    elif soft_required:
        # A listing naming no practical skills at all offers no evidence that
        # the candidate can do the work, so it is capped rather than
        # renormalised to 1.0. Renormalising was the first attempt at this fix
        # and made the bug worse: a kitchen listing that enriched to only soft
        # skills scored the full 0.400 on "teamwork" and "communication" and
        # still beat a developer role the CV genuinely half-matched.
        #
        # The cap has to sit above what a soft-only *match* earns on a listing
        # that does name practical skills (at most SOFT_SKILL_WEIGHT, 0.15),
        # or a chef CV would rank developer jobs above kitchen ones purely
        # because those listings mention teamwork.
        ratio = soft_ratio * SOFT_ONLY_CAP
    else:
        ratio = 0.0

    return SkillComparisonResult(
        matched=matched,
        missing=missing,
        ratio=round(ratio, 6),
        matched_hard=matched_hard,
        matched_soft=matched_soft,
        hard_ratio=round(hard_ratio, 6),
        soft_ratio=round(soft_ratio, 6),
    )


def identify_matched_skills(cv_skills, job_skills) -> list[str]:
    """
    M-02-07 — identifyMatchedSkills(cvSkills: list, jobSkills: list) -> list

    The overlapping skills, as the tags SRS-053 displays on the job card.

    Parameters:
        cv_skills: list — Skills from the CV.
        job_skills: list[str] — Skills the listing requires.

    Returns:
        list[str] — matched skill tags; [] when there is no overlap, in which
        case matching continues on education and experience alone
        (Alternative Flow C).

    Throws:
        -
    """
    return compare_skills(cv_skills, job_skills).matched


# ---------------------------------------------------------------------
# M-02-04
# ---------------------------------------------------------------------

def compare_education(cv_education, job_requirement) -> EducationComparisonResult:
    """
    M-02-04 — compareEducation(cvEducation: list, jobRequirements) -> EducationComparisonResult

    Compares the CV's education against the listing's stated qualification.

    Accepts the requirement in either form:
      * the structured `education_requirement`
        ({"min_degree_level": "bachelor", "fields": [...]}), which
        enrich_jobs.py now asks the model to produce; or
      * the free-text `education` string, parsed here — the fallback for rows
        enriched before the structured column existed.

    Two things are compared: attained degree level against required level, and
    field of study. Level carries 0.6 of the ratio and field 0.4 — a Master's
    in an unrelated field should not outscore a Bachelor's in exactly the
    right one, but level is the harder requirement.

    Fields are **alternatives**, not a checklist: a listing accepting
    "computer science, computer engineering, or information technology" is
    fully satisfied by any one of them. Scoring the best-matching alternative
    rather than the pooled set is what stops a precise requirement from
    scoring lower than a vague one.

    Parameters:
        cv_education: list — Education entries from the CV
            ({institution, degree, start_year, end_year}).
        job_requirement: dict | str | None — structured requirement, free
            text, or nothing.

    Returns:
        EducationComparisonResult — whether the requirement is met, the ratio
        (0.000–1.000), and a short human-readable detail. When the listing
        states no requirement, returns meets_requirement=True with ratio 1.0.

    Throws:
        -
    """
    required_level, alternatives, raw_text = _parse_requirement(job_requirement)

    if required_level == 0 and not alternatives:
        return EducationComparisonResult(True, 1.0, "No qualification stated by the listing")

    entries = [e for e in (cv_education or []) if isinstance(e, (dict, str))]
    if not entries:
        return EducationComparisonResult(False, 0.0, "No education on the CV")

    # Institution is deliberately excluded from the level check: a university's
    # *name* says nothing about the degree attained, and including it is what
    # let "Chiang Mai University" register as a Master's. It still contributes
    # to field matching, where a name like "Faculty of Engineering" is a real
    # signal.
    degree_text = " ".join(
        str(e.get("degree", "")) if isinstance(e, dict) else str(e) for e in entries
    )
    field_text = " ".join(
        f"{e.get('degree','')} {e.get('field','')} {e.get('institution','')}"
        if isinstance(e, dict) else str(e)
        for e in entries
    )

    cv_level = _degree_level(degree_text)
    if required_level == 0:
        level_score = 1.0 if cv_level else 0.5
    elif cv_level == 0:
        level_score = 0.0
    elif cv_level >= required_level:
        level_score = 1.0
    else:
        # One level short scores partially rather than zero: a diploma
        # against a bachelor's requirement is closer than nothing.
        level_score = max(0.0, 1.0 - 0.4 * (required_level - cv_level))

    cv_fields = _field_tokens(field_text)
    if not alternatives:
        # No field named, so the field half cannot discriminate. Scoring it
        # 1.0 would let a vague requirement beat a precisely matched one, so
        # the ratio is the level score alone.
        ratio = round(level_score, 6)
        meets = cv_level >= required_level
        return EducationComparisonResult(
            meets, min(1.0, ratio),
            f"CV level {cv_level} vs required {required_level}; no field specified",
        )

    best_field_score = 0.0
    for alternative in alternatives:
        wanted = _field_tokens(alternative)
        if not wanted:
            continue
        overlap = len(wanted & cv_fields) / len(wanted)
        best_field_score = max(best_field_score, overlap)

    ratio = round(0.6 * level_score + 0.4 * best_field_score, 6)
    meets = cv_level >= required_level and best_field_score > 0.0
    detail = (
        f"CV level {cv_level} vs required {required_level}; "
        f"best field match {best_field_score:.0%} of {len(alternatives)} alternative(s)"
    )
    return EducationComparisonResult(meets, min(1.0, ratio), detail)


def _parse_requirement(job_requirement):
    """
    Normalises a listing's education requirement to
    (required_level_ordinal, field_alternatives, raw_text).

    Prefers the structured form written by enrich_jobs.py; falls back to
    parsing free text for rows that predate that column.
    """
    if isinstance(job_requirement, str):
        decoded = _decode_json(job_requirement)
        if isinstance(decoded, dict):
            job_requirement = decoded

    if isinstance(job_requirement, dict):
        level_name = job_requirement.get("min_degree_level")
        level = DEGREE_ORDINALS.get(level_name, 0) if isinstance(level_name, str) else 0
        fields = job_requirement.get("fields")
        alternatives = [f for f in fields if isinstance(f, str) and f.strip()] if isinstance(fields, list) else []
        return level, alternatives, json.dumps(job_requirement, ensure_ascii=False)

    text = str(job_requirement or "").strip()
    if not text:
        return 0, [], ""
    return _required_degree_level(text), _split_field_alternatives(text), text


# ---------------------------------------------------------------------
# M-02-05
# ---------------------------------------------------------------------

def compare_experience(cv_experience, required_years) -> ExperienceComparisonResult:
    """
    M-02-05 — compareExperience(cvExperience: list, jobRequirements) -> ExperienceComparisonResult

    Compares total years of work experience on the CV against the years the
    listing requires.

    Only duration is compared, not role relevance. The document says
    "e.g. minimum years, relevant role history", but a listing's enrichment
    carries only experience_years — there is no structured "relevant role"
    field to compare against, and inferring relevance from free-text titles
    would be guesswork dressed as a measurement. Duration is what the data
    actually supports; recorded in TBD_and_Conflicts.md.

    Parameters:
        cv_experience: list — Work-experience entries from the CV.
        required_years: int | None — job_enrichment.experience_years.

    Returns:
        ExperienceComparisonResult — whether the requirement is met, the
        ratio (0.000–1.000), and the years counted on each side. When the
        listing states no requirement, any experience scores 1.0 and none
        scores 0.5 — unstated is not the same as "none needed", so a CV with
        no experience is neither rewarded nor failed outright.

    Throws:
        -
    """
    entries = [e for e in (cv_experience or []) if isinstance(e, dict)]
    cv_years = round(sum(_years_from(e) for e in entries), 2)

    if required_years is None:
        if entries and cv_years > 0:
            return ExperienceComparisonResult(True, 1.0, cv_years, None)
        if entries:
            # Dates unparseable but the CV does list roles.
            return ExperienceComparisonResult(True, 0.75, cv_years, None)
        return ExperienceComparisonResult(False, 0.5, 0.0, None)

    required = max(0, int(required_years))
    if required == 0:
        return ExperienceComparisonResult(True, 1.0, cv_years, 0)
    ratio = min(1.0, cv_years / required)
    return ExperienceComparisonResult(cv_years >= required, round(ratio, 6), cv_years, required)


# ---------------------------------------------------------------------
# M-02-06
# ---------------------------------------------------------------------

def calculate_match_score(skill_result, education_result, experience_result,
                          available_categories) -> float:
    """
    M-02-06 — calculateMatchScore(skillResult, educationResult, experienceResult,
                                  availableCategories) -> number

    Combines the three comparison ratios into one score between 0.000 and
    1.000 (SRS-052), weighting only the categories the CV actually has and
    renormalising across them (SRS-058).

    So a CV with skills and experience but no education is scored on
    0.50 and 0.30 renormalised to 0.625 and 0.375 — it is not silently
    penalised for a category it never had.

    Parameters:
        skill_result: SkillComparisonResult
        education_result: EducationComparisonResult
        experience_result: ExperienceComparisonResult
        available_categories: list[str] — the CV categories containing data,
            as cv_data_adapter.available_categories returns them.

    Returns:
        float — the score, rounded to 3 decimals to match
        job_match.match_score's DECIMAL(4,3), clamped to [0.0, 1.0].

    Throws:
        MatchingCalculationException — when no category is available to score
        on, or a ratio is not a usable number. Both mean a score cannot
        honestly be produced, and M-02-12 turns this into SRS-060's message
        rather than showing a fabricated 0.000.
    """
    ratios = {
        "skills": getattr(skill_result, "ratio", None),
        "education": getattr(education_result, "ratio", None),
        "work_experience": getattr(experience_result, "ratio", None),
    }

    categories = [c for c in (available_categories or []) if c in CATEGORY_WEIGHTS]
    if not categories:
        raise MatchingCalculationException(
            "No CV categories available to score on — the CV has no skills, "
            "education or work experience."
        )

    total_weight = sum(CATEGORY_WEIGHTS[c] for c in categories)
    if total_weight <= 0:
        raise MatchingCalculationException("Category weights sum to zero.")

    score = 0.0
    for category in categories:
        ratio = ratios.get(category)
        if ratio is None or not isinstance(ratio, (int, float)) or ratio != ratio:
            raise MatchingCalculationException(
                f"Comparison for {category!r} produced no usable ratio."
            )
        score += (CATEGORY_WEIGHTS[category] / total_weight) * max(0.0, min(1.0, float(ratio)))

    return round(max(0.0, min(1.0, score)), SCORE_DECIMAL_PLACES)


# ---------------------------------------------------------------------
# M-02-08
# ---------------------------------------------------------------------

def rank_job_matches(matches) -> list[JobMatchResult]:
    """
    M-02-08 — rankJobMatches(matches: list) -> list

    Sorts matches by score, highest first (SRS-054), and assigns
    rank_position starting at 1.

    Ties are broken by matched-skill count then job_listing_id so the order is
    deterministic: two runs over unchanged data must produce the same ranking,
    or a stored rank_position would not reproduce what the Jobseeker saw.

    Parameters:
        matches: list[JobMatchResult] — scored, unranked.

    Returns:
        list[JobMatchResult] — the same objects, ordered and with
        rank_position set. [] in, [] out.

    Throws:
        -
    """
    ordered = sorted(
        list(matches or []),
        key=lambda m: (-float(m.score), -len(m.matched_skills or []), str(m.job_listing_id)),
    )
    for position, match in enumerate(ordered, start=1):
        match.rank_position = position
    return ordered


# ---------------------------------------------------------------------
# M-02-09
# ---------------------------------------------------------------------

def store_job_match_results(cv_id, matches) -> None:
    """
    M-02-09 — storeJobMatchResults(cvId: str, matches: list) -> None

    Persists ranked results to the job_match table, recording the score,
    matched skill tags and missing CV categories for each listing evaluated.

    A CV's previous results are deleted and rewritten in the same transaction,
    so a re-match replaces rather than accumulates and no reader sees a
    half-updated ranking. Ranking all listings, not a top-N, per the decision
    to reduce later only if volume demands it.

    Parameters:
        cv_id: str — the CV the matches belong to.
        matches: list[JobMatchResult] — ranked results, as M-02-08 returns.

    Returns:
        None

    Throws:
        DatabaseException — any insert failed; the transaction is rolled back
        and the CV's previous results survive intact, as M-02-09 specifies.
    """
    if not cv_id:
        raise DatabaseException("A CV id is required to store match results.")

    now = datetime.now(timezone.utc)
    try:
        with db.transaction() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM job_match WHERE cv_id = %s", (cv_id,))
                for match in matches or []:
                    cursor.execute(
                        """
                        INSERT INTO job_match
                            (id, cv_id, job_listing_id, match_score, matched_skills,
                             missing_categories, rank_position, computed_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            str(uuid.uuid4()),
                            cv_id,
                            match.job_listing_id,
                            round(float(match.score), SCORE_DECIMAL_PLACES),
                            json.dumps(match.matched_skills or [], ensure_ascii=False),
                            json.dumps(match.missing_categories or [], ensure_ascii=False),
                            int(match.rank_position),
                            now,
                        ),
                    )
            finally:
                cursor.close()
    except db.DatabaseError as ex:
        raise DatabaseException(
            "Unable to write to the job_match table."
        ) from ex


def load_job_match_results(cv_id) -> list[dict]:
    """
    Reads back a CV's stored matches in rank order, joined with the listing
    fields the job card displays.

    Not an M-numbered method: M-02-10 displayJobMatchResults is the *rendering*
    step and lives in the UI layer, but it needs the data from somewhere, and
    job_match is this module's table. Marked "To be documented".

    Parameters:
        cv_id: str

    Returns:
        list[dict] — one row per stored match, rank 1 first; [] when the CV
        has never been matched.
    """
    rows = db.query(
        """
        SELECT m.id, m.cv_id, m.job_listing_id, m.match_score, m.matched_skills,
               m.missing_categories, m.rank_position, m.computed_at,
               l.url, l.job_title, l.company_name, l.job_location,
               l.job_employment_type, l.salary, l.outdated_manual,
               e.skills, e.translated_description, e.work_mode
        FROM job_match m
        JOIN job_listing l ON l.id = m.job_listing_id
        LEFT JOIN job_enrichment e ON e.job_listing_id = m.job_listing_id
        WHERE m.cv_id = %s
        ORDER BY m.rank_position
        """,
        (cv_id,),
    )
    for row in rows:
        row["matched_skills"] = _decode_json(row.get("matched_skills")) or []
        row["missing_categories"] = _decode_json(row.get("missing_categories")) or []
        row["skills"] = _decode_json(row.get("skills")) or []
        row["match_score"] = float(row["match_score"]) if row.get("match_score") is not None else 0.0
    return rows


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------

def match_cv_against_listings(cv_id) -> list[JobMatchResult]:
    """
    Runs the full UC-006 comparison for one CV: read the CV data, read active
    listings, compare each on all three categories, score, rank, persist.

    Not an M-numbered method — it is the sequence UC-006's Normal Flow
    describes across Steps 1–9, which the document expresses as a flow rather
    than a method. Keeping it here means the controller stays thin, matching
    Feature 1's split. Marked "To be documented".

    Parameters:
        cv_id: str

    Returns:
        list[JobMatchResult] — ranked, already stored.

    Throws:
        cv_data_adapter.CVDataCorruptedException — CV data unusable (SRS-061).
        MatchingCalculationException — a score could not be computed.
        DatabaseException — results could not be stored.
    """
    cv_data = cv_data_adapter.get_extracted_cv_data(cv_id)
    available = cv_data_adapter.available_categories(cv_data)
    missing = [c for c in cv_data_adapter.CV_CATEGORIES if c not in available]

    listings = retrieve_active_job_listings()
    results = []
    for listing in listings:
        skill_result = compare_skills(cv_data["skills"], listing.get("skills"))
        education_result = compare_education(
            cv_data["education"],
            # Prefer the structured requirement; fall back to the free text
            # for rows enriched before that column existed.
            listing.get("education_requirement") or listing.get("education"),
        )
        experience_result = compare_experience(
            cv_data["work_experience"], listing.get("experience_years")
        )
        score = calculate_match_score(skill_result, education_result, experience_result, available)
        results.append(JobMatchResult(
            job_listing_id=listing["id"],
            score=score,
            matched_skills=skill_result.matched,
            missing_categories=missing,
            listing=listing,
        ))

    ranked = rank_job_matches(results)
    store_job_match_results(cv_id, ranked)
    return ranked