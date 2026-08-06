"""
scraper_controller.py — Request-Handling Entry Points for Scrapers

Implements M-001 (loadProfileForm), M-003 (createScraper), M-007
(getScrapers), M-008 (runScraper), M-011 (previewNextRun), M-012
(saveSchedule), and M-014 (checkDueSchedules) for UC-F1-001 (Create
Scraper), UC-F1-002 (Fetch Jobs), and UC-F1-003 (Schedule Job
Fetching).

Like job_controller.py, these are plain Python functions with no
Streamlit calls of their own — the diagrams' "UI / Frontend" lifeline
(forms, buttons, session state, the disabled-Run-button precondition in
UT-1-08-003, progress messages during polling) is admin.py's job once
it's built, not this file's.

This is also where the M-009 execute()-logging question from
scraper_service.py gets resolved in practice: run_scraper and
check_due_schedules are the two callers that actually call
log_service.append_log after execute() returns, using "run" and
"auto_run" respectively — the split scraper_service.py's docstring
said its callers would handle.
"""

from datetime import timedelta

import log_service
import scraper_service
import validation_service

_INTERVAL_DAYS = {"weekly": 7, "biweekly": 14, "monthly": 30}

# Re-exported so the UI layer can catch a failed run without importing
# scraper_service (C4). Not a new method — the same exception object,
# reachable from the layer admin.py is supposed to talk to.
APIError = scraper_service.APIError


class SnapshotTimeout(Exception):
    """
    Raised by run_scraper() when execute() reports a timed-out
    snapshot poll ("Snapshot timed out"), matching M-008's Throws
    clause. scraper_service.execute() itself never raises this — it
    returns the timeout as a plain string in its result tuple; this is
    where that string becomes an actual exception for the manual-run
    caller.
    """


# To be documented — see TBD_and_Conflicts.md
def find_scraper(scraper_id):
    """Delegates to scraper_service.find_scraper(), the single
    resolution point for the id-or-website_name ambiguity that UT-1-08,
    UT-1-12, and UT-1-13 all rely on (C2). Public rather than private
    so scraper_ui.py can resolve a scraper through its controller
    instead of importing scraper_service directly (C4)."""
    return scraper_service.find_scraper(scraper_id)


# To be documented — see TBD_and_Conflicts.md
def get_profiles():
    """
    Lists the saved provider profiles available in the Create tab's
    picker. Not one of the 32 methods — M-001 loads a *single* chosen
    profile, and nothing documented lists them, though a picker can't
    render without the list.

    Exists as a controller entry point rather than the UI calling
    scraper_service.list_profile_names() directly (C4), matching File
    Structure's description of this file: "Receives UI actions and
    orchestrates calls into scraper_service.py."

    Returns:
        list[str] — profile names, alphabetically; [] when none exist.

    Throws:
        -
    """
    return scraper_service.list_profile_names()


def load_profile_form(profile_id):
    """
    M-001 — loadProfileForm(profile_id: str) -> dict

    Loads the provider profile the administrator selects in the
    Create tab and returns the data needed to render the
    create-scraper form (credential headers and parameter fields).
    Maps straight to scraper_service.get_profile() (M-002) — the same
    lookup, just named for this specific calling context.

    Parameters:
        profile_id: str — The profile_name of the saved provider
            profile chosen from the picker.

    Returns:
        dict — the provider profile record used to render the form
        (UT-1-01-001; UT-1-01-002 with an empty field_map); None when
        profile_id doesn't match a saved profile (UT-1-01-003).

    Throws:
        -  (ProfileNotFound is documented as "guarded": the picker
        only ever lists profiles that exist, so a lookup miss just
        returns None rather than raising.)
    """
    return scraper_service.get_profile(profile_id)


def create_scraper(profile_id, website_name, description, credentials, parameters):
    """
    M-003 — createScraper(profile_id, website_name, description, credentials, parameters) -> dict

    Orchestrates creation of a new scraper instance from a saved
    profile: validates required inputs, builds the executable request,
    and persists it. save_scraper (M-006) handles both the
    field-map inheritance and the "add" log entry itself — see that
    function's docstring for why this one doesn't log again.

    This is where the assumption noted in
    TBD_and_Conflicts.md/validation_service.py actually gets
    implemented: validateRequiredFields has no field-metadata of its
    own, so this function reads the profile's own field definitions to
    build the required-only subset it expects, before calling it.

    Parameters:
        profile_id: str — Source profile name the scraper is created
            from.
        website_name: str — Display name of this scraper instance.
            Required.
        description: str — Optional free-text note.
        credentials: dict — Secret value for each credential header
            defined by the profile.
        parameters: dict — One value per profile parameter; required
            parameters must be non-empty.

    Returns:
        dict — the newly created scraper record (UT-1-03-001;
        UT-1-03-002 with description left blank).

    Throws:
        validation_service.MissingFieldException — website_name or any
        required parameter is empty; nothing is built or persisted.
    """
    profile = scraper_service.get_profile(profile_id) or {}
    required_params = {
        field["name"]: (parameters or {}).get(field["name"], "")
        for field in profile.get("fields") or []
        if field.get("required")
    }
    validation_service.validate_required_fields(website_name, required_params)

    curl_cmd = scraper_service.build_curl(profile, credentials, parameters)
    scraper = {
        "website_name": (website_name or "").strip(),
        "description": (description or "").strip(),
        "request": curl_cmd,
        "source_profile": profile_id,
    }
    return scraper_service.save_scraper(scraper)


def get_scrapers():
    """
    M-007 — getScrapers() -> list

    Loads and returns all configured scrapers for the Scrapers tab,
    each with name, description, last-run date, schedule, and
    field-map status. Maps straight to scraper_service.list_scrapers()
    — the "shown with ... action buttons" part of the description is
    the UI layer's job once it has this list, same division as
    job_controller.get_listings().

    Parameters:
        -

    Returns:
        list[dict] — the scraper records (UT-1-07-001); [] when none
        exist (UT-1-07-002).

    Throws:
        -
    """
    return scraper_service.list_scrapers()


def run_scraper(scraper_id):
    """
    M-008 — runScraper(scraper_id: str) -> dict

    Handles a manual run request from the Run button: invokes execute
    (M-009) on the selected scraper, then reports the added/skipped
    counts or logs the run error and raises it so the UI can surface
    it. Greying out the button / disabling other controls (also
    mentioned in this method's description) is the UI layer's concern,
    not this function's.

    Parameters:
        scraper_id: str — Identifier (id, or website_name — see
            find_scraper) of the configured scraper to run.

    Returns:
        dict — {added, skipped} on success (UT-1-08-001); None when
        scraper_id doesn't match any configured scraper (not covered
        by a test case; mirrors the not-found-returns-None convention
        used elsewhere — getProfile/M-002, job_controller.mark_outdated).

        UT-1-08-003 ("Not invoked — Run action disabled" when a
        scraper has no field_map) is a UI-level precondition — the Run
        button itself is disabled — not something checked here;
        calling this directly on a scraper with no field_map just runs
        execute() with an empty field_map, mapping nothing.

    Throws:
        scraper_service.APIError — the provider rejected the request
            (UT-1-08-002); the error is logged before being raised.
        SnapshotTimeout — the snapshot never finished; also logged
            before being raised.
    """
    scraper = find_scraper(scraper_id)
    if scraper is None:
        return None

    display_name = scraper.get("website_name") or str(scraper_id)
    added, skipped, error = scraper_service.execute(scraper)

    if error:
        log_service.append_log("run", display_name, error)
        if error == "Snapshot timed out":
            raise SnapshotTimeout(error)
        raise scraper_service.APIError(error)

    log_service.append_log("run", display_name, f"{added} new jobs saved, {skipped} duplicates skipped")
    return {"added": added, "skipped": skipped}


def preview_next_run(schedule_type, values):
    """
    M-011 — previewNextRun(schedule_type: str, values: dict) -> str

    Computes the next estimated run time for a recurring schedule
    (last run + interval) or the chosen date/time for a fixed
    schedule, for preview before the administrator saves. Uses
    scraper_service.coerce_datetime() — the same date parsing
    getDueScrapers relies on — rather than a second, locally
    duplicated copy.

    Parameters:
        schedule_type: str — "fixed" or "recurring".
        values: dict — run_at (fixed) or interval + last_request_date
            (recurring).

    Returns:
        str — "Next run estimate: <date> UTC" for recurring
        (UT-1-11-001); the chosen date/time alone, with no prefix, for
        fixed (UT-1-11-002); "No last request date recorded — will run
        on next page load." when a recurring schedule has no prior run
        to compute from (UT-1-11-003); "" for an unrecognized
        schedule_type or interval (not covered by a test case, but
        kept distinct from the "no prior run" message rather than
        reusing it for an unrelated failure mode).

    Throws:
        -
    """
    values = values or {}

    if schedule_type == "fixed":
        run_at = scraper_service.coerce_datetime(values.get("run_at"))
        return run_at.strftime("%Y-%m-%d %H:%M UTC") if run_at else ""

    if schedule_type == "recurring":
        last_request_date = values.get("last_request_date")
        last_dt = (
            scraper_service.coerce_datetime(last_request_date)
            if last_request_date not in (None, "-") else None
        )
        if last_dt is None:
            return "No last request date recorded — will run on next page load."
        interval_days = _INTERVAL_DAYS.get(values.get("interval"))
        if interval_days is None:
            return ""
        next_dt = last_dt + timedelta(days=interval_days)
        return f"Next run estimate: {next_dt.strftime('%Y-%m-%d %H:%M UTC')}"

    return ""


def save_schedule(scraper_id, schedule):
    """
    M-012 — saveSchedule(scraper_id: str, schedule: dict) -> dict

    Receives the schedule form submission and forwards it to
    persistSchedule (M-013, which persists it and logs the "schedule"
    entry itself), then returns just the saved schedule object — not
    the whole scraper record persistSchedule itself returns. Closing
    the panel and refreshing the schedule badge (also mentioned in
    this method's description) are UI-layer concerns once this
    returns.

    Parameters:
        scraper_id: str — Target scraper. Accepts a real Scraper.id or
            a website_name (UT-1-12 passes the latter); persistSchedule
            resolves it to the real row before writing, so the schedule
            row's foreign key is always a UUID (C2 fix — resolution
            lives in the service rather than here, because UT-1-13
            calls persistSchedule directly and needs the same
            protection).
        schedule: dict — {mode, run_at | interval, enabled}.

    Returns:
        dict — the saved schedule object (UT-1-12-001 recurring;
        UT-1-12-002 disabled fixed schedule with last_auto_run: null).

    Throws:
        db.DatabaseError — propagated unchanged from persistSchedule
        when the write fails, or when scraper_id matches no stored
        scraper.
    """
    result = scraper_service.persist_schedule(scraper_id, schedule)
    return result.get("schedule", {})


def check_due_schedules():
    """
    M-014 — checkDueSchedules() -> list

    Runs on every page load (no admin action) to find and
    automatically execute all scrapers whose schedule is currently
    due, logging each auto-run's outcome as "auto_run" — success or
    "FAILED: <error>" — itself. This is the other resolution (besides
    run_scraper above) of the M-009 logging split noted in
    scraper_service.py: execute() doesn't log, so this loop does, with
    its own action label.

    Parameters:
        -

    Returns:
        list[tuple] — (website_name, added, skipped, error) per
        auto-run scraper: a success (UT-1-14-001), no due scrapers at
        all (UT-1-14-002, returns []), or a failed run (UT-1-14-003) —
        the failure is logged and recorded in the result, but does not
        raise; the schedule stays active for future runs.

    Throws:
        -  (an individual scraper's APIError/SnapshotTimeout is caught
        by execute() itself and reported as that scraper's error
        entry; nothing propagates out of this loop.)
    """
    results = []
    for scraper in scraper_service.get_due_scrapers():
        display_name = scraper.get("website_name") or str(scraper.get("id"))
        added, skipped, error = scraper_service.execute(scraper)
        if error:
            log_service.append_log("auto_run", display_name, f"FAILED: {error}")
        else:
            log_service.append_log("auto_run", display_name, f"{added} new jobs, {skipped} skipped")
        results.append((display_name, added, skipped, error))
    return results


# To be documented — see TBD_and_Conflicts.md
def update_scraper(scraper_id, fields):
    """
    Handles an edit-form submission for an existing scraper: validates
    that the website name is present, then persists the change (which
    also writes the "edit" log entry — see
    scraper_service.update_scraper).

    Not one of the 32 methods; restored on request alongside the ✏️
    button on the scraper card. Note the guard is the *documented* one:
    validate_required_fields (M-004) with an empty parameters dict,
    which checks the website name and has nothing else to check, rather
    than a second bespoke validator.

    Parameters:
        scraper_id: str — Identifier (id or website_name) of the
            scraper being edited.
        fields: dict — Any of website_name, description, request.

    Returns:
        dict — the updated scraper record; None when scraper_id
        matches nothing.

    Throws:
        validation_service.MissingFieldException — "Website Name is
            required." when the name is blank; nothing is persisted
            and no log entry is written.
        db.DatabaseError — propagated unchanged when the write fails.
    """
    validation_service.validate_required_fields(fields.get("website_name"), {})
    return scraper_service.update_scraper(scraper_id, fields)


# To be documented — see TBD_and_Conflicts.md
def delete_scraper(scraper_id, confirmed=True):
    """
    Permanently removes a scraper after the administrator confirms the
    deletion dialog, and records a "delete" activity-log entry. Not
    one of the 32 methods — see scraper_service.delete_scraper()'s
    docstring and TBD_and_Conflicts.md for why this exists at all.
    Mirrors job_controller.delete_listing's shape (including the same
    confirmed=True default for the same reason: a single-argument
    deleteX(id) can't distinguish "confirmed" from "cancelled" callers
    on its own).

    Parameters:
        scraper_id: str — Identifier of the scraper to delete.
        confirmed: bool — Whether the administrator has confirmed the
            delete dialog. Defaults to True so a direct call with just
            scraper_id (matching the shape every other entry point in
            this file uses) still deletes.

    Returns:
        bool — True when the scraper was removed; False when
        confirmed=False or scraper_id matched nothing.

    Throws:
        db.DatabaseError — propagated unchanged when the delete fails.
    """
    if not confirmed:
        return False

    scraper = find_scraper(scraper_id)
    if scraper is None:
        return False

    deleted = scraper_service.delete_scraper(scraper.get("id"))
    if deleted:
        log_service.append_log("delete", scraper.get("website_name") or str(scraper_id), "")
    return deleted