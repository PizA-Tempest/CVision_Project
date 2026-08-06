"""
scraper_service.py — Business Logic for Provider Profiles, Scrapers,
and Fetch Runs

Implements M-002 (getProfile), M-005 (buildCurl), M-006 (saveScraper),
M-009 (execute), M-010 (pollSnapshot), M-013 (persistSchedule), M-015
(getDueScrapers), M-024 (sendRequest), and M-025 (applyFieldMap) for
UC-F1-001 (Create Scraper), UC-F1-002 (Fetch Jobs), and UC-F1-003
(Schedule Job Fetching).

Talks to storage exclusively through db.py, to job_service.py for job
listings (execute() dedupes/saves through job_service, not by writing
job_listing directly), and to log_service.py for the two writes whose
own Method Description explicitly folds logging into the method itself
(saveScraper -> "add", persistSchedule -> "schedule"). See each
function's docstring, and TBD_and_Conflicts.md, for the several places
this file had to make a judgment call the source documents didn't
settle outright — this is the most ambiguous file built so far.
"""

import json
import shlex
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

import db
import job_service
import log_service

POLL_INTERVAL_SECONDS = 60
POLL_MAX_ATTEMPTS = 10

_JOB_FIELDS = (
    "url", "job_title", "company_name", "job_location",
    "job_details", "job_employment_type", "job_posted_date", "salary",
)

_DATETIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S UTC",
    "%Y-%m-%d %H:%M UTC",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


class APIError(Exception):
    """Raised by send_request() when the external provider returns a
    non-2xx status (e.g. 401 Unauthorized)."""


# ---------------------------------------------------------------------
# Small private helpers (parsing/formatting only — no named M-XXX
# method covers these; kept private since, unlike list_scrapers() and
# _parse_curl() below, nothing outside this file needs to call them).
# ---------------------------------------------------------------------

def coerce_datetime(value):
    """Returns a timezone-aware datetime for value (native datetime,
    one of _DATETIME_FORMATS, or a general ISO-8601 string with an
    explicit +HH:MM offset), or None if empty/unparseable."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# To be documented — see TBD_and_Conflicts.md
def format_display_datetime(value):
    """
    Renders a Timestamp column as the "last run" display string the
    Method Description's test cases expect — "2026-06-09 20:12 UTC"
    (UT-1-07-001, UT-1-13-001), or "-" when the column is NULL
    (UT-1-06-001/002, a scraper that has never run).

    Half of the C1 fix: the Data Dictionary types
    Scraper.last_request_date as a Timestamp, but the test cases show
    it as these display strings. Storing a real datetime (or NULL) in
    the column and formatting here — at the boundary where the tests
    observe it — satisfies both documents at once, instead of writing
    "-" into a DATETIME column, which MySQL rejects outright.
    """
    dt = coerce_datetime(value)
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "-"


# To be documented — see TBD_and_Conflicts.md
def format_iso_z(value):
    """
    Renders a Timestamp column in the ISO-8601 UTC form the Data
    Dictionary uses for its own examples and the test cases expect for
    schedule times — "2026-07-01T08:00:00Z" (UT-1-12-002, UT-1-15-001)
    — or None when the column is NULL (UT-1-28-001's last_auto_run).

    Milliseconds are included only when non-zero, matching the two
    documented shapes: the Data Dictionary's
    JobListing.job_posted_date example carries them
    ("2026-06-09T20:12:48.473Z") while its Schedule.run_at example
    does not ("2026-07-01T08:00:00Z").
    """
    dt = coerce_datetime(value)
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_parse_resp(text):
    """Parses a provider response body as JSON, falling back to NDJSON
    (one JSON object per line) — BrightData-style APIs use both."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        results = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return results


def _normalise_response(data):
    """Unwraps a provider response into a flat list of raw job dicts,
    whether the provider returned a bare list or wrapped it under a
    "results"/"data"/"jobs"/"items" key."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "data", "jobs", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _extract_error_message(response):
    """Builds a human-readable message for APIError. Providers like
    BrightData return a JSON body describing what went wrong (e.g.
    {"error": "Invalid credentials"}) rather than just an HTTP status
    line — this is an inferred convention (see TBD_and_Conflicts.md),
    since neither the Method Description nor its test cases state
    which field to read; it checks a few common ones and falls back
    to the plain status line (which is what produces "401
    Unauthorized" for UT-1-09-004)."""
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        for key in ("error", "message", "error_message"):
            if data.get(key):
                return str(data[key])
    return f"{response.status_code} {response.reason}".strip()


def _decode_json_columns(row, keys):
    """provider_profile / scraper JSON columns come back from
    mysql-connector as plain strings, not auto-decoded dicts/lists —
    this decodes the given keys of row in place where present."""
    for key in keys:
        value = row.get(key)
        if isinstance(value, str):
            try:
                row[key] = json.loads(value)
            except (ValueError, TypeError):
                pass
    return row


# To be documented — see TBD_and_Conflicts.md
def _parse_curl(raw_cmd):
    """
    Parses a scraper's stored curl.exe command back into (url,
    headers, body) so execute() can actually dispatch it via
    send_request(). This is the reverse of buildCurl (M-005) — no
    M-numbered method documents this direction, even though execute()
    (M-009) can't run without it.
    """
    tokens = shlex.split((raw_cmd or "").replace("curl.exe", "curl"))
    if not tokens:
        return "", {}, None
    url = tokens[-1]
    headers = {}
    body = None
    t = 1
    while t < len(tokens) - 1:
        if tokens[t] in ("-H", "--header"):
            k, v = tokens[t + 1].split(":", 1)
            headers[k.strip()] = v.strip()
            t += 2
        elif tokens[t] in ("-d", "--data", "--data-raw"):
            body = tokens[t + 1]
            t += 2
        else:
            t += 1
    return url, headers, body


def _write_last_request_date(cursor, scraper_id):
    """Updates scraper.last_request_date as part of the caller's
    transaction — the second half of the atomic group M-032 requires
    of a fetch run.

    C3 note: this replaces an earlier best-effort helper that opened
    its own write and swallowed db.DatabaseError, on the reasoning
    that a successful fetch shouldn't be reported as failed just
    because the timestamp touch-up failed afterwards. That reasoning
    is a UX preference, and M-032 states the opposite outright —
    execute's "inserted listings and updated last-run timestamp
    either both persist or neither does". Swallowing the failure
    while keeping the listings is exactly the partial write M-032
    forbids, so the swallow is gone and this write now rolls the
    listings back with it. See TBD_and_Conflicts.md.

    Writes a real datetime, not a display string — see C1.
    """
    if not scraper_id:
        return
    cursor.execute(
        "UPDATE scraper SET last_request_date = %s WHERE id = %s",
        (datetime.now(timezone.utc), scraper_id),
    )


# ---------------------------------------------------------------------
# M-002 / M-005 / M-006 — provider profiles and scraper creation
# ---------------------------------------------------------------------

def get_profile(profile_id):
    """
    M-002 — getProfile(profile_id: str) -> dict

    Retrieves a single provider profile from the provider_profile
    table by its profile_name.

    Parameters:
        profile_id: str — profile_name key of the profile to fetch.

    Returns:
        dict — the matching provider profile (UT-1-02-001); None when
        no profile matches (UT-1-02-002).

    Throws:
        -
    """
    rows = db.query(
        "SELECT id, profile_name, url, query_params, headers, body_template, "
        "fields, field_map FROM provider_profile WHERE profile_name = %s",
        (profile_id,),
    )
    if not rows:
        return None
    return _decode_json_columns(
        rows[0], ("query_params", "headers", "body_template", "fields", "field_map")
    )


def build_curl(profile, credentials, parameters):
    """
    M-005 — buildCurl(profile: dict, credentials: dict, parameters: dict) -> str

    Reconstructs an executable curl command from the profile's saved
    request schema, substituting the administrator-supplied credential
    and parameter values into the request template.

    Parameters:
        profile: dict — Provider profile schema (url, query_params,
            headers, body_template, fields).
        credentials: dict — Secret values per credential header.
        parameters: dict — Parameter values per field.

    Returns:
        str — a curl.exe command string compatible with _parse_curl /
        send_request (UT-1-05-001/002).

    Throws:
        -
    """
    query_str = urlencode(profile.get("query_params") or {})
    full_url = profile["url"] + (f"?{query_str}" if query_str else "")

    header_parts = []
    for h in profile.get("headers") or []:
        if h.get("is_credential"):
            secret = (credentials or {}).get(h["key"], "")
            prefix = h.get("cred_prefix", "")
            val = f"{prefix}{secret}" if secret else ""
        else:
            val = h.get("fixed_value", "")
        header_parts.append(f'-H "{h["key"]}: {val}"')

    body_template = profile.get("body_template")
    field_values = {f["name"]: (parameters or {}).get(f["name"], "") for f in profile.get("fields") or []}

    def _match_template_type(submitted, template_value):
        """Keeps a submitted value in whatever JSON type the profile's
        body_template uses for that key.

        Every parameter arrives from the create form as a string, but a
        template value of 20 (Indeed's "pay") means the provider expects
        a JSON number — sending "200" instead of 200 is a type error the
        API rejects. Only numeric template values are coerced, and only
        when the submitted text actually parses as a number; anything
        else (including a blank optional field) is left as the string it
        came in as, so this can't turn a valid value into null.
        """
        if isinstance(template_value, bool) or not isinstance(template_value, (int, float)):
            return submitted
        if not isinstance(submitted, str):
            return submitted
        text = submitted.strip()
        if not text:
            return submitted
        try:
            return int(text) if isinstance(template_value, int) else float(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return submitted

    def _substitute(node):
        if isinstance(node, dict):
            return {
                k: (_match_template_type(field_values[k], node[k]) if k in field_values
                    else _substitute(node[k]))
                for k in node
            }
        if isinstance(node, list):
            return [_substitute(item) for item in node]
        return node

    body_obj = _substitute(body_template) if body_template is not None else {}
    body_json = json.dumps(body_obj, ensure_ascii=False)
    body_escaped = body_json.replace('"', '\\"')

    header_str = " ".join(header_parts)
    return f'curl.exe {header_str} -d "{body_escaped}" "{full_url}"'


def save_scraper(scraper):
    """
    M-006 — saveScraper(scraper: dict) -> dict

    Persists the new scraper to the scraper table and, when the source
    profile has a saved field_map, auto-applies it so the scraper
    appears in the Scrapers tab ready to run. Records the creation in
    the activity log (SRS-004) — this method calls log_service itself
    (its "Maps to" line explicitly includes "+ _append_log('add',...)",
    unlike M-009/M-026 whose mappings don't, which is the signal this
    file uses throughout for deciding who logs what).

    Parameters:
        scraper: dict — The assembled scraper record (website_name,
            description, request, source_profile, optional field_map).

    Returns:
        dict — the persisted scraper record (UT-1-06-001 with an
        inherited field_map, UT-1-06-002 without one).

    Throws:
        db.DatabaseError — "Unable to write to the scraper table."
        when the write fails (UT-1-06-003).
    """
    scraper = dict(scraper)
    scraper.setdefault("id", str(uuid.uuid4()))
    scraper.setdefault("last_request_date", "-")

    source_profile_name = scraper.get("source_profile")
    profile = get_profile(source_profile_name) if source_profile_name else None

    applied_field_map = False
    if not scraper.get("field_map") and profile and profile.get("field_map"):
        scraper["field_map"] = profile["field_map"]
        applied_field_map = True

    try:
        db.execute(
            """
            INSERT INTO scraper
                (id, source_profile_id, website_name, description, request,
                 field_map, last_request_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                scraper["id"],
                profile.get("id") if profile else None,
                scraper.get("website_name"),
                scraper.get("description") or "",
                scraper.get("request"),
                json.dumps(scraper["field_map"]) if scraper.get("field_map") else None,
                # C1: last_request_date is a Timestamp column — a brand-new
                # scraper has never run, which is NULL in the table. The "-"
                # the test cases expect stays in the returned dict below and
                # is regenerated on every later read by
                # format_display_datetime().
                coerce_datetime(scraper["last_request_date"]),
            ),
        )
    except db.DatabaseError as ex:
        raise db.DatabaseError("Unable to write to the scraper table.") from ex

    if source_profile_name:
        detail = (
            f"Created from profile '{source_profile_name}' (field mapping auto-applied)"
            if applied_field_map else
            f"Created from profile '{source_profile_name}'"
        )
    else:
        detail = ""
    log_service.append_log("add", scraper.get("website_name"), detail)

    return scraper


# ---------------------------------------------------------------------
# M-024 / M-010 / M-025 / M-009 — the fetch pipeline
# ---------------------------------------------------------------------

def send_request(url, headers, body):
    """
    M-024 — sendRequest(url: str, headers: dict, body: str | None) -> Response

    Dispatches the built HTTP request to the external job API provider
    and returns the raw response for parsing. Method is inferred the
    same way _parse_curl's caller built the command: POST when a body
    is present, GET otherwise — the signature itself carries no
    explicit method argument.

    Parameters:
        url: str — Provider endpoint the request is sent to.
        headers: dict — Request headers, including the credential /
            Authorization header.
        body: str | None — Request body for POST-style calls; None
            for GET.

    Returns:
        Response — the raw HTTP response (UT-1-24-001).

    Throws:
        APIError — Provider returned a non-2xx status (UT-1-24-002).
    """
    method = "POST" if body else "GET"
    response = requests.request(method, url, headers=headers, data=body, timeout=300)
    if not response.ok:
        raise APIError(_extract_error_message(response))
    return response


def poll_snapshot(snapshot_id, auth_header):
    """
    M-010 — pollSnapshot(snapshot_id: str, auth_header: str) -> list | dict | None

    Polls the provider's asynchronous snapshot endpoint every 60
    seconds for up to 10 attempts until the dataset is ready. Unlike
    the original _poll_snapshot, this takes no UI status-placeholder
    parameter — matching M-010's 2-argument signature exactly; showing
    a "still running" message is the caller's concern (whichever of
    scraper_controller.py / admin.py renders progress), not this
    function's.

    Parameters:
        snapshot_id: str — Provider snapshot identifier.
        auth_header: str — Authorization header value reused for the
            poll requests.

    Returns:
        list | dict — the ready snapshot data (UT-1-10-001 ready on
        attempt 1, UT-1-10-002 ready on attempt 10); None when the
        snapshot never leaves "running" within 10 attempts
        (UT-1-10-003).

    Throws:
        requests.HTTPError — a poll request itself returns an error
        status (UT-1-10-004).
    """
    snapshot_url = f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}?format=json"
    poll_headers = {"Authorization": auth_header, "Content-Type": "application/json"}
    for attempt in range(POLL_MAX_ATTEMPTS):
        # Sleep *between* attempts rather than before the first one: a
        # synchronous /scrape snapshot is often ready straight away, and
        # sleeping first made every run wait a full minute for nothing.
        # Still 10 attempts at 60-second intervals as M-010 documents,
        # and UT-1-10-001/002/003 are unaffected — they specify which
        # attempt succeeds, not where the delay sits.
        if attempt:
            time.sleep(POLL_INTERVAL_SECONDS)
        response = requests.get(snapshot_url, headers=poll_headers, timeout=30)
        response.raise_for_status()
        data = _safe_parse_resp(response.text)
        if not (isinstance(data, dict) and data.get("status") in ("running", "closing", "pending", "building", "collecting")):
            return data
    return None


def apply_field_map(raw_job, field_map):
    """
    M-025 — applyFieldMap(rawJob: dict, fieldMap: dict) -> dict

    Standardizes one raw provider record into the canonical job schema,
    copying each mapped source field and storing unmapped/optional
    fields as null.

    Parameters:
        rawJob: dict — A single raw record returned by the provider.
        fieldMap: dict — Mapping of canonical job field to the
            provider's field key.

    Returns:
        dict — the standardized job record (UT-1-25-001 all keys
        mapped, UT-1-25-002 an unmapped optional field).

    Throws:
        -
    """
    field_map = field_map or {}
    return {
        field: (raw_job.get(field_map[field]) if field_map.get(field) else None)
        for field in _JOB_FIELDS
    }


def execute(scraper):
    """
    M-009 — execute(scraper: dict) -> tuple(added: int, skipped: int, error: str | None)

    Runs a scraper end-to-end: parses its stored request, calls the
    external provider, resolves asynchronous snapshots by polling,
    filters provider-flagged error rows, standardizes each remaining
    record via apply_field_map, skips URLs already stored, saves the
    new listings through job_service, and updates the scraper's
    last-run timestamp.

    Those last two writes are one atomic group, per M-032: "a fetch
    run's inserted listings and updated last-run timestamp either both
    persist or neither does" (C3). job_service.save_listings joins
    this method's db.transaction() rather than committing separately.

    Deliberately does NOT call log_service.append_log itself, despite
    this method's own prose ("...and logs the outcome") suggesting
    otherwise — see TBD_and_Conflicts.md. The short version: this
    function has no way to know whether it was invoked manually
    (action "run") or by the schedule loop (action "auto_run"), since
    its signature carries only `scraper`; the original _run_scraper it
    maps to doesn't log either, and its actual callers each log with
    their own action label after execute() returns.

    Parameters:
        scraper: dict — The scraper record to execute (request,
            field_map, id).

    Returns:
        tuple(added, skipped, error) — (5, 0, None) for a clean run
        (UT-1-09-001); (3, 2, None) with 2 duplicate URLs
        (UT-1-09-002); (4, 0, None) with 1 provider error row filtered
        (UT-1-09-003); (0, 0, "401 Unauthorized") on rejection
        (UT-1-09-004); (0, 0, "Snapshot timed out") on timeout
        (UT-1-09-005).

    Throws:
        -  (APIError / snapshot timeout are caught internally and
        returned as the tuple's error field, per this method's own
        Throws clause — never raised out of execute(). A rolled-back
        storage failure is returned the same way, as (0, 0, message):
        M-009 documents no DatabaseError, and swallowing it would
        break the M-014 auto-run loop for every other scraper.)
    """
    field_map = scraper.get("field_map") or {}
    raw_cmd = (scraper.get("request") or "").strip()

    try:
        url, headers, body = _parse_curl(raw_cmd)
        response = send_request(url, headers, body)
        data = _safe_parse_resp(response.text)

        # A provider that answers asynchronously returns a snapshot
        # reference instead of the jobs themselves. BrightData's /scrape
        # endpoint returns bare {"snapshot_id": "sd_..."} with no status
        # field at all, so keying off status (running/closing/pending)
        # silently skipped the poll: _normalise_response then found no
        # job array in that dict and the run reported success with zero
        # jobs while the data sat in the snapshot. The test that
        # produced "status" alongside the id (UT-1-10) is one shape of
        # the same thing, not the only one — so the rule is now simply:
        # a dict carrying a snapshot_id and no embedded job list needs
        # fetching.
        if isinstance(data, dict) and data.get("snapshot_id") and not _normalise_response(data):
            data = poll_snapshot(data["snapshot_id"], headers.get("Authorization", ""))
            if data is None:
                return 0, 0, "Snapshot timed out"

        raw_jobs = _normalise_response(data)
        raw_jobs = [j for j in raw_jobs if "error_code" not in j and "error" not in j]
        new_jobs = [apply_field_map(j, field_map) for j in raw_jobs]

        existing = job_service.load_listings()
        existing_urls = {j.get("url") for j in existing if j.get("url")}
        to_save = list(existing)
        added = skipped = 0
        for job in new_jobs:
            job_url = job.get("url")
            if job_url and job_url in existing_urls:
                skipped += 1
            else:
                job["scraper_id"] = scraper.get("id")
                to_save.append(job)
                if job_url:
                    existing_urls.add(job_url)
                added += 1

        # C3 — M-032 requires these two writes to be one atomic group:
        # "a fetch run's inserted listings and updated last-run
        # timestamp either both persist or neither does". They used to
        # be two independent commits (save_listings opened its own,
        # then a separate best-effort UPDATE), which could leave jobs
        # saved with a stale last-run date. save_listings now joins
        # this transaction via its conn parameter.
        with db.transaction() as conn:
            job_service.save_listings(to_save, conn=conn)
            cursor = conn.cursor()
            try:
                _write_last_request_date(cursor, scraper.get("id"))
            finally:
                cursor.close()
        return added, skipped, None

    except (APIError, requests.exceptions.RequestException) as ex:
        return 0, 0, str(ex)
    except db.DatabaseError as ex:
        # M-009's Throws clause names only APIError and SnapshotTimeout,
        # so a rolled-back storage failure is surfaced through the
        # documented Returns contract instead ("an error string when the
        # run failed") rather than propagating — which also keeps one
        # bad scraper from breaking the whole auto-run loop (M-014).
        # Counts are zero because the rollback means nothing persisted.
        # db.transaction() wraps the original error, so the specific
        # table message is recovered from the cause where present.
        return 0, 0, str(ex.__cause__ or ex)


# ---------------------------------------------------------------------
# M-013 / M-015 — schedules
# ---------------------------------------------------------------------

# To be documented — see TBD_and_Conflicts.md
def list_scrapers():
    """
    Reads every scraper together with its schedule (if any), joined
    from the scraper and schedule tables. Not one of the 32 methods —
    no M-XXX covers this read, but both getDueScrapers() below and
    scraper_controller.getScrapers() (M-007, next file) need the same
    underlying data, so it lives here once rather than being
    duplicated or querying db.py straight from the controller.
    """
    rows = db.query(
        """
        SELECT s.id, s.source_profile_id, s.website_name, s.description,
               s.request, s.field_map, s.last_request_date,
               sc.mode AS sched_mode, sc.run_at AS sched_run_at,
               sc.interval_type AS sched_interval, sc.enabled AS sched_enabled,
               sc.last_auto_run AS sched_last_auto_run
        FROM scraper s
        LEFT JOIN schedule sc ON sc.scraper_id = s.id
        """
    )
    scrapers = []
    for row in rows:
        _decode_json_columns(row, ("field_map",))
        scraper = {
            "id": row.get("id"),
            "source_profile_id": row.get("source_profile_id"),
            "website_name": row.get("website_name"),
            "description": row.get("description"),
            "request": row.get("request"),
            "field_map": row.get("field_map"),
            # C1: the three Timestamp columns come back from db.query() as
            # native datetimes; they're rendered here, at the read boundary,
            # into the exact shapes the test cases expect — the "last run"
            # display string for last_request_date (UT-1-07-001), ISO-Z for
            # the schedule times (UT-1-15-001).
            "last_request_date": format_display_datetime(row.get("last_request_date")),
        }
        if row.get("sched_mode"):
            scraper["schedule"] = {
                "mode": row.get("sched_mode"),
                "run_at": format_iso_z(row.get("sched_run_at")),
                "interval": row.get("sched_interval"),
                "enabled": bool(row.get("sched_enabled")),
                "last_auto_run": format_iso_z(row.get("sched_last_auto_run")),
            }
        scrapers.append(scraper)
    return scrapers


def _is_due(scraper):
    """Port of the original _is_due: is this scraper's enabled
    schedule currently due? Folded in here rather than exposed
    separately, since M-015's own description is exactly this check
    applied across every scraper ("Maps to _is_due")."""
    schedule = scraper.get("schedule")
    if not schedule or not schedule.get("enabled"):
        return False

    mode = schedule.get("mode")
    now = datetime.now(timezone.utc)

    if mode == "fixed":
        run_at = coerce_datetime(schedule.get("run_at"))
        if run_at is None:
            return False
        last_auto_run = coerce_datetime(schedule.get("last_auto_run"))
        if last_auto_run and last_auto_run >= run_at:
            return False
        return now >= run_at

    if mode == "recurring":
        interval_days = {"weekly": 7, "biweekly": 14, "monthly": 30}.get(schedule.get("interval"))
        if interval_days is None:
            return False
        last_run = coerce_datetime(scraper.get("last_request_date"))
        if last_run is None:
            return True
        return now >= last_run + timedelta(days=interval_days)

    return False


# To be documented — see TBD_and_Conflicts.md
def find_scraper(scraper_id):
    """
    Resolves a scraper identifier to its stored record, matching on
    the real `id` first and falling back to `website_name`.

    The single resolution point for the identifier ambiguity logged in
    TBD_and_Conflicts.md: UT-1-08, UT-1-12, and UT-1-13 all pass a
    website name (e.g. "LinkedIn Jobs -- Remote") as "scraper_id",
    while the Data Dictionary requires `Schedule.scraper_id` to be a
    Scraper UUID. Every caller that needs to turn one of those inputs
    into a real row goes through here — persist_schedule (M-013) below,
    scraper_controller._find_scraper, and scraper_ui — rather than each
    keeping its own copy of the same lookup.

    Parameters:
        scraper_id: str — a Scraper.id, or a website_name.

    Returns:
        dict — the matching scraper record from list_scrapers(); None
        when nothing matches.

    Throws:
        -
    """
    for scraper in list_scrapers():
        if str(scraper.get("id")) == str(scraper_id) or scraper.get("website_name") == scraper_id:
            return scraper
    return None


# To be documented — see TBD_and_Conflicts.md
def update_scraper(scraper_id, fields):
    """
    Updates an existing scraper's editable fields (website_name,
    description, request) and records an "edit" activity-log entry.

    Not one of the 32 methods: no M-XXX covers editing a scraper after
    creation, though the original admin.py had the feature and
    URS-001 calls for the administrator to be able to "update" a
    scraper. Restored on request; the ⚙️ Configure field-mapping panel
    it used to sit beside stays out of scope.

    The field_map is deliberately not editable here — it is set once,
    automatically, by save_scraper (M-006) inheriting it from the
    source profile, and changing it is the Configure feature that
    remains out of scope.

    Parameters:
        scraper_id: str — Identifier (id or website_name) of the
            scraper to update; resolved via find_scraper().
        fields: dict — Any of website_name, description, request. Keys
            that are absent are left unchanged.

    Returns:
        dict — the updated scraper record; None when scraper_id
        matches nothing (the not-found-returns-None convention used by
        getProfile / M-002).

    Throws:
        db.DatabaseError — "Unable to write to the scraper table."
        when the write fails, matching the message M-006 and M-013 use
        for the same table.
    """
    scraper = find_scraper(scraper_id)
    if scraper is None:
        return None

    updated = {
        "website_name": fields.get("website_name", scraper.get("website_name")),
        "description": fields.get("description", scraper.get("description")),
        "request": fields.get("request", scraper.get("request")),
    }
    for key in ("website_name", "description", "request"):
        if isinstance(updated[key], str):
            updated[key] = updated[key].strip()

    try:
        db.execute(
            "UPDATE scraper SET website_name = %s, description = %s, request = %s WHERE id = %s",
            (updated["website_name"], updated["description"] or "", updated["request"], scraper.get("id")),
        )
    except db.DatabaseError as ex:
        raise db.DatabaseError("Unable to write to the scraper table.") from ex

    renamed = updated["website_name"] != scraper.get("website_name")
    detail = (
        f"Renamed from '{scraper.get('website_name')}'" if renamed
        else "Details updated"
    )
    log_service.append_log("edit", updated["website_name"], detail)

    result = dict(scraper)
    result.update(updated)
    return result


def get_due_scrapers():
    """
    M-015 — getDueScrapers() -> list

    Returns the scrapers whose enabled schedule is currently due —
    a fixed run_at that's been reached, or a recurring interval
    elapsed since the last run.

    Parameters:
        -

    Returns:
        list[dict] — due scrapers, each with its schedule attached
        (UT-1-15-001 fixed, UT-1-15-002 recurring); [] when nothing is
        due or every schedule is disabled (UT-1-15-003).

    Throws:
        -
    """
    return [s for s in list_scrapers() if _is_due(s)]


def persist_schedule(scraper_id, schedule):
    """
    M-013 — persistSchedule(scraper_id: str, schedule: dict) -> dict

    Writes the schedule object into the schedule table (upserted by
    scraper_id) and appends a "schedule" activity-log entry (SRS-020).

    Parameters:
        scraper_id: str — Target scraper. Accepts either a real
            Scraper.id or a website_name (UT-1-13-001 passes the
            latter); resolved to the real row via find_scraper()
            before anything is written, so the schedule row's
            scraper_id is always the UUID foreign key the Data
            Dictionary requires (C2 fix).

        schedule: dict — {mode, run_at | interval, enabled}.

    Returns:
        dict — the updated scraper record with its schedule attached
        (UT-1-13-001: website_name, request, field_map,
        last_request_date, and the schedule object).

    Throws:
        db.DatabaseError — "Unable to write to the scraper table."
        when the write fails (UT-1-13-002). The message says "scraper"
        rather than "schedule" — carried over unchanged from the test
        case even though the actual write here targets the new,
        separate schedule table; see TBD_and_Conflicts.md.

        The same error is raised when scraper_id matches no stored
        scraper. That is exactly what a real schema does — the write
        would violate schedule.scraper_id's foreign key, MySQL would
        reject it, and db.execute would surface it as a DatabaseError
        that this method re-raises with that message. Failing here is
        deliberate: the previous behaviour silently wrote an orphan
        row keyed by whatever string it was handed.
    """
    schedule = schedule or {}

    scraper = find_scraper(scraper_id)
    if scraper is None:
        raise db.DatabaseError("Unable to write to the scraper table.")
    resolved_id = scraper.get("id")

    try:
        db.execute(
            """
            INSERT INTO schedule (id, scraper_id, mode, run_at, interval_type, enabled, last_auto_run)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                mode = VALUES(mode), run_at = VALUES(run_at),
                interval_type = VALUES(interval_type), enabled = VALUES(enabled),
                last_auto_run = VALUES(last_auto_run)
            """,
            (
                str(uuid.uuid4()),
                resolved_id,
                schedule.get("mode"),
                # C1: run_at / last_auto_run are Timestamp columns. The UI
                # hands them over as ISO-Z strings ("2026-07-01T08:00:00Z"),
                # whose trailing "Z" MySQL will not accept in a DATETIME —
                # coerced to real datetimes here, and rendered back to ISO-Z
                # in schedule_out below.
                coerce_datetime(schedule.get("run_at")),
                schedule.get("interval"),
                bool(schedule.get("enabled", True)),
                coerce_datetime(schedule.get("last_auto_run")),
            ),
        )
    except db.DatabaseError as ex:
        raise db.DatabaseError("Unable to write to the scraper table.") from ex

    # Read back by the resolved id, not the caller's string: given
    # UT-1-13-001's own input ("LinkedIn Jobs -- Remote") this lookup
    # previously matched nothing, and the returned record came back
    # missing request, field_map, and last_request_date (C2 fix).
    rows = db.query(
        "SELECT id, website_name, request, field_map, last_request_date "
        "FROM scraper WHERE id = %s",
        (resolved_id,),
    )
    scraper_row = _decode_json_columns(dict(rows[0]), ("field_map",)) if rows else dict(scraper)

    # Mode-aware on purpose, not a blanket "drop empty values" filter:
    # UT-1-12-001 (recurring) expects no run_at/last_auto_run keys at
    # all, while UT-1-12-002 (fixed) expects last_auto_run present and
    # explicitly null. last_auto_run is only meaningful for fixed mode
    # anyway — _is_due() above only ever reads it in the fixed branch.
    schedule_out = {"mode": schedule.get("mode"), "enabled": bool(schedule.get("enabled", True))}
    if schedule.get("mode") == "fixed":
        schedule_out["run_at"] = format_iso_z(schedule.get("run_at"))
        schedule_out["last_auto_run"] = format_iso_z(schedule.get("last_auto_run"))
    elif schedule.get("mode") == "recurring":
        schedule_out["interval"] = schedule.get("interval")

    result = dict(scraper_row)
    # C1: the read-back carries last_request_date as a native datetime;
    # UT-1-13-001 expects it as the "2026-06-09 20:12 UTC" display string.
    if "last_request_date" in result:
        result["last_request_date"] = format_display_datetime(result["last_request_date"])
    result["schedule"] = schedule_out

    # SRS-020 requires the log entry itself to record the schedule type,
    # its run time/interval, and enabled status — not just that a
    # schedule was saved.
    enabled = schedule_out.get("enabled", True)
    if schedule_out.get("mode") == "fixed":
        detail = f"fixed schedule for {schedule_out.get('run_at')}, enabled={enabled}"
    else:
        detail = f"recurring schedule ({schedule_out.get('interval')}), enabled={enabled}"

    log_service.append_log("schedule", scraper_row.get("website_name") or str(scraper_id), detail)
    return result


# To be documented — see TBD_and_Conflicts.md
def list_profile_names():
    """
    Lists every saved provider profile's name, for populating the
    profile picker in the Create tab. No M-numbered method covers
    this — M-002/getProfile only ever fetches one named profile, and
    nothing in the 32 methods lists all of them, even though a picker
    can't render with zero options. Profile creation/deletion/
    configuration themselves are out of scope entirely — see
    TBD_and_Conflicts.md.
    """
    rows = db.query("SELECT profile_name FROM provider_profile ORDER BY profile_name")
    return [row["profile_name"] for row in rows]


# To be documented — see TBD_and_Conflicts.md
def delete_scraper(scraper_id):
    """
    Permanently removes a scraper (and its schedule row, if any) from
    storage. No M-numbered method covers scraper deletion at all —
    unlike job listings, which have deleteListing (M-022), there is no
    equivalent for scrapers anywhere in the Method Description, even
    though the original admin.py has this feature and a Scrapers tab
    with no way to remove a scraper would be a real functional gap.

    Parameters:
        scraper_id: str — Identifier of the scraper to delete.

    Returns:
        bool — True when a scraper row was deleted; False when
        scraper_id matched nothing.

    Throws:
        db.DatabaseError — "Unable to write to the scraper table."
        when the delete fails.
    """
    try:
        db.execute("DELETE FROM schedule WHERE scraper_id = %s", (scraper_id,))
        rowcount = db.execute("DELETE FROM scraper WHERE id = %s", (scraper_id,))
    except db.DatabaseError as ex:
        raise db.DatabaseError("Unable to write to the scraper table.") from ex
    return rowcount > 0