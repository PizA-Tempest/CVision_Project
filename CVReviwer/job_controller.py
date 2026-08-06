"""
job_controller.py — Request-Handling Entry Points for Job Listings

Implements M-016 (getListings), M-018 (updateListing), M-021
(markOutdated), and M-022 (deleteListing) for UC-F1-004 (View and
Manage Job Listings).

These four functions are the "job.controller" lifeline in the UC-F1-004
sequence diagram: plain Python functions with no Streamlit calls of
their own (no st.*), matching the Method Description's strictly-typed
Returns/Throws columns (dict / bool / a named exception — never a
rendered widget or notification). The diagram's "UI / Frontend"
lifeline — forms, buttons, session state, success/error messages — is
Streamlit-specific and belongs in admin.py's Data-tab rendering, which
will call into these functions and render the result. Keeping this
file Streamlit-free is also what makes it directly testable against
the UT-1-16/18/21/22 cases, the same way job_service.py and
validation_service.py were.

Orchestrates validation_service.py (the shared guard) and
job_service.py (storage + the 365-day rule); calls log_service.py
directly for the two actions the Method Description doesn't have
job_service already logging internally (job_mark, job_delete) — see
each function's docstring for exactly which layer logs what.
"""

import job_service
import log_service
import validation_service


class OutdatedLockError(Exception):
    """
    Raised by mark_outdated() when trying to unmark a listing that's
    already system-outdated by the 365-day rule (SRS-029) — that flag
    can't be manually reversed, matching the disabled unmark control
    in the Data tab.
    """


def get_listings():
    """
    M-016 — getListings() -> list

    Loads stored job listings for the Data tab. Maps straight to
    job_service.load_listings() (M-017) — the "renders each as a
    card ... Active/Outdated badge, and Edit / Mark Outdated / Delete /
    Details buttons" part of the description is the UI-layer's job
    once it has this list, not something this function does itself
    (the returned rows carry raw values, e.g. salary: None rather than
    "No salary listed" — see UT-1-16-002).

    Parameters:
        -

    Returns:
        list[dict] — job listing records prepared for display,
        annotated with "outdated" (UT-1-16-001/002); [] when the
        table is empty (UT-1-16-003).

    Throws:
        -
    """
    return job_service.load_listings()


def update_listing(listing_id, fields):
    """
    M-018 — updateListing(listing_id: str, fields: dict) -> dict

    Handles an edit-form submission for a job listing: validates the
    required fields, saves the changes, and (via job_service.save_listing,
    M-020) records the "job_edit" log entry. The "shows a success
    notification" part of the description is the UI layer's
    responsibility once this returns successfully, not something
    rendered here.

    Parameters:
        listing_id: str — Identifier of the listing being edited.
        fields: dict — The eight editable job fields (url, job_title,
            company_name, job_location, job_details,
            job_employment_type, job_posted_date, salary).

    Returns:
        dict — the updated listing (UT-1-18-001).

    Throws:
        validation_service.MissingFieldException — Raised when any of
            url, job_title, company_name, job_location, job_details is
            empty (UT-1-18-002); the save is rejected before
            job_service is ever called, so nothing is persisted and
            no log entry is written.
    """
    validation_service.validate_required(
        fields.get("url"),
        fields.get("job_title"),
        fields.get("company_name"),
        fields.get("job_location"),
        fields.get("job_details"),
    )
    return job_service.save_listing(listing_id, fields)


def mark_outdated(listing_id, flag):
    """
    M-021 — markOutdated(listing_id: str, flag: bool) -> dict

    Toggles the manual outdated flag on a listing and records a
    "job_mark" log entry noting the manual change (SRS-030). Unlike
    updateListing, this calls job_service.save_listings (M-026) and
    log_service.append_log (M-023) directly rather than through
    save_listing (M-020) — the UC-F1-004 diagram draws
    markOutdated -> saveListings -> appendLog as three separate steps
    at the job.controller level, not a delegation to saveListing.

    Parameters:
        listing_id: str — Target listing.
        flag: bool — New manual-outdated state (mark / unmark).

    Returns:
        dict — {job_title, company_name, outdated_manual} for the
        updated listing (UT-1-21-001/002); None when listing_id
        doesn't match any stored listing (not covered by a test case;
        mirrors getProfile's not-found-returns-None convention, M-002,
        rather than inventing a new exception for it).

    Throws:
        OutdatedLockError — "Already outdated by system (365+ days) —
            cannot unmark" when flag is False and the listing is
            currently system-outdated (UT-1-21-003); the unmark
            control is disabled in exactly this situation, so nothing
            is persisted and no log entry is written.
    """
    listings = job_service.load_listings()
    target = next((j for j in listings if str(j.get("id")) == str(listing_id)), None)
    if target is None:
        return None

    if not flag and job_service.is_system_outdated(target):
        raise OutdatedLockError(
            "Already outdated by system (365+ days) — cannot unmark"
        )

    target["outdated_manual"] = flag
    job_service.save_listings(listings)

    action_label = "Marked" if flag else "Unmarked"
    log_service.append_log(
        "job_mark",
        target.get("job_title") or str(listing_id),
        f"{action_label} as outdated manually",
    )
    return {
        "job_title": target.get("job_title"),
        "company_name": target.get("company_name"),
        "outdated_manual": target.get("outdated_manual"),
    }


def delete_listing(listing_id, confirmed=True):
    """
    M-022 — deleteListing(listing_id: str) -> bool

    Permanently removes a job listing after the administrator
    confirms the deletion dialog, and records a "job_delete" log entry
    noting which listing was deleted (SRS-031; "by whom" comes from
    log_service's current-user stamp, not a parameter here).

    Parameters:
        listing_id: str — Identifier of the listing to delete.
        confirmed: bool — Whether the administrator has confirmed the
            delete dialog. Not part of M-022's documented signature —
            the diagram only ever shows deleteListing(listing_id)
            called from the confirm path, and never draws a call for
            the cancel path at all (Cancel just closes the dialog
            client-side). Since a single-argument function can't
            literally produce both UT-1-22-001 (confirm -> True) and
            UT-1-22-002 (cancel -> False) from the same listing_id,
            this defaults to True so every diagram-documented call
            site (deleteListing(listing_id)) is unaffected, while
            still giving UT-1-22-002 something concrete to call. See
            TBD_and_Conflicts.md.

    Returns:
        bool — True when the listing was removed (UT-1-22-001); False
        when the administrator cancels (UT-1-22-002, via
        confirmed=False) or listing_id matches nothing.

    Throws:
        -
    """
    if not confirmed:
        return False

    listings = job_service.load_listings()
    target = next((j for j in listings if str(j.get("id")) == str(listing_id)), None)
    if target is None:
        return False

    remaining = [j for j in listings if str(j.get("id")) != str(listing_id)]
    job_service.save_listings(remaining)
    log_service.append_log(
        "job_delete",
        target.get("job_title") or str(listing_id),
        f"Company: {target.get('company_name') or '-'}",
    )
    return True
