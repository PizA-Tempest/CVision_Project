"""
validation_service.py — Shared Field-Validation Guards

Implements M-004 (validateRequiredFields) and M-019 (validateRequired),
the required-field checks used by:
  - scraper_controller.createScraper (UC-F1-001 / SRS-006), guarding
    the "Create Scraper" form.
  - job_controller.updateListing (UC-F1-004 / SRS-026, SRS-032),
    guarding the job-listing edit form.

Both sequence diagrams show the same shape: controller calls the guard
first; on failure it throws MissingFieldException straight back to the
controller, which rejects the save and highlights the missing fields
(never reaching buildCurl/saveScraper or saveListing). Pure functions,
no storage dependency — nothing here talks to db.py.
"""


class MissingFieldException(Exception):
    """
    Raised by either guard below when a required field is blank.
    Caught by the calling controller (createScraper / updateListing),
    which rejects the save and reports the missing fields back to the
    form instead of persisting anything.
    """


def validate_required_fields(website_name, parameters):
    """
    M-004 — validateRequiredFields(website_name: str, parameters: dict) -> None

    Verifies that the website name and every required parameter
    contain a non-empty value before a scraper is saved. Corresponds
    to the required-field check in the create-form submit handler
    (UC-F1-001).

    Parameters:
        website_name: str — Scraper display name to validate.
        parameters: dict — Submitted values for the profile's
            *required* parameters only, keyed by field name. This
            guard has no field-definition metadata of its own (the
            signature carries no such argument) — it is the caller's
            job (scraper_controller.createScraper, which holds the
            profile via getProfile) to already know which fields are
            required and pass just that subset here. This matches
            UT-1-04-003, whose input dict contains only the one
            required field being tested ({"location": ""}), not the
            profile's optional fields alongside it.

    Returns:
        None — completes silently when every required field is
        present (UT-1-04-001).

    Throws:
        MissingFieldException —
            "Website Name is required." when website_name is blank
            (UT-1-04-002);
            "Required fields missing: <name, name, ...>" listing every
            blank required parameter, in dict iteration order
            (UT-1-04-003).
        Website name is checked first: if both it and a parameter are
        blank, only the website-name message is raised, since only one
        exception can surface per call and the original create-form
        copy always led with that message.
    """
    if not (website_name or "").strip():
        raise MissingFieldException("Website Name is required.")

    missing = [name for name, value in parameters.items() if not (value or "").strip()]
    if missing:
        raise MissingFieldException(f"Required fields missing: {', '.join(missing)}")


def validate_required(url, job_title, company_name, job_location, job_details):
    """
    M-019 — validateRequired(url, job_title, company_name, job_location, job_details) -> None

    Confirms the five mandatory job fields are non-empty before an
    edit is saved. Corresponds to the required-field check in the
    edit form (UC-F1-004).

    Parameters:
        url: str — Listing URL. Required.
        job_title: str — Job title. Required.
        company_name: str — Hiring company. Required.
        job_location: str — Job location. Required.
        job_details: str — Full description. Required.

    Returns:
        None — completes silently when all five required fields are
        present (UT-1-19-001).

    Throws:
        MissingFieldException — "Required fields missing: <name,
            name, ...>" listing every blank field, in the parameter
            order above (UT-1-19-002: a single blank job_location
            raises "Required fields missing: job_location").
    """
    fields = [
        ("url", url),
        ("job_title", job_title),
        ("company_name", company_name),
        ("job_location", job_location),
        ("job_details", job_details),
    ]
    missing = [name for name, value in fields if not (value or "").strip()]
    if missing:
        raise MissingFieldException(f"Required fields missing: {', '.join(missing)}")
