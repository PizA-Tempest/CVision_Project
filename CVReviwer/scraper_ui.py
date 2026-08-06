"""
scraper_ui.py — Frontend (Streamlit) Handler for the Schedule Panel

Implements M-028 (openSchedulePanel) for UC-F1-003 (Schedule Job
Fetching) / SRS-017.

Unlike scraper_controller.py and scraper_service.py — deliberately kept
framework-free so they could be unit-tested like everything else in
this project — CVision_File_Structure.docx calls this file out as
running "in the UI layer... matching the UI / Frontend lifeline in the
sequence diagrams — rather than in the controller or service." So this
file does import streamlit and render widgets directly, calling into
scraper_controller.py's pure functions (find_scraper, preview_next_run,
save_schedule) for the actual lookup, computation and persistence
rather than duplicating any of them. Since C4 it imports no service
module at all — only its controller.

That said, M-028's own test cases (UT-1-28-001/002) only check a plain
dict, not any rendered widget — so the pre-fill logic is split out into
_schedule_defaults() below, which is independently testable the same
way every other file in this project has been. The widget-rendering
code around it follows the same layout as the original admin.py inline
schedule panel, but — unlike every other file built so far — it can't
be exercised end-to-end in this sandbox: Streamlit widgets only run
inside a live `streamlit run` server loop, not a plain `import`, so
only _schedule_defaults() and _parse_iso_z() are actually verified.
The widget code around them still needs a manual smoke-test in a real
Streamlit session; this is recorded in TBD_and_Conflicts.md.
"""

from datetime import datetime

import streamlit as st

import scraper_controller

_INTERVAL_OPTIONS = ["weekly", "biweekly", "monthly"]


def _parse_iso_z(value):
    """Turns a schedule Timestamp — handed over as an ISO-Z string
    after C1 ("2026-07-01T08:00:00Z") — into a datetime, so the date
    and time widgets can be pre-filled. Returns None when there is no
    stored run_at.

    Local rather than borrowed from scraper_service (C4): this is a
    UI-layer file, and pre-filling widgets is presentation, not
    business logic. Narrow on purpose — ISO-Z is the only shape the
    service layer emits for these columns."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None


def _schedule_defaults(scraper_id):
    """
    The pure, testable half of M-028: derives the dict used to
    pre-fill the panel from the scraper's current schedule, or a
    sensible default when it has none yet. Kept separate from the
    rendering below specifically so it can be checked against
    UT-1-28-001/002 without a live Streamlit runtime.

    Note this shape does NOT match persist_schedule's own return
    shape (scraper_service.py) for a recurring schedule — that one
    drops last_auto_run for recurring (UT-1-12-001), this one keeps
    it whenever a real schedule row exists (UT-1-28-001 is recurring
    *and* includes last_auto_run: null). See TBD_and_Conflicts.md;
    this reproduces UT-1-28's shape specifically rather than reusing
    persist_schedule's mode-aware logic wholesale.

    Returns:
        dict — matches UT-1-28-001 (existing recurring schedule, with
        last_auto_run present) and UT-1-28-002 (no schedule yet:
        {"mode": "fixed", "run_at": None, "enabled": True}).
    """
    scraper = scraper_controller.find_scraper(scraper_id)
    schedule = scraper.get("schedule") if scraper else None
    if not schedule:
        return {"mode": "fixed", "run_at": None, "enabled": True}

    defaults = {"mode": schedule.get("mode"), "enabled": bool(schedule.get("enabled", True))}
    if schedule.get("mode") == "fixed":
        defaults["run_at"] = schedule.get("run_at")
    elif schedule.get("mode") == "recurring":
        defaults["interval"] = schedule.get("interval")
    defaults["last_auto_run"] = schedule.get("last_auto_run")
    return defaults


def open_schedule_panel(scraper_id):
    """
    M-028 — openSchedulePanel(scraper_id: str) -> dict

    Opens the inline schedule panel for a configured scraper when the
    administrator clicks the schedule button (SRS-017): renders the
    schedule-type selector (Fixed or Recurring), the date/time or
    interval inputs, and the enabled toggle, pre-filled from any
    existing schedule. Live-previews the next run via
    scraper_controller.preview_next_run (M-011 / SRS-018), and on Save
    forwards to scraper_controller.save_schedule (M-012, which itself
    calls persistSchedule / M-013 and logs the "schedule" entry —
    SRS-019/020); this function doesn't call log_service directly.

    Parameters:
        scraper_id: str — The configured scraper whose schedule panel
            is opened.

    Returns:
        dict — the current schedule configuration used to populate
        the panel (UT-1-28-001 with an existing recurring schedule;
        UT-1-28-002's default shape when the scraper has none yet).
        The widgets rendered around this return value aren't part of
        what the test cases check.

    Throws:
        -
    """
    defaults = _schedule_defaults(scraper_id)

    st.markdown("#### 📅 Schedule")

    mode = st.radio(
        "Schedule type",
        ["fixed", "recurring"],
        index=["fixed", "recurring"].index(defaults.get("mode", "fixed")),
        horizontal=True,
        format_func=lambda m: "Fixed date & time" if m == "fixed" else "Recurring interval",
        key=f"sched_mode_{scraper_id}",
    )

    preview_values = {}
    if mode == "fixed":
        st.caption("Run once at a specific date and time (UTC).")
        existing_run_at = _parse_iso_z(defaults.get("run_at"))
        col_date, col_time = st.columns(2)
        with col_date:
            run_date = st.date_input(
                "Date (UTC)",
                value=existing_run_at.date() if existing_run_at else None,
                key=f"sched_date_{scraper_id}",
            )
        with col_time:
            run_time = st.time_input(
                "Time (UTC)",
                value=existing_run_at.time() if existing_run_at else None,
                key=f"sched_time_{scraper_id}",
            )
        preview_values["run_at"] = f"{run_date}T{run_time}Z" if run_date and run_time else None

    else:
        st.caption("Run automatically on a repeating schedule.")
        current_interval = defaults.get("interval", "weekly")
        interval = st.selectbox(
            "Interval",
            _INTERVAL_OPTIONS,
            index=_INTERVAL_OPTIONS.index(current_interval) if current_interval in _INTERVAL_OPTIONS else 0,
            key=f"sched_interval_{scraper_id}",
        )
        preview_values["interval"] = interval
        scraper = scraper_controller.find_scraper(scraper_id)
        preview_values["last_request_date"] = scraper.get("last_request_date") if scraper else None

    enabled = st.toggle(
        "Enable this schedule",
        value=defaults.get("enabled", True),
        key=f"sched_enabled_{scraper_id}",
    )

    preview_text = scraper_controller.preview_next_run(mode, preview_values)
    if preview_text:
        st.caption(preview_text)

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Save Schedule", type="primary", key=f"sched_save_{scraper_id}"):
            schedule = {"mode": mode, "enabled": enabled, **preview_values}
            schedule.pop("last_request_date", None)  # preview-only input, not a schedule field
            scraper_controller.save_schedule(scraper_id, schedule)
            st.success("Schedule saved.")
            st.rerun()
    with col_cancel:
        if st.button("Cancel", key=f"sched_cancel_{scraper_id}"):
            st.rerun()

    return defaults
