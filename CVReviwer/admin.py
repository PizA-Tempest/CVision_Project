"""
admin.py — Thin Streamlit Orchestrator

The final file in the Feature #1 refactor. Owns login, tab navigation,
and rendering — every actual decision (validation, persistence,
scheduling, fetching) lives in the eight files built before this one.
No business logic here beyond what's needed to turn a button click
into a call to job_controller.py / scraper_controller.py / scraper_ui.py.

SCOPE DECISIONS — read before extending this file
===================================================
A few things the original admin.py did are deliberately NOT reproduced
here, because cross-checking against the Method Description turned up
no M-numbered method (or even an implied one) covering them:

  - Provider-profile creation ("paste a new curl command" — already
    commented out/disabled in the original code itself), deletion, and
    profile-level field-map configuration. loadProfileForm (M-001) and
    getProfile (M-002) only ever *read* an existing, already-configured
    profile; nothing in the 32 methods creates, edits, or deletes one.
    Profiles are treated as pre-existing/seeded data.
  - Per-scraper field-map (re)configuration (the "⚙️ Configure" panel
    with its live test-run wizard). A scraper only ever gets a
    field_map via save_scraper's (M-006) auto-inherit-from-profile
    step at creation time. Notably, "configure" IS one of
    log_service.py's VALID_ACTIONS (from the Data Dictionary's
    LogEntry.action enum) — so the schema anticipates this feature
    existing, but no M-numbered method implements it. See
    TBD_and_Conflicts.md.
  - Editing an existing scraper's name/description/raw request.
  - Real authentication. Every SRS use case lists "The Admin is
    authenticated and logged in" as a precondition, but authentication
    itself belongs to "Feature #5: Authentication" — a separate
    feature, not covered by any document handed to me for this
    refactor. The login gate below is a minimal stand-in reading the
    Data Dictionary's Admin table directly (plaintext comparison,
    matching that table's own example data), just enough for this
    file to run standalone. It should be replaced by whatever
    Feature #5 actually specifies.

Two things WERE added, despite not being in the 32 methods, because
their absence would be a real functional gap rather than a missing
nicety: scraper_service.list_profile_names() (the Create tab's picker
needs *something* to list, reached here through
scraper_controller.get_profiles()) and scraper_service.delete_scraper() /
scraper_controller.delete_scraper() (every other entity in this system
can be deleted; scrapers, oddly, have no M-numbered deleteScraper at
all). Both are marked "To be documented" at their definitions.

LAYERING (C4)
=============
This file talks to controllers — job_controller, scraper_controller,
scraper_ui — plus log_service.set_current_user() at login. Neither
job_service nor scraper_service is imported here at all: display
formatting is local (_format_timestamp), the outdated-lock state is
derived from what getListings already returns, and the profile picker
goes through scraper_controller.get_profiles().

Two direct db.query() calls remain, against File Structure's line that
db.py is "used by scraper_service.py, job_service.py and log_service.py
— the only module that issues SQL":

  - The Log tab read. Kept deliberately: the alternative is a
    log_service.get_recent_logs() wrapper, and db.query() is already
    M-030, so this trades a layering deviation for *not* adding an
    undocumented method. That trade was chosen on purpose; flip it by
    moving this query into log_service.py if the layering rule matters
    more.
  - The login lookup against the Admin table. No service owns Admin —
    authentication is Feature #5 and outside this refactor entirely
    (see above), so there is nowhere in the target structure to put it.

Both are recorded in TBD_and_Conflicts.md rather than left implicit.
"""

from datetime import datetime, timezone
from html import escape as _esc

import streamlit as st

import db
import job_controller
import log_service
import scraper_controller
import scraper_ui
import validation_service

# Static reference data for the Create tab's "standard_choice" parameter
# fields (e.g. a country dropdown) — pure UI convenience, not backed by
# any document; copied from the original admin.py unchanged.
STANDARD_CHOICE_SETS = {
    "iso_country": [
        ("Afghanistan", "AF"), ("Albania", "AL"), ("Algeria", "DZ"), ("Andorra", "AD"),
        ("Angola", "AO"), ("Argentina", "AR"), ("Armenia", "AM"), ("Australia", "AU"),
        ("Austria", "AT"), ("Azerbaijan", "AZ"), ("Bahamas", "BS"), ("Bahrain", "BH"),
        ("Bangladesh", "BD"), ("Belarus", "BY"), ("Belgium", "BE"), ("Belize", "BZ"),
        ("Brazil", "BR"), ("Bulgaria", "BG"), ("Cambodia", "KH"), ("Cameroon", "CM"),
        ("Canada", "CA"), ("Chile", "CL"), ("China", "CN"), ("Colombia", "CO"),
        ("Croatia", "HR"), ("Cyprus", "CY"), ("Czech Republic", "CZ"), ("Denmark", "DK"),
        ("Egypt", "EG"), ("Estonia", "EE"), ("Finland", "FI"), ("France", "FR"),
        ("Germany", "DE"), ("Greece", "GR"), ("Hong Kong", "HK"), ("Hungary", "HU"),
        ("India", "IN"), ("Indonesia", "ID"), ("Ireland", "IE"), ("Israel", "IL"),
        ("Italy", "IT"), ("Japan", "JP"), ("Kenya", "KE"), ("Malaysia", "MY"),
        ("Mexico", "MX"), ("Netherlands", "NL"), ("New Zealand", "NZ"), ("Nigeria", "NG"),
        ("Norway", "NO"), ("Pakistan", "PK"), ("Philippines", "PH"), ("Poland", "PL"),
        ("Portugal", "PT"), ("Romania", "RO"), ("Russia", "RU"), ("Saudi Arabia", "SA"),
        ("Singapore", "SG"), ("South Africa", "ZA"), ("South Korea", "KR"), ("Spain", "ES"),
        ("Sweden", "SE"), ("Switzerland", "CH"), ("Taiwan", "TW"), ("Thailand", "TH"),
        ("Turkey", "TR"), ("Ukraine", "UA"), ("United Arab Emirates", "AE"),
        ("United Kingdom", "GB"), ("United States", "US"), ("Vietnam", "VN"),
    ],
}


def _format_timestamp(value, fmt="%Y-%m-%d %H:%M UTC"):
    """
    Display-only formatting — never used for a comparison or a
    persisted value, just how a date/time reads on screen.

    C4: this used to call scraper_service.coerce_datetime(), which
    meant the UI layer reached into a service for parsing. Formatting
    for display is genuinely a UI concern, and after C1 the services
    hand out only two shapes, so a local formatter needs no general
    date parser: a native datetime (log_entry.timestamp, read here),
    or an ISO-Z string (job_posted_date, schedule.run_at). Values
    already in display form ("2026-06-09 20:12 UTC", "-") pass
    straight through, so a scraper's last_request_date needs no
    formatting at all.
    """
    if value in (None, "", "-"):
        return "Never"
    if isinstance(value, datetime):
        return value.strftime(fmt)
    text = str(value)
    if text.endswith("Z"):
        try:
            return datetime.fromisoformat(text[:-1] + "+00:00").strftime(fmt)
        except ValueError:
            return text
    return text


def _authenticate(username, password):
    """Minimal stand-in for Feature #5 (Authentication) — see the
    module docstring. Plaintext comparison against the Admin table,
    matching the Data Dictionary's own example data for that column."""
    rows = db.query("SELECT id, username, password FROM admin WHERE username = %s", (username,))
    if rows and rows[0].get("password") == password:
        return rows[0]
    return None


# ---------------------------------------------------------------------
# Scrapers tab — UC-F1-002 / UC-F1-003
# ---------------------------------------------------------------------

def _render_scrapers_tab():
    auto_results = st.session_state.get("_auto_run_results") or []
    for name, added, skipped, error in auto_results:
        if error:
            st.warning(f"Auto-run **{name}** failed: {error}")
        else:
            st.success(f"Auto-ran **{name}** — {added} new jobs, {skipped} skipped.")

    run_result = st.session_state.get("scraper_run_result")
    if run_result:
        if run_result.get("error"):
            st.error(f"Run **{run_result['name']}** failed: {run_result['error']}")
        else:
            st.success(
                f"Done! **{run_result['added']}** new jobs saved. "
                f"**{run_result['skipped']}** duplicates skipped."
            )

    scrapers = scraper_controller.get_scrapers()

    delete_id = st.session_state.get("scraper_delete_id")
    if delete_id is not None:
        target = next((s for s in scrapers if s.get("id") == delete_id), None)
        if target:
            st.warning(f"Delete **{target['website_name']}**? This cannot be undone.")
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("Yes, delete", type="primary", key="confirm_scraper_del"):
                    scraper_controller.delete_scraper(delete_id)
                    st.session_state["scraper_delete_id"] = None
                    st.success("Scraper deleted.")
                    st.rerun()
            with col_no:
                if st.button("Cancel", key="cancel_scraper_del"):
                    st.session_state["scraper_delete_id"] = None
                    st.rerun()

    if not scrapers:
        st.info("No scrapers yet. Go to the **Create** tab to add one.")

    for s in scrapers:
        sid = s.get("id")
        has_map = bool(s.get("field_map"))
        sched = s.get("schedule") or {}
        has_sched = bool(sched.get("enabled"))

        with st.container(border=True):
            row = st.columns([5, 2, 2, 1, 1, 1, 1])
            row[0].markdown(f"**{s.get('website_name', '-')}**")
            # last_request_date already arrives as a display string
            # ("-" or "2026-06-09 20:12 UTC") from getScrapers (C1), so
            # there is nothing left for the UI to format here.
            row[1].caption(f"Last run: {s.get('last_request_date') or '-'}")

            if has_sched:
                if sched.get("mode") == "fixed":
                    badge = f"📅 {_format_timestamp(sched.get('run_at'), '%Y-%m-%d')}"
                else:
                    interval_label = {
                        "weekly": "Weekly", "biweekly": "2-week", "monthly": "Monthly",
                    }.get(sched.get("interval", ""), "")
                    badge = f"🔁 {interval_label}"
                row[2].caption(badge)
            else:
                row[2].caption("No schedule")

            row[3].markdown(
                "✅" if has_map else "⚠️",
                help="Field map configured" if has_map else
                     "No field map — set at creation from a mapped profile; Run/Schedule stay disabled until then",
            )

            if row[4].button("✏️", key=f"edit_btn_{sid}", help="Edit name, description or request"):
                st.session_state["scraper_edit_id"] = (
                    None if st.session_state.get("scraper_edit_id") == sid else sid
                )
                st.rerun()

            if row[5].button(
                "📅", key=f"sched_btn_{sid}",
                help="Set schedule" if has_map else "Needs a field map first",
                disabled=not has_map,
            ):
                st.session_state["scraper_schedule_id"] = (
                    None if st.session_state.get("scraper_schedule_id") == sid else sid
                )
                st.rerun()

            if row[6].button("🗑️", key=f"del_btn_{sid}", help="Delete"):
                st.session_state["scraper_delete_id"] = sid
                st.rerun()

            st.caption(s.get("description") or "")

            if st.session_state.get("scraper_edit_id") == sid:
                st.markdown("---")
                with st.form(f"scraper_edit_form_{sid}"):
                    st.markdown("##### ✏️ Edit scraper")
                    e_name = st.text_input("Website Name *", value=s.get("website_name") or "")
                    e_desc = st.text_area("Description", value=s.get("description") or "", height=80)
                    e_req = st.text_area(
                        "Request (curl command)", value=s.get("request") or "", height=160,
                        help="Edited directly. The field mapping is not changed here — it is "
                             "inherited from the source profile when the scraper is created.",
                    )
                    col_save, col_cancel = st.columns(2)
                    with col_save:
                        save = st.form_submit_button("💾 Save", type="primary")
                    with col_cancel:
                        cancel = st.form_submit_button("Cancel")
                    if save:
                        try:
                            scraper_controller.update_scraper(
                                sid,
                                {"website_name": e_name, "description": e_desc, "request": e_req},
                            )
                            st.session_state["scraper_edit_id"] = None
                            st.success("Scraper updated.")
                            st.rerun()
                        except validation_service.MissingFieldException as ex:
                            st.error(str(ex))
                    if cancel:
                        st.session_state["scraper_edit_id"] = None
                        st.rerun()

            if st.button(
                "▶ Run", key=f"run_btn_{sid}",
                help="Run scraper & save jobs" if has_map else "Needs a field map first",
                disabled=not has_map,
            ):
                with st.spinner("Calling scraper API..."):
                    try:
                        result = scraper_controller.run_scraper(sid)
                        st.session_state["scraper_run_result"] = {"name": s["website_name"], **result}
                    except (scraper_controller.APIError, scraper_controller.SnapshotTimeout) as ex:
                        st.session_state["scraper_run_result"] = {"name": s["website_name"], "error": str(ex)}
                st.rerun()

            if st.session_state.get("scraper_schedule_id") == sid:
                st.markdown("---")
                scraper_ui.open_schedule_panel(sid)


# ---------------------------------------------------------------------
# Data tab — UC-F1-004
# ---------------------------------------------------------------------

_EDITABLE_JOB_FIELDS = (
    ("url", "URL", True), ("job_title", "Job Title", True),
    ("company_name", "Company Name", True), ("job_location", "Job Location", True),
    ("job_details", "Job Details", True), ("job_employment_type", "Employment Type", False),
    ("job_posted_date", "Posted Date", False), ("salary", "Salary", False),
)


def _render_data_tab():
    listings = job_controller.get_listings()
    st.caption(f"{len(listings)} jobs total")
    if not listings:
        st.info("No job listings yet. Run a scraper from the **Scrapers** tab.")

    delete_id = st.session_state.get("job_delete_id")
    if delete_id is not None:
        target = next((j for j in listings if j.get("id") == delete_id), None)
        if target:
            st.warning(f"Delete job **{target.get('job_title', '-')}**? This cannot be undone.")
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("Yes, delete", type="primary", key="confirm_job_del"):
                    job_controller.delete_listing(delete_id)
                    st.session_state["job_delete_id"] = None
                    st.success("Job deleted.")
                    st.rerun()
            with col_no:
                if st.button("Cancel", key="cancel_job_del"):
                    st.session_state["job_delete_id"] = None
                    st.rerun()

    for job in listings:
        jid = job.get("id")

        if st.session_state.get("job_edit_id") == jid:
            with st.container(border=True):
                with st.form(f"job_edit_form_{jid}"):
                    values = {}
                    for name, label, required in _EDITABLE_JOB_FIELDS:
                        field_label = f"{label} *" if required else label
                        if name == "job_details":
                            values[name] = st.text_area(field_label, value=job.get(name) or "", height=120)
                        else:
                            values[name] = st.text_input(field_label, value=job.get(name) or "")
                    col_save, col_cancel = st.columns(2)
                    with col_save:
                        save = st.form_submit_button("💾 Save", type="primary")
                    with col_cancel:
                        cancel = st.form_submit_button("Cancel")
                    if save:
                        try:
                            job_controller.update_listing(jid, values)
                            st.session_state["job_edit_id"] = None
                            st.success("Job updated.")
                            st.rerun()
                        except validation_service.MissingFieldException as ex:
                            st.error(str(ex))
                    if cancel:
                        st.session_state["job_edit_id"] = None
                        st.rerun()
            continue

        outdated = job.get("outdated", False)
        manual_flag = bool(job.get("outdated_manual"))
        # C4: this used to call job_service.is_system_outdated() — the UI
        # reaching past its controller into a service. The lock state is
        # already derivable from what getListings (M-016) returns:
        # "outdated" is the manual flag OR the 365-day rule (M-017), so
        # when the manual flag is off, an outdated listing can only be
        # system-outdated — which is exactly when unmarking is locked
        # (M-021 / SRS-029). Identical in every case to the old call.
        outdate_locked = outdated and not manual_flag

        with st.container(border=True):
            col_title, col_badge, col_btns = st.columns([6, 2, 2])
            with col_title:
                st.markdown(f"**{job.get('job_title', '-')}** @ {job.get('company_name', '-')}")
                st.caption(
                    f"{job.get('job_location', '-')} | "
                    f"{_format_timestamp(job.get('job_posted_date'))} | "
                    f"{job.get('salary') or 'No salary listed'}"
                )
            with col_badge:
                if outdated:
                    # Labelled by the manual flag rather than the system
                    # rule: it's the one the admin can actually act on,
                    # and it's the only half derivable here (C4). A
                    # listing that is both manually marked and 365+ days
                    # old now reads "manually marked" — still accurate,
                    # just less specific than before.
                    reason = "Outdated (manually marked)" if manual_flag else "Outdated (365+ days)"
                    st.markdown(
                        f"<span style='background:#fef2f2;color:#dc2626;padding:3px 10px;"
                        f"border-radius:999px;font-size:12px;font-weight:600' title='{reason}'>Outdated</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<span style='background:#f0fdf4;color:#16a34a;padding:3px 10px;"
                        "border-radius:999px;font-size:12px;font-weight:600'>Active</span>",
                        unsafe_allow_html=True,
                    )
            with col_btns:
                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button("✏️", key=f"job_edit_btn_{jid}", help="Edit"):
                        st.session_state["job_edit_id"] = jid
                        st.rerun()
                with b2:
                    if st.button(
                        "↩️" if manual_flag else "⏳", key=f"job_outdate_btn_{jid}",
                        help=(
                            "Already outdated by system — cannot unmark" if outdate_locked else
                            ("Unmark as outdated" if manual_flag else "Mark as outdated")
                        ),
                        disabled=outdate_locked,
                    ):
                        try:
                            job_controller.mark_outdated(jid, not manual_flag)
                            st.rerun()
                        except job_controller.OutdatedLockError as ex:
                            st.error(str(ex))
                with b3:
                    if st.button("🗑️", key=f"job_del_btn_{jid}", help="Delete"):
                        st.session_state["job_delete_id"] = jid
                        st.rerun()

            with st.expander("Details"):
                st.write(job.get("job_details") or "-")
                st.caption(f"Employment type: {job.get('job_employment_type') or '-'}")
                if job.get("url"):
                    st.markdown(f"[🔗 View posting]({job['url']})")


# ---------------------------------------------------------------------
# Log tab
# ---------------------------------------------------------------------

def _relative_age(dt):
    """'(1 minute ago)' / '(2 hours ago)' as shown in the wireframe."""
    if not isinstance(dt, datetime):
        return ""
    now = datetime.now(timezone.utc)
    ref = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    secs = max(0, int((now - ref).total_seconds()))
    for limit, div, unit in ((60, 1, "second"), (3600, 60, "minute"),
                             (86400, 3600, "hour"), (2592000, 86400, "day")):
        if secs < limit:
            n = secs // div
            return f"({n} {unit}{'s' if n != 1 else ''} ago)"
    return f"({secs // 2592000} month{'s' if secs // 2592000 != 1 else ''} ago)"


def _log_style(action, detail):
    """
    Maps a stored log entry to the wireframe's presentation: icon,
    human-readable label, and colour band.

    The label is finer-grained than the stored `action` alone, because
    the wireframe distinguishes cases that share one action value — a
    "run" reads as "Manual run", "Run stopped - API error", or "Run
    stopped - timeout" depending on outcome, and "auto_run" as
    "Scheduled run" or "Scheduled run failed". Those are exactly the
    distinctions SRS-013 / SRS-015 / SRS-016 and SRS-022 / SRS-023 draw,
    so the split comes from the detail text the service layer already
    writes rather than from a new column.

    Pure function, kept separate from the rendering so it is testable
    without a Streamlit runtime.

    Returns:
        tuple(icon, label, border_colour, background_colour)
    """
    BLUE  = ("#3b82f6", "#eff6ff")
    RED   = ("#dc2626", "#fef2f2")
    AMBER = ("#d97706", "#fefce8")
    GREEN = ("#16a34a", "#f0fdf4")
    text = (detail or "").lower()

    if action == "run":
        if "timed out" in text or "timeout" in text:
            return ("⏳", "Run stopped - timeout", *AMBER)
        if any(w in text for w in ("error", "unauthorized", "failed", "invalid", "credential")):
            return ("⛔", "Run stopped - API error", *RED)
        return ("▶", "Manual run", *BLUE)

    if action == "auto_run":
        if text.startswith("failed") or "failed" in text:
            return ("⏰", "Scheduled run failed", *RED)
        return ("⏰", "Scheduled run", *BLUE)

    return {
        "add":            ("➕", "Added scraper", *GREEN),
        "delete":         ("🗑", "Deleted scraper", *RED),
        "schedule":       ("📅", "Set schedule", *GREEN),
        "job_edit":       ("✏️", "Edited job", *AMBER),
        "job_mark":       ("⏳", "Marked/unmarked job", *AMBER),
        "job_delete":     ("🗑", "Deleted job", *RED),
        "edit":           ("✏️", "Edited scraper", *AMBER),
        "configure":      ("⚙️", "Configured field mapping", *GREEN),
        "profile_create": ("➕", "Added profile", *GREEN),
        "profile_delete": ("🗑", "Deleted profile", *RED),
    }.get(action, ("•", action or "-", "#94a3b8", "#f8fafc"))


def _render_log_tab():
    """
    No M-XXX method covers reading the log back out (only appendLog,
    M-023, writes to it). Reads log_entry directly via db.query() —
    already M-030 — rather than adding a new wrapper method, per the
    decision recorded in TBD_and_Conflicts.md.

    Joins admin so each entry shows the acting username, as the
    wireframe does. log_entry.user_id stores the Admin.id UUID (per the
    Data Dictionary), which is not what an administrator should be
    reading off the screen.
    """
    rows = db.query(
        "SELECT l.id, l.user_id, a.username, l.action, l.target_name, l.detail, l.timestamp "
        "FROM log_entry l LEFT JOIN admin a ON a.id = l.user_id "
        "ORDER BY l.timestamp DESC LIMIT %s",
        (200,),
    )
    if not rows:
        st.info("No activity yet.")
        return

    st.caption(f"{len(rows)} log entries")
    for row in rows:
        icon, label, border, background = _log_style(row.get("action"), row.get("detail"))
        target = row.get("target_name") or "-"
        ts = row.get("timestamp")
        stamp = _format_timestamp(ts, "%b %d, %Y %H:%M")
        age = _relative_age(ts)
        who = row.get("username") or row.get("user_id") or "-"
        detail = row.get("detail") or ""

        st.markdown(
            f"""<div style="border-left:4px solid {border};background:{background};
                 padding:8px 12px;margin-bottom:8px;border-radius:4px;
                 display:flex;justify-content:space-between;align-items:flex-start;gap:16px">
              <div style="min-width:0">
                <div style="font-weight:600;font-size:13px;color:{border}">
                  {icon} {label} - {_esc(target)}</div>
                <div style="font-size:12px;color:#475569;margin-top:2px">{_esc(detail)}</div>
              </div>
              <div style="font-size:11px;color:#94a3b8;white-space:nowrap;text-align:right">
                {stamp} {age} &nbsp;|&nbsp; {_esc(str(who))}</div>
            </div>""",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------
# Create tab — UC-F1-001
# ---------------------------------------------------------------------

def _render_create_tab():
    profile_names = scraper_controller.get_profiles()
    if not profile_names:
        st.info(
            "No saved provider profiles yet. Provider-profile creation isn't part of this "
            "refactor's scope (see the module docstring / TBD_and_Conflicts.md) — profiles "
            "are expected to already exist."
        )
        return

    chosen_name = st.selectbox("Profile", profile_names, key="create_profile_picker")
    profile = scraper_controller.load_profile_form(chosen_name)
    if profile is None:
        st.error("Selected profile could not be loaded.")
        return

    has_map = bool(profile.get("field_map"))
    if not has_map:
        st.warning(
            "This profile has no field mapping yet. Per-profile field-map configuration "
            "isn't part of this refactor's scope — a scraper created from it will have "
            "Run/Schedule disabled until a field_map is set directly on the scraper row."
        )

    with st.form("use_profile_form"):
        n_name = st.text_input("Website Name (this scraper instance) *")
        n_desc = st.text_area("Description", height=80)

        st.markdown("##### Credentials")
        credential_values = {}
        for h in profile.get("headers") or []:
            if h.get("is_credential"):
                prefix = h.get("cred_prefix", "")
                label = (
                    f'{h["key"]} (just the secret — "{prefix.strip()}" is added automatically)'
                    if prefix else h["key"]
                )
                credential_values[h["key"]] = st.text_input(label, type="password", key=f"cred_{h['key']}")

        st.markdown("##### Parameters")
        field_values = {}
        for f in profile.get("fields") or []:
            label = f["name"] + (" *" if f.get("required") else "")
            if f.get("type") == "standard_choice" and f.get("standard") in STANDARD_CHOICE_SETS:
                options = STANDARD_CHOICE_SETS[f["standard"]]
                display = ["(leave blank)"] + [name for name, _code in options]
                sel = st.selectbox(label, display, key=f"val_{f['name']}")
                field_values[f["name"]] = "" if sel == "(leave blank)" else next(
                    (code for name, code in options if name == sel), ""
                )
            elif f.get("type") == "choice" and f.get("choices"):
                display = ["(leave blank)"] + [lbl for lbl, _val in f["choices"]]
                sel = st.selectbox(label, display, key=f"val_{f['name']}")
                field_values[f["name"]] = "" if sel == "(leave blank)" else next(
                    (val for lbl, val in f["choices"] if lbl == sel), ""
                )
            else:
                default_val = f.get("sample_value", "") if not f.get("required") else ""
                field_values[f["name"]] = st.text_input(label, value=default_val, key=f"val_{f['name']}")

        submitted = st.form_submit_button("✅ Create Scraper", type="primary")
        if submitted:
            try:
                created = scraper_controller.create_scraper(
                    chosen_name, n_name, n_desc, credential_values, field_values
                )
                if created.get("field_map"):
                    st.success(
                        f"✅ Added '{created['website_name']}' — field mapping applied "
                        f"automatically. Ready to run from the **Scrapers** tab."
                    )
                else:
                    st.warning(
                        f"✅ Added '{created['website_name']}', but it has no field mapping "
                        f"— Run/Schedule will stay disabled for it."
                    )
            except validation_service.MissingFieldException as ex:
                st.error(str(ex))


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

def show_admin_page():
    for key, default in [
        ("admin_authenticated", False),
        ("admin_user", ""),
        ("active_tab", "Scrapers"),
        ("scraper_delete_id", None),
        ("scraper_edit_id", None),
        ("scraper_schedule_id", None),
        ("scraper_run_result", None),
        ("job_edit_id", None),
        ("job_delete_id", None),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # Login gate — see module docstring re: Feature #5 (Authentication)
    if not st.session_state["admin_authenticated"]:
        st.markdown("## 🔐 Admin Login")
        username = st.text_input("Username", key="admin_username_input")
        password = st.text_input("Password", type="password", key="admin_password_input")
        if st.button("Login"):
            admin = _authenticate(username, password)
            if admin:
                st.session_state["admin_authenticated"] = True
                st.session_state["admin_user"] = username
                # Resolves the log_service.py gap flagged in TBD_and_Conflicts.md:
                # stamps log entries with the Admin's real UUID, not the username.
                log_service.set_current_user(admin.get("id") or username)
                st.rerun()
            else:
                st.error("Invalid credentials")
        st.stop()

    # Runs every rerun, matching the original code's placement (and SRS-022's
    # "on each page load") — Streamlit has no distinct hook for an initial
    # load vs. a widget-triggered rerun, and get_due_scrapers() only returns
    # genuinely due scrapers, so this is self-limiting in practice.
    st.session_state["_auto_run_results"] = scraper_controller.check_due_schedules()

    tabs = ["Scrapers", "Log", "Data", "Create"]
    nav_cols = st.columns(len(tabs) + 1)
    for col, name in zip(nav_cols[:-1], tabs):
        with col:
            if st.button(
                name, key=f"navtab_{name}",
                type="primary" if st.session_state["active_tab"] == name else "secondary",
                use_container_width=True,
            ):
                st.session_state["active_tab"] = name
                st.rerun()
    with nav_cols[-1]:
        if st.button("Log Out", use_container_width=True):
            st.session_state["admin_authenticated"] = False
            st.session_state["admin_user"] = ""
            st.rerun()

    st.markdown("---")

    active_tab = st.session_state["active_tab"]
    if active_tab == "Scrapers":
        _render_scrapers_tab()
    elif active_tab == "Log":
        _render_log_tab()
    elif active_tab == "Data":
        _render_data_tab()
    elif active_tab == "Create":
        _render_create_tab()


# Streamlit executes this file top to bottom with __name__ == "__main__",
# so this is what makes `streamlit run admin.py` actually render. Guarded
# rather than a bare call so the module stays importable — by a parent
# multi-page app, or by a test — without launching the page as a
# side effect. set_page_config must precede every other Streamlit call,
# which is why it lives here rather than inside show_admin_page().
if __name__ == "__main__":
    st.set_page_config(page_title="CVision Admin", page_icon="🛠️", layout="wide")
    show_admin_page()