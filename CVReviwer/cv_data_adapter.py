"""
cv_data_adapter.py — Feature 2's read-only bridge to Feature 3's CV store

Feature 2 (Job Matching) needs the structured CV information that Feature 3
(CV Upload & Parsing) extracts: skills, education and work experience. This
module is the single place that knows *where* that data lives.

WHY AN ADAPTER RATHER THAN A DIRECT READ
========================================
Feature 3 persists to `cvs.json` through its own `_load_cvs()` / `_save_cvs()`
helpers. Those helpers are not M-numbered, so redirecting them to MySQL would
not alter any approved method's code — but Feature 3's test suite patches
`cv_upload.CVS_REGISTRY_FILE` to a temp file, and moving to MySQL would render
that patching inert and break his approved 125-test suite. So Feature 3 stays
on JSON, and Feature 2 reads it from here.

Consequences, all deliberate and recorded in TBD_and_Conflicts.md Part 4:

  * The system runs mixed storage — MySQL for Features 1 and 2, JSON for
    Feature 3. This file is the seam.
  * This module deliberately does NOT import cv_upload. Importing it would
    couple Feature 2 to Feature 3's module (and drag in pikepdf and PyPDF2
    for a JSON read), and would mean a change on his side could break
    matching. It reads the same file independently instead.
  * Because it doesn't import cv_upload, the file path is duplicated here.
    If Feature 3's CVS_REGISTRY_FILE ever changes, this constant must change
    with it. That duplication is the price of the decoupling; the alternative
    was a coupling that costs more.

If Feature 3 later moves to MySQL, only this file changes.

READS ONLY with respect to Feature 3. Feature 2 never writes to cvs.json —
writing extracted CV data is M-03-09 storeExtractedCVInfo's job, and it stays
that way. The ownership helpers at the foot of this file do write, but to
MySQL's jobseeker_cv table, which is Feature 2/5's own.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

# Mirrors cv_upload.CVS_REGISTRY_FILE. Overridable so tests (and a future
# relocation of the file) don't have to edit source.
CV_REGISTRY_FILE = os.environ.get("CV_REGISTRY_FILE", "cvs.json")

# The three categories Feature 3 extracts, as M-03-09 writes them. Note the
# key is "work_experience" on disk even though the dataclass field is
# `workExperience` — storeExtractedCVInfo renames it when persisting, and
# what's on disk is what matters here.
CV_CATEGORIES = ("skills", "education", "work_experience")


class CVDataCorruptedException(Exception):
    """
    Raised when a CV's stored data cannot be read as usable structured
    information — the record is missing, has never been through extraction,
    or the registry file itself is unreadable.

    Named to match M-02-01's documented Throws clause: "CVDataCorruptedException
    — if the stored CV data is detected as corrupted or unreadable; prompts the
    Jobseeker to re-upload their CV (Exception Flow E2)". M-02-01 raises this
    straight through to satisfy SRS-061; defining it here rather than in
    match_service keeps it with the code that actually detects the condition.
    """


def _load_registry() -> list[dict[str, Any]]:
    """
    Reads the whole CV registry. Mirrors Feature 3's `_load_cvs()`, including
    its behaviour of returning [] for a missing or unparseable file rather
    than raising — a fresh install has no cvs.json, and that is not an error.
    """
    try:
        with open(CV_REGISTRY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def get_cv_record(cv_id: str) -> dict[str, Any] | None:
    """
    Returns the raw registry record for a CV, or None when no record matches.

    Parameters:
        cv_id: str — the identifier Feature 3 assigned at upload
            (`uuid.uuid4().hex`, 32 characters).

    Returns:
        dict | None — the record as stored, including upload metadata and,
        once M-03-09 has run, an "extracted_data" key.
    """
    if not cv_id:
        return None
    for record in _load_registry():
        if record.get("id") == cv_id:
            return record
    return None


def get_extracted_cv_data(cv_id: str) -> dict[str, list]:
    """
    Returns the structured CV information Feature 2 matches against.

    This is the storage half of M-02-01 retrieveCVData. M-02-01 itself lives
    in the Feature 2 service layer and adds the use-case framing; this
    function only answers "what did Feature 3 store for this CV".

    Parameters:
        cv_id: str — the CV identifier.

    Returns:
        dict — {"skills": [...], "education": [...], "work_experience": [...]}.
        Every key is always present, always a list. A category the CV simply
        didn't contain comes back as [] rather than missing, so callers can
        compute M-02-06's `availableCategories` by truthiness without
        defensive key checks.

    Throws:
        CVDataCorruptedException — the record doesn't exist, has no
            "extracted_data" (extraction never ran or never persisted), the
            extracted_data isn't a mapping, or every category is unusable.
            All four are cases where the Jobseeker must re-upload, which is
            exactly what SRS-061 specifies, so they share one exception
            rather than being distinguished for their own sake.
    """
    record = get_cv_record(cv_id)
    if record is None:
        raise CVDataCorruptedException(
            f"No stored CV found for id {cv_id!r}. Please re-upload your CV."
        )

    extracted = record.get("extracted_data")
    if extracted is None:
        # Distinguished in the message because this is the *expected* state
        # until app.py is rewired to call the M-03 chain (Phase 3, Step 6):
        # today Feature 3's storeExtractedCVInfo is never invoked, so every
        # record in cvs.json lacks this key. A caller hitting this is far
        # more likely looking at unwired plumbing than a damaged file.
        raise CVDataCorruptedException(
            f"CV {cv_id!r} has no extracted data — it was uploaded but never "
            f"parsed, or the parse result was not stored. Please re-upload "
            f"your CV."
        )
    if not isinstance(extracted, dict):
        raise CVDataCorruptedException(
            f"CV {cv_id!r} has malformed extracted data. Please re-upload your CV."
        )

    result: dict[str, list] = {}
    for category in CV_CATEGORIES:
        value = extracted.get(category)
        # Feature 3's AIExtractionResult types all three as list[dict], but
        # what lands on disk is whatever the AI returned. Anything that isn't
        # a list is treated as absent rather than propagated, so a malformed
        # single category degrades to "missing" — which SRS-058 already
        # handles by reweighting — instead of breaking the whole match.
        result[category] = list(value) if isinstance(value, list) else []

    if not any(result.values()):
        raise CVDataCorruptedException(
            f"CV {cv_id!r} has no usable skills, education or work experience. "
            f"Please re-upload your CV."
        )

    return result


def available_categories(cv_data: dict[str, list]) -> list[str]:
    """
    Returns the category names that actually contain data.

    Feeds M-02-06 calculateMatchScore's `availableCategories` parameter, which
    drives SRS-058's weighting adjustment, and M-02-09's stored
    `missing_categories`. Kept here beside get_extracted_cv_data so the
    definition of "available" lives with the shape it inspects.

    Parameters:
        cv_data: dict — as returned by get_extracted_cv_data.

    Returns:
        list[str] — a subset of CV_CATEGORIES, in that fixed order so a
        stored missing_categories list is comparable between runs.
    """
    return [c for c in CV_CATEGORIES if cv_data.get(c)]


def list_cv_ids() -> list[str]:
    """
    Returns every CV id in the registry, newest upload first.

    Not part of any M-02 method. The Feature 2 UI needs a way to pick which
    stored CV to match against while there is no authentication to identify
    the Jobseeker (Feature #5) — the same gap Feature 1's admin login has.
    Marked "To be documented" in TBD_and_Conflicts.md.
    """
    records = _load_registry()
    records.sort(key=lambda r: r.get("uploaded_at") or "", reverse=True)
    return [r["id"] for r in records if r.get("id")]


# ---------------------------------------------------------------------
# CV ownership — the jobseeker_cv table
#
# These write to MySQL, not to cvs.json. The read-only guarantee above is
# about Feature 3's store, which is never written here; jobseeker_cv is a
# Feature 2/5 table and its rows are ours to maintain.
#
# M-03-05 storeCVFile already records jobseekerId inside the JSON record,
# so this table is a queryable index over the same fact rather than a second
# source of truth. If the two ever disagree, cvs.json is authoritative.
# ---------------------------------------------------------------------

def record_cv_ownership(jobseeker_id, cv_id, original_filename=None, uploaded_at=None) -> bool:
    """
    Records which Jobseeker uploaded a CV, so Feature 5's "My CVs" picker can
    list one person's uploads rather than everyone's.

    Not an M-numbered method — authentication is Feature 5 and nothing in
    Feature 2's document covers ownership. Called on every upload so the rows
    accumulate from now on and Feature 5 inherits a populated index.

    Best-effort by design: a failure here is swallowed and reported as False.
    Losing the ownership index costs a future convenience feature; raising
    would abort an upload that has already succeeded and been stored by
    Feature 3, which is a far worse outcome for the Jobseeker in front of the
    screen.

    Parameters:
        jobseeker_id: str — stand-in identifier until Feature 5 supplies one.
        cv_id: str — the id Feature 3 assigned at upload.
        original_filename: str | None
        uploaded_at: datetime | None — defaults to now.

    Returns:
        bool — True when the row was written.
    """
    if not jobseeker_id or not cv_id:
        return False
    import db
    try:
        db.execute(
            """
            INSERT INTO jobseeker_cv (id, jobseeker_id, cv_id, original_filename, uploaded_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                jobseeker_id = VALUES(jobseeker_id),
                original_filename = VALUES(original_filename),
                uploaded_at = VALUES(uploaded_at)
            """,
            (
                str(uuid.uuid4()),
                str(jobseeker_id),
                str(cv_id),
                original_filename,
                uploaded_at or datetime.now(timezone.utc),
            ),
        )
        return True
    except Exception:
        return False


def list_cv_ids_for(jobseeker_id) -> list[dict]:
    """
    Returns one Jobseeker's uploaded CVs, newest first — the query behind a
    "My CVs" picker.

    Reads the jobseeker_cv index, then confirms each id still exists in
    Feature 3's registry: cvs.json is authoritative, and a CV deleted there
    should disappear from the picker even though the index row survives.

    Parameters:
        jobseeker_id: str

    Returns:
        list[dict] — {cv_id, original_filename, uploaded_at}; [] when the
        Jobseeker has none, or the index is unavailable.
    """
    if not jobseeker_id:
        return []
    import db
    try:
        rows = db.query(
            "SELECT cv_id, original_filename, uploaded_at FROM jobseeker_cv "
            "WHERE jobseeker_id = %s ORDER BY uploaded_at DESC",
            (str(jobseeker_id),),
        )
    except Exception:
        return []
    known = {r.get("id") for r in _load_registry()}
    return [r for r in rows if r.get("cv_id") in known]
