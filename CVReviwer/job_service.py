"""
job_service.py — Business Logic for Job Listings

Implements M-017 (loadListings), M-020 (saveListing), M-026
(saveListings), and M-027 (isSystemOutdated) for UC-F1-004 (View and
Manage Job Listings).

Storage access goes through db.py: query() (M-030) for reads, and
transaction() (M-032) for the listings write — or, since C3, a
connection handed down by a caller that is grouping this write with
others (see save_listings' conn parameter). db.py owns connections,
commits and rollbacks; the SQL statements themselves live here, in the
module that owns the job_listing table.

save_listing() also calls log_service.append_log(), since M-020's own
description requires it ("appends a 'job_edit' activity-log entry"),
matching SRS-027 — even though the UC-F1-004 sequence diagram doesn't
draw that message explicitly (only 'job_mark' and 'job_delete' are
drawn there); the Method Description and SRS are treated as
authoritative over that omission.
"""

import uuid
from datetime import datetime, timedelta, timezone

import db
import log_service

OUTDATED_THRESHOLD_DAYS = 365

_EDITABLE_FIELDS = (
    "url", "job_title", "company_name", "job_location",
    "job_details", "job_employment_type", "job_posted_date", "salary",
)

# Fallback string formats for job_posted_date. db.query() normally
# returns a native datetime for a proper TIMESTAMP/DATETIME column,
# but this also has to accept a string — e.g. a raw provider record
# passed straight to isSystemOutdated before it's ever been through
# saveListings — mirroring the multi-format parsing the original
# _is_outdated / _is_system_outdated helpers did for JSON-stored dates.
_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S UTC",
    "%Y-%m-%d %H:%M UTC",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def _format_posted_date(value):
    """
    Renders job_posted_date — a Timestamp column per the Data
    Dictionary — in the ISO-8601 UTC form the test cases expect
    ("2026-06-09T20:12:48.473Z", UT-1-16-001 / UT-1-17-001 /
    UT-1-20-001), or None when the column is NULL (UT-1-27-004).

    Deliberately a local copy of scraper_service.format_iso_z rather
    than an import: scraper_service already imports job_service (for
    execute's dedupe/save step), so importing back the other way would
    be a circular import. Both are three lines; see
    TBD_and_Conflicts.md.
    """
    dt = _parse_posted_date(value)
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_posted_date(value):
    """Returns a timezone-aware datetime for value, or None when value
    is empty (UT-1-27-004) or unparseable."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def is_system_outdated(job):
    """
    M-027 — isSystemOutdated(job: dict) -> bool

    Determines whether a listing is system-outdated by testing
    whether its posted date is 365 or more days old. Used when
    rendering listings (loadListings, M-017) and when deciding whether
    the manual unmark control must be locked (markOutdated, M-021, in
    job_controller.py).

    Parameters:
        job: dict — the job listing to evaluate; reads
            job["job_posted_date"].

    Returns:
        bool — True at 365+ days old, including the exact boundary
        (UT-1-27-001 at 400 days, UT-1-27-002 at exactly 365 days);
        False for a more recent posting (UT-1-27-003 at 30 days) or a
        missing posted date (UT-1-27-004).

        Note: the original _is_system_outdated used a strict ">"
        comparison, which would have left a listing posted exactly
        365 days ago classified as still active. UT-1-27-002 expects
        True at that exact boundary, matching SRS-029's wording ("365
        or more days old"), so this uses ">=" — a deliberate
        correction of that off-by-one, not a port of the original.

    Throws:
        -
    """
    posted = _parse_posted_date(job.get("job_posted_date"))
    if posted is None:
        return False
    return (datetime.now(timezone.utc) - posted) >= timedelta(days=OUTDATED_THRESHOLD_DAYS)


def load_listings():
    """
    M-017 — loadListings() -> list

    Reads the job_listing table and, for each listing, evaluates
    whether it is outdated — combining the manual outdated_manual
    flag with the automatic 365-day rule into one "outdated" status
    for display, the same combination the original _is_outdated
    helper made (isSystemOutdated alone only covers the automatic
    half). Maps to db.query(... FROM job_listing) + isSystemOutdated
    (M-027).

    Parameters:
        -

    Returns:
        list[dict] — listings annotated with an "outdated" key
        (UT-1-17-001/002/003).

    Throws:
        -
    """
    rows = db.query(
        "SELECT id, scraper_id, url, job_title, company_name, job_location, "
        "job_details, job_employment_type, job_posted_date, salary, outdated_manual "
        "FROM job_listing"
    )
    for row in rows:
        # Order matters: the 365-day rule is evaluated against the native
        # datetime db.query() returns, then job_posted_date is rendered to
        # the ISO-Z string the test cases expect (C1). is_system_outdated
        # accepts either form, so the sequence is defensive, not required.
        row["outdated"] = bool(row.get("outdated_manual")) or is_system_outdated(row)
        row["job_posted_date"] = _format_posted_date(row.get("job_posted_date"))
    return rows


def _write_listing_rows(cursor, jobs):
    """Clears job_listing and reinserts every row in `jobs` using the
    cursor it's given. Shared by both save_listings paths — its own
    transaction, or a caller's (see save_listings' conn parameter)."""
    cursor.execute("DELETE FROM job_listing")
    for job in jobs:
        cursor.execute(
            """
            INSERT INTO job_listing
                (id, scraper_id, url, job_title, company_name, job_location,
                 job_details, job_employment_type, job_posted_date, salary,
                 outdated_manual)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job.get("id") or str(uuid.uuid4()),
                job.get("scraper_id"),
                job.get("url"),
                job.get("job_title"),
                job.get("company_name"),
                job.get("job_location"),
                job.get("job_details"),
                job.get("job_employment_type") or None,
                # C1: job_posted_date is a Timestamp column, but the
                # value arriving here is whatever string the provider
                # returned (or an already-formatted ISO-Z string from
                # load_listings). Coerced to a real datetime; an
                # unparseable provider date becomes NULL, which the
                # 365-day rule then treats as "not outdated"
                # (UT-1-27-004's behaviour) rather than crashing the
                # whole save — see TBD_and_Conflicts.md.
                _parse_posted_date(job.get("job_posted_date")),
                job.get("salary") or None,
                bool(job.get("outdated_manual", False)),
            ),
        )


def save_listings(jobs, conn=None):
    """
    M-026 — saveListings(jobs: list) -> bool

    Persists the full job-listings collection to storage. Called
    after a fetch run appends new jobs (scraper_service.execute,
    M-009), and after an edit (saveListing, M-020) or a delete/mark
    (job_controller.deleteListing / markOutdated, M-021/M-022) changes
    the collection.

    Implementation note: this contract carries over unchanged from
    the pre-MySQL JSON-file design, where _save_listings always
    rewrote the entire file with whatever list it was given — "jobs"
    here is the complete, already-updated collection, not a delta. To
    honor that same "the list I hand you IS the new state of the
    table" contract on MySQL, this clears job_listing and reinserts
    every row from `jobs` inside one db.transaction() (M-032), so the
    swap is atomic: either every row lands, or none does, and no
    reader ever sees a half-emptied table in between. A job dict
    missing "id" is treated as new and given one.

    Parameters:
        jobs: list[dict] — The complete listings collection to write.
        conn: connection | None — Not part of M-026's documented
            signature. When None (every documented call site — the
            edit, mark, and delete paths), this opens and commits its
            own db.transaction() exactly as before. When a caller
            passes its own open connection, the rows are written on
            that connection and the caller commits, so this write can
            join a larger atomic group. Added for C3: M-032 requires a
            fetch run's inserted listings and its updated last-run
            timestamp to "either both persist or neither does", which
            is impossible if this method always commits on its own.
            See TBD_and_Conflicts.md.

    Returns:
        bool — True when the collection was written (UT-1-26-001).
        When conn is supplied the rows are written but not yet
        committed; True means "written into your transaction".

    Throws:
        db.DatabaseError — "Unable to write to the job_listing
        table." when the write fails (UT-1-26-002), on both paths.
    """
    if conn is not None:
        try:
            cursor = conn.cursor()
            try:
                _write_listing_rows(cursor, jobs)
            finally:
                cursor.close()
        except Exception as ex:
            raise db.DatabaseError("Unable to write to the job_listing table.") from ex
        return True

    try:
        with db.transaction() as own_conn:
            cursor = own_conn.cursor()
            _write_listing_rows(cursor, jobs)
            cursor.close()
    except db.DatabaseError as ex:
        raise db.DatabaseError("Unable to write to the job_listing table.") from ex
    return True


def save_listing(listing_id, fields):
    """
    M-020 — saveListing(listing_id: str, fields: dict) -> dict

    Persists the edited listing to the job_listing table (optional
    fields stored as null when blank) and appends a "job_edit"
    activity-log entry (SRS-027). Maps to _save_listings (here,
    save_listings — M-026) + _append_log("job_edit", ...).

    Parameters:
        listing_id: str — Identifier of the listing being saved.
        fields: dict — The eight editable job fields (see
            _EDITABLE_FIELDS), already validated by
            validation_service.validate_required (called by
            job_controller.updateListing before this).

    Returns:
        dict — the saved listing's eight editable fields; a field
        left blank comes back as None (UT-1-20-001: blank
        job_employment_type / salary saved as null).

    Throws:
        db.DatabaseError — "Unable to write to the job_listing
        table." when the write fails (UT-1-20-002).
    """
    listings = load_listings()
    target = next((j for j in listings if str(j.get("id")) == str(listing_id)), None)
    if target is None:
        target = {"id": listing_id}
        listings.append(target)

    for name in _EDITABLE_FIELDS:
        value = fields.get(name)
        target[name] = value.strip() if isinstance(value, str) and value.strip() else None

    # C1: normalise the posted date to the same ISO-Z form load_listings
    # returns, so an edited listing reads back identically to a fetched one
    # (UT-1-20-001 expects "2026-06-09T20:12:48.473Z").
    target["job_posted_date"] = _format_posted_date(target.get("job_posted_date"))

    save_listings(listings)
    log_service.append_log("job_edit", target.get("job_title") or str(listing_id), "")
    return {name: target.get(name) for name in _EDITABLE_FIELDS}
