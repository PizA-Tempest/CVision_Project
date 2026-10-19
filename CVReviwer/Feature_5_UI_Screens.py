"""Feature #5 — Authentication UI Screens (URS demo).

A copy of app.py's real auth UI (same CSS, same form fields, same labels),
with a URS button bar. Click a URS to show its interface and screenshot it.

Run:  .venv\\Scripts\\python.exe -m streamlit run Feature_5_UI_Screens.py
"""

import streamlit as st

st.set_page_config(page_title="Feature 5 — UI Screens", layout="wide")

# =========================================================================
# CSS — copied verbatim from app.py so the UI is identical
# =========================================================================
MAIN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
.title {
    font-family: 'Inter', sans-serif !important;
    font-size: 36px !important;
    font-weight: 700 !important;
    color: #4b4bf7 !important;
    letter-spacing: -0.5px;
}
.subtitle {
    font-family: 'Inter', sans-serif !important;
    font-size: 16px !important;
    color: #6b7280 !important;
}
.card {
    background: white;
    padding: 20px;
    border-radius: 16px;
    box-shadow: 0px 4px 12px rgba(0,0,0,0.05);
    margin-bottom: 15px;
}
div[data-testid="stButton"] > button {
    border-radius: 6px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    padding: 0.5rem 1rem !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;
}
div[data-testid="stButton"] > button[kind="secondary"] {
    background: white !important;
    border: 1px solid #d1d5db !important;
    color: #374151 !important;
}
div[data-testid="stButton"] > button[kind="secondary"]:hover {
    border-color: #ff4b4b !important;
    color: #ff4b4b !important;
}
div[data-testid="stButton"] > button[kind="primary"] {
    background: #ff4b4b !important;
    border: 1px solid #ff4b4b !important;
    color: white !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #ff3333 !important;
    border-color: #ff3333 !important;
}
input::-ms-reveal, input::-ms-clear { display: none !important; }
input::-webkit-credentials-auto-fill-button { visibility: hidden; }
input::-webkit-textfield-decoration-container { visibility: hidden; }
</style>
"""

AUTH_CSS = """
<style>
.auth-brand { text-align: center; margin-bottom: 6px; }
.auth-logo {
    width: 48px; height: 48px; margin: 0 auto 8px auto; border-radius: 14px;
    background: linear-gradient(135deg, #4b4bf7, #8b5cf6);
    display: flex; align-items: center; justify-content: center;
    font-size: 24px; color: white;
    box-shadow: 0 4px 12px rgba(75,75,247,0.35);
}
.auth-title { font-size: 22px; font-weight: 700; color: #111827; margin: 0; }
.auth-sub { font-size: 14px; color: #6b7280; margin: 4px 0 12px 0; }
.auth-footer { text-align: center; font-size: 13px; color: #6b7280; margin-top: 10px; }
.auth-terms { text-align: center; font-size: 12px; color: #9ca3af; margin-top: 10px; }
.pw-meter { height: 6px; border-radius: 999px; background: #e5e7eb; overflow: hidden; margin: 6px 0 2px 0; }
.pw-meter > div { height: 100%; border-radius: 999px; transition: width .2s; }
.pw-label { font-size: 12px; margin-bottom: 6px; }
div[data-testid="stForm"] { border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; }
div[data-testid="stFormSubmitButton"] > button { width: 100%; border-radius: 10px !important; font-weight: 600 !important; }
</style>
"""

st.markdown(MAIN_CSS, unsafe_allow_html=True)
st.markdown(AUTH_CSS, unsafe_allow_html=True)


# =========================================================================
# Helpers — copied from app.py
# =========================================================================
def _auth_brand(title, subtitle):
    st.markdown(
        f'<div class="auth-brand"><div class="auth-logo">📄</div>'
        f'<p class="auth-title">{title}</p>'
        f'<p class="auth-sub">{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def _pw_strength(password):
    pw = password or ""
    score = 0
    if len(pw) >= 8:
        score += 25
    if len(pw) >= 12:
        score += 25
    if any(c.isupper() for c in pw) and any(c.islower() for c in pw):
        score += 25
    if any(c.isdigit() for c in pw) or any(not c.isalnum() for c in pw):
        score += 25
    if score <= 25:
        return score or 5, "Weak", "#ef4444"
    if score <= 50:
        return score, "Okay", "#f59e0b"
    if score <= 75:
        return score, "Good", "#3b82f6"
    return score, "Strong", "#16a34a"


def _guest_header():
    """The real guest header: CVision + Log in / Sign up."""
    _c_logo, _c_auth = st.columns([8, 2], vertical_alignment="center")
    with _c_logo:
        st.markdown('<div class="title">📄 CVision</div>', unsafe_allow_html=True)
    with _c_auth:
        _c_in, _c_up = st.columns(2, gap="small")
        with _c_in:
            st.button("Log in", key="demo_login_top", use_container_width=True)
        with _c_up:
            st.button("Sign up", key="demo_signup_top", type="primary",
                      use_container_width=True)
    st.markdown(
        '<div class="subtitle">Upload your CV and discover your best job matches 🚀</div>',
        unsafe_allow_html=True)
    st.markdown("")


def _user_header(name="alice_j", initial="A"):
    """The real logged-in header: CVision + avatar circle."""
    _c_logo, _c_auth = st.columns([20, 1], vertical_alignment="center")
    with _c_logo:
        st.markdown('<div class="title">📄 CVision</div>', unsafe_allow_html=True)
    with _c_auth:
        st.markdown(
            f"""<style>
            div[data-testid="stHorizontalBlock"]:has(.demo-avatar) {{
                gap: 0 !important;
            }}
            .demo-avatar {{
                width: 42px; height: 42px; border-radius: 50%;
                background: linear-gradient(135deg, #4b4bf7, #8b5cf6);
                display: flex; align-items: center; justify-content: center;
                font-weight: 700; font-size: 20px; color: white;
                box-shadow: 0 2px 8px rgba(75,75,247,0.35);
                margin-left: auto;
            }}
            </style>
            <div class="demo-avatar">{initial}</div>""",
            unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Upload your CV and discover your best job matches 🚀</div>',
        unsafe_allow_html=True)
    st.markdown("")


def _uploader(selected=False):
    if selected:
        st.markdown(
            '<div class="card">📎 Selected file: <strong>CV_2026.pdf</strong></div>',
            unsafe_allow_html=True)
    st.file_uploader(
        "📤 Upload your CV (PDF)",
        type=["pdf"],
        help="Drag and drop your CV here, or click Browse files. PDF format, max 20 MB.",
        key="demo_uploader",
    )


def _centered(card_fn):
    """Render a dialog-like card centered on the page (mimics st.dialog)."""
    _sp1, _mid, _sp2 = st.columns([1, 2.2, 1])
    with _mid:
        card_fn()


# =========================================================================
# URS button bar
# =========================================================================
if "urs_demo" not in st.session_state:
    st.session_state.urs_demo = "URS-010"

st.markdown("### Feature #5 — Authentication UI Screens")
st.caption("Click a URS button — the real app interface for that requirement "
           "appears below. Screenshot the panel.")

_urs_items = [
    ("URS-010", "Register"),
    ("URS-011", "Log in"),
    ("URS-012", "Password"),
    ("URS-013", "Guest block"),
    ("URS-014", "My CVs"),
    ("URS-015", "Log out"),
    ("URS-016", "Reset PW"),
    ("URS-017", "Username"),
]
_cols = st.columns(len(_urs_items))
for _i, ((_uid, _label), _col) in enumerate(zip(_urs_items, _cols)):
    with _col:
        _active = st.session_state.urs_demo == _uid
        if st.button(
            f"**{_uid}**\n{_label}",
            key=f"urs_btn_{_i}",
            use_container_width=True,
            type="primary" if _active else "secondary",
        ):
            st.session_state.urs_demo = _uid
            st.rerun()

st.divider()

# =========================================================================
# Screen renderers
# =========================================================================
def screen_u10():
    """URS-010 — Register (SRS-077, SRS-078)."""
    _guest_header()

    def _card():
        _auth_brand("Create your account",
                    "Create your profile and discover jobs that fit you.")
        with st.form("demo_register_form"):
            st.text_input("Username", key="demo_r_user",
                          placeholder="e.g. alice_j",
                          help="3-30 characters: letters, digits, _ . -")
            st.text_input("Email", key="demo_r_email",
                          placeholder="you@example.com")
            st.text_input("Password", type="password", key="demo_r_pw",
                          placeholder="At least 8 characters",
                          help="8-64 characters. Stored only as a salted hash (SRS-077, SRS-082).")
            st.text_input("Confirm password", type="password",
                          key="demo_r_pw2",
                          placeholder="Repeat password")
            st.form_submit_button("Create account", type="primary")
        st.markdown(
            '<div class="auth-terms">By creating an account you agree to keep '
            'your credentials private.</div>',
            unsafe_allow_html=True)

    _centered(_card)


def screen_u11():
    """URS-011 — Log in (SRS-079, SRS-080, SRS-081)."""
    _guest_header()

    def _card():
        _auth_brand("Welcome back",
                    "Log in to access your CVs and job matches.")
        with st.form("demo_login_form"):
            st.text_input("Username or email", key="demo_identifier",
                          placeholder="you@example.com or username")
            st.text_input("Password", type="password", key="demo_password",
                          placeholder="Enter your password")
            st.form_submit_button("Log In", type="primary")
        st.button("Forgot password?", key="demo_forgot_link",
                  type="tertiary", use_container_width=True)
        st.markdown(
            '<div class="auth-footer">Go to the Register tab to create a free '
            'account.</div>',
            unsafe_allow_html=True)

    _centered(_card)


def screen_u12():
    """URS-012 — Password privacy & strength (SRS-082, SRS-083)."""
    _guest_header()

    def _card():
        _auth_brand("Create your account",
                    "Create your profile and discover jobs that fit you.")
        with st.form("demo_reg_strength"):
            st.text_input("Username", key="demo_s_user",
                          placeholder="e.g. alice_j")
            st.text_input("Email", key="demo_s_email",
                          placeholder="you@example.com")
            st.text_input("Password", type="password", key="demo_s_pw",
                          placeholder="At least 8 characters")
            st.text_input("Confirm password", type="password",
                          key="demo_s_pw2",
                          placeholder="Repeat password")
            st.form_submit_button("Create account", type="primary")
        # strength meter (same widget + CSS as app.py)
        _typed = "Secret123!"
        _pct, _lbl, _col = _pw_strength(_typed)
        st.markdown(
            f'<div class="pw-meter"><div style="width:{_pct}%;background:{_col}"></div></div>'
            f'<div class="pw-label" style="color:{_col}">Password strength: {_lbl}</div>',
            unsafe_allow_html=True)
        st.info("🔒 Password is stored only as a salted hash — never shown in "
                "plain text after entry (SRS-082, SRS-083).")

    _centered(_card)


def screen_u13():
    """URS-013 — Guest sees upload but must log in first (SRS-084, SRS-085)."""
    _guest_header()
    _uploader(selected=True)
    st.warning("🔐 Please log in or create an account to upload your CV.")

    def _card():
        st.caption("Log in or create a free account to upload your CV.")
        _t_login, _t_register = st.tabs(["Log In", "Sign Up"])
        with _t_login:
            _auth_brand("Welcome back",
                        "Log in to access your CVs and job matches.")
            with st.form("demo_guest_login"):
                st.text_input("Username or email", key="demo_gl_id",
                              placeholder="you@example.com or username")
                st.text_input("Password", type="password", key="demo_gl_pw",
                              placeholder="Enter your password")
                st.form_submit_button("Log In", type="primary")
            st.button("Forgot password?", key="demo_gl_forgot",
                      type="tertiary", use_container_width=True)
        with _t_register:
            _auth_brand("Create your account",
                        "Create your profile and discover jobs that fit you.")
            with st.form("demo_guest_reg"):
                st.text_input("Username", key="demo_gr_user",
                              placeholder="e.g. alice_j")
                st.text_input("Email", key="demo_gr_email",
                              placeholder="you@example.com")
                st.text_input("Password", type="password", key="demo_gr_pw",
                              placeholder="At least 8 characters")
                st.text_input("Confirm password", type="password",
                              key="demo_gr_pw2",
                              placeholder="Repeat password")
                st.form_submit_button("Create account", type="primary")

    _centered(_card)


def screen_u14():
    """URS-014 — View my own CVs & matches, private (SRS-086, SRS-087)."""
    _user_header()
    with st.expander("📁 My CVs (2)", expanded=True):
        for _fname, _date in [("CV_2026.pdf", "2026-01-15 10:30"),
                              ("CV_MyCV.pdf", "2025-11-02 14:12")]:
            with st.container(border=True):
                _c1, _c2, _c3 = st.columns([4, 2.6, 1.2],
                                           vertical_alignment="center", gap=0)
                with _c1:
                    st.markdown(f"📄 {_fname}")
                with _c2:
                    st.markdown(
                        f"<div style='color:#6b7280;font-size:13px;"
                        f"text-align:center'>{_date}</div>",
                        unsafe_allow_html=True)
                with _c3:
                    st.button("View", key=f"demo_view_{_fname}", width=150)
    _uploader()
    st.info("Only you can see these CVs and matches — they are private to "
            "your account (SRS-086, SRS-087).")


def screen_u15():
    """URS-015 — Log out (SRS-088)."""
    _user_header()
    _uploader()
    # profile popover contents (matches the real popover: name/email + 3 actions)
    with st.container(border=True):
        st.markdown("**alice_j**")
        st.markdown(
            "<div style='color:#6b7280;font-size:12px'>alice@example.com</div>",
            unsafe_allow_html=True)
        st.divider()
        st.button("✏️ Change name", key="demo_acct_change_name",
                  use_container_width=True)
        st.button("🔑 Change password", key="demo_acct_change_pw",
                  use_container_width=True)
        st.divider()
        st.button("🚪 Log out", key="demo_jobseeker_logout",
                  type="primary", use_container_width=True)
    st.success("Logging out clears your session token — you will need to log "
               "in again (SRS-088).")


def screen_u16():
    """URS-016 — Change / reset password (SRS-089, SRS-090)."""
    _user_header()
    _uploader()

    def _card():
        _auth_brand("Change password",
                    "Use at least 8 characters, different from the old one.")
        with st.form("demo_change_pw"):
            st.text_input("Current password", type="password",
                          placeholder="Current password")
            st.text_input("New password", type="password",
                          placeholder="New password")
            st.text_input("Confirm new password", type="password",
                          placeholder="Repeat new password")
            st.form_submit_button("Change password", type="primary")
        st.divider()
        _auth_brand("Reset password",
                    "Enter your account details to set a new password.")
        with st.form("demo_forgot_pw"):
            st.text_input("Username", placeholder="Your username")
            st.text_input("Account email", placeholder="you@example.com")
            st.text_input("New password", type="password",
                          placeholder="At least 8 characters")
            st.text_input("Confirm new password", type="password",
                          placeholder="Repeat new password")
            st.form_submit_button("Reset password")
        st.button("← Back to Log In", key="demo_back_to_login",
                  type="tertiary", use_container_width=True)

    _centered(_card)


def screen_u17():
    """URS-017 — Change username (SRS-091)."""
    _user_header()
    _uploader()

    def _card():
        _auth_brand("Edit profile",
                    "Change how your name appears on CVision.")
        with st.form("demo_change_name"):
            st.text_input("Display name", value="alice_j",
                          placeholder="e.g. alice_j",
                          help="3-30 characters: letters, digits, _ . -")
            st.form_submit_button("Save changes", type="primary")

    _centered(_card)


# =========================================================================
# Dispatch
# =========================================================================
_SCREEN = {
    "URS-010": screen_u10,
    "URS-011": screen_u11,
    "URS-012": screen_u12,
    "URS-013": screen_u13,
    "URS-014": screen_u14,
    "URS-015": screen_u15,
    "URS-016": screen_u16,
    "URS-017": screen_u17,
}

_screen_fn = _SCREEN.get(st.session_state.urs_demo)
if _screen_fn:
    _screen_fn()
