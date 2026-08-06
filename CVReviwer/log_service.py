"""
log_service.py — Shared Activity-Logging Operation

Implements M-023 (appendLog), the single logging path invoked by every
create / edit / delete / run / schedule action across all four use
cases (UC-F1-001 to UC-F1-004): SRS-004 (scraper created), SRS-013
(fetch run), SRS-015/016 (run error / timeout), SRS-020 (schedule
saved), SRS-022/023 (auto-run success / failure), SRS-027 (job edited),
SRS-030 (job marked/unmarked outdated), SRS-031 (job deleted).

Opens no connection of its own — its single write goes through
db.py's execute() (M-031), per the File Structure rule that db.py is
the storage layer beneath the services. There is no read path here:
see the note at the foot of this file about how the Log tab reads
log_entry back.

A note on "user": the Method Description's signature for M-023 is
    appendLog(action: str, target: str, detail: str) -> bool
with no user parameter, yet its own test cases (UT-1-23-001/002)
expect the persisted row to include the acting admin (e.g. user:
"PS"), and none of the four sequence diagrams show a call that passes
one in either. The original _append_log() got this from
st.session_state["admin_user"] directly. To keep the exact 3-argument
signature the spec and its tests require, without importing streamlit
into a service module, this module holds a small piece of session
state of its own: set_current_user() is called once by admin.py right
after a successful login, and append_log() reads it internally rather
than requiring every caller to pass it. Falls back to "system" for
entries with no attributable admin (e.g. before login, or automatic
runs triggered outside a session).

set_current_user() is not one of the 32 methods in the Method
Description — see the "To be documented" marker on it below, and
TBD_and_Conflicts.md for the running list of everything like it
across the codebase.
"""

import uuid
from datetime import datetime, timezone

import db

# Data Dictionary LogEntry.action enum, for reference only — not
# enforced here, since M-023 documents no validation throw.
VALID_ACTIONS = {
    "add", "edit", "delete", "configure", "schedule", "run", "auto_run",
    "profile_create", "profile_delete", "job_edit", "job_mark", "job_delete",
}

_current_user = "system"


# To be documented — see TBD_and_Conflicts.md
def set_current_user(user_id):
    """
    Records who is currently logged in, so append_log() can stamp
    entries with the acting admin without taking it as a parameter
    (see module docstring). Call this once, right after admin.py's
    login gate succeeds.

    Parameters:
        user_id: str — the authenticated admin's Admin.id. admin.py's
            login gate resolves the username to that UUID before
            calling this, so log_entry.user_id holds the foreign key
            the Data Dictionary specifies. Falls back to "system" when
            passed nothing.
    """
    global _current_user
    _current_user = user_id or "system"


def append_log(action, target_name, detail=""):
    """
    M-023 — appendLog(action: str, target: str, detail: str) -> bool

    Writes one activity-log entry (action, affected scraper/listing,
    detail, current user, and UTC timestamp) to the LogEntry table.

    Parameters:
        action: str — Log kind, e.g. add, edit, delete, configure,
            schedule, run, auto_run, profile_create, profile_delete,
            job_edit, job_mark, job_delete (see VALID_ACTIONS).
        target_name: str — Name of the affected scraper or job listing.
        detail: str — Optional free-text detail (added/skipped counts,
            error text, schedule info). Defaults to "".

    Returns:
        bool — True when the entry was appended.

    Throws:
        db.DatabaseError — propagated unchanged when the insert fails.
        M-023 documents no throws of its own, so no extra
        catching/swallowing is added here: a failed log write surfaces
        the same way any other failed write would.
    """
    entry_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)

    db.execute(
        """
        INSERT INTO log_entry (id, user_id, action, target_name, detail, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (entry_id, _current_user, action, target_name, detail, timestamp),
    )
    return True


# Reading the log_entry table back out for the Log tab doesn't need a
# wrapper here: db.query() is already M-030, so whatever renders that
# tab (admin.py) can call
#     db.query("SELECT ... FROM log_entry ORDER BY timestamp DESC LIMIT %s", (limit,))
# directly, using a method that's already in the Method Description
# instead of a new one being added to it.
