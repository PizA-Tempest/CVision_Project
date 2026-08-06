"""
match_controller.py — Feature #2 request-handling entry points

Implements M-02-01 (retrieveCVData), M-02-10 (displayJobMatchResults),
M-02-11 (openJobPosting) and M-02-12 (handleMatchingError) for UC-006.

Like Feature 1's controllers, these are plain Python functions with no
Streamlit calls of their own. M-02-10 and M-02-11 are described in the
document as rendering and navigation steps, which in a Flask design would
happen server-side; in Streamlit the rendering belongs to app.py. So each
returns the data or the decision app.py needs, and app.py draws it — the same
split used for M-01-16 getListings and M-01-07 getScrapers. Keeping this file
framework-free is also what makes it directly testable.
"""

from __future__ import annotations

from urllib.parse import urlparse

import db
import cv_data_adapter
import match_service
from cv_data_adapter import CVDataCorruptedException
from match_service import DatabaseException, MatchingCalculationException


class JobPostingUnavailableException(Exception):
    """
    Raised by open_job_posting (M-02-11) when a listing's URL is unusable.
    Named to match M-02-11's documented Throws clause; M-02-12 maps it to
    "This job posting is no longer available" and SRS-062 disables the link
    on that card while leaving the other cards alone.
    """


def retrieve_cv_data(cv_id) -> dict:
    """
    M-02-01 — retrieveCVData(cvId: str) -> CVData

    Returns the Jobseeker's structured CV information — skills, education and
    work experience — for matching.

    The document describes this as querying "the CV_extracted record along
    with its associated Skill, Education, and WORK_EXPERIENCE rows". Those
    tables do not exist: Feature 3 stores extracted CV data in cvs.json, and
    the decision to leave Feature 3 untouched means Feature 2 reads it from
    there through cv_data_adapter. The returned shape is what the document
    specifies; only the storage behind it differs. See TBD_and_Conflicts.md.

    Parameters:
        cv_id: str — the identifier of the Jobseeker's stored CV.

    Returns:
        dict — {"skills": [...], "education": [...], "work_experience": [...]}.
        Every key present, every value a list; a category the CV lacked is []
        rather than absent.

    Throws:
        CVDataCorruptedException — the stored CV data is missing, unparsed or
            unreadable; the Jobseeker is asked to re-upload (SRS-061,
            Exception Flow E2).
    """
    return cv_data_adapter.get_extracted_cv_data(cv_id)


def generate_job_matches(cv_id) -> list:
    """
    Runs the whole match for one CV and stores the result.

    Not an M-numbered method: UC-006's Normal Flow Steps 1–9 are a flow, not a
    method, and app.py needs one call to trigger them. Delegates to
    match_service.match_cv_against_listings. Marked "To be documented".

    Parameters:
        cv_id: str

    Returns:
        list[JobMatchResult] — ranked and persisted.

    Throws:
        CVDataCorruptedException, MatchingCalculationException,
        DatabaseException — all propagate for M-02-12 to translate.
    """
    return match_service.match_cv_against_listings(cv_id)


def display_job_match_results(cv_id) -> list[dict]:
    """
    M-02-10 — displayJobMatchResults(cvId: str) -> None

    Returns the stored, ranked job matches for a CV, each carrying what
    SRS-055's job card shows: title, company, location, score, matched skill
    tags and the posting link.

    Returns rather than renders, and so returns a list rather than the
    document's `void`: the document assumes a server that writes HTML, while
    here app.py owns the drawing. The data is what the document specifies.

    Reads what was stored rather than recomputing, so the ranking a Jobseeker
    revisits is the one that was saved (SRS-054), not a fresh calculation that
    might differ if listings changed in between.

    Parameters:
        cv_id: str — the CV whose matches to display.

    Returns:
        list[dict] — rank 1 first; [] when the CV has no stored matches or
        zero active listings existed (SRS-057, which app.py renders as the
        "no job listings currently available" message).

    Throws:
        -
    """
    return match_service.load_job_match_results(cv_id)


def open_job_posting(url) -> str:
    """
    M-02-11 — openJobPosting(url: str) -> None

    Validates a listing's posting URL before the Jobseeker is sent to it
    (SRS-056), and returns the URL for app.py to open in a new tab.

    Only the URL's form is checked, not whether the site responds. The
    document mentions "the external site is unreachable", but reaching out to
    every listing's server while rendering a page would make the results page
    as slow as the slowest job board and could hang it entirely. A malformed
    or missing URL is caught here; a dead-but-well-formed link is left to the
    browser. Recorded in TBD_and_Conflicts.md.

    Parameters:
        url: str — the posting URL stored on the job listing.

    Returns:
        str — the validated URL.

    Throws:
        JobPostingUnavailableException — the URL is missing or malformed. The
            caller disables that one card's link and leaves the rest
            untouched (SRS-062, Exception Flow E3).
    """
    if not url or not str(url).strip():
        raise JobPostingUnavailableException("This job posting has no link recorded.")
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise JobPostingUnavailableException(
            f"This job posting's link is not usable: {url!r}"
        )
    return str(url).strip()


def handle_matching_error(exception) -> str:
    """
    M-02-12 — handleMatchingError(exception: Exception) -> str

    Maps a matching exception to the message shown to the Jobseeker.

    The four strings below are quoted from M-02-12's own description and
    should not be reworded without changing the document too — they are what
    SRS-060, SRS-061 and SRS-062 promise the Jobseeker will see.

    Parameters:
        exception: Exception — raised during matching or display.

    Returns:
        str — the user-facing message. Unknown types get the generic message
        rather than leaking an internal error string.

    Throws:
        none.
    """
    if isinstance(exception, MatchingCalculationException):
        return "Job matches could not be generated at this time"
    if isinstance(exception, CVDataCorruptedException):
        return "Your CV data could not be read — please re-upload your CV"
    if isinstance(exception, JobPostingUnavailableException):
        return "This job posting is no longer available"
    if isinstance(exception, (DatabaseException, db.DatabaseError)):
        # Neither is named by M-02-12, but M-02-09 raises DatabaseException and
        # M-02-02 reads through db.query, so a storage failure at either point
        # reaches the same UI path. Both map to the calculation message, which
        # is what SRS-060 promises for "an internal error occurs" — the
        # Jobseeker cannot act on the difference between a failed calculation
        # and a failed read.
        #
        # db.DatabaseError was previously unmapped, so a plain SQL problem — a
        # missing table, a column added by a later schema revision — fell
        # through to the generic message below and gave no indication of what
        # was wrong.
        return "Job matches could not be generated at this time"
    return "An unexpected error occurred. Please try again"