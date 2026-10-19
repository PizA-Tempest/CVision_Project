"""
auth_service.py — Feature #5: Authentication.

Owns Jobseeker registration / login and Administrator credential
verification. Streamlit pages (app.py, admin.py) call into this module;
no Streamlit calls live here so it stays directly testable.

URS coverage (URS Feature#5.md — SRS-077..091):
  URS-010 / SRS-077,078 — validate registration format before duplicate
      check; unique username+email with inline error, no submit
  URS-011 / SRS-079,080,081 — dedicated admin login verified independently;
      jobseeker login by username OR email; Log in/Sign up replaced by
      profile popover (display name, email, Change name, Change password,
      Log out)
  URS-012 / SRS-082,083 — salted password hashes only, never plaintext;
      constant-time verify with generic failure
  URS-013 / SRS-084,085 — guest sees upload section but picking a file
      opens login/register popup and discards it; server rejects uploads
      without a valid Jobseeker session
  URS-014 / SRS-086,087 — "My CVs" shows only the owner's CVs, newest
      first, max 20, parsed only; every upload records the Jobseeker ID as
      owner and foreign CV IDs are rejected (ownership helpers live in
      cv_data_adapter; the jobseeker id produced here is what callers
      store/filter on)
  URS-015 / SRS-088 — logout ends the session and clears session state
  URS-016 / SRS-089,090 — signed-in password change (current + new 8-64,
      blocklisted, different); forgotten-password reset (username + matching
      email + new-password confirmation)
  URS-017 / SRS-091 — signed-in username change via "Change name" (same
      rule as registration, no duplicates, session display updates
      immediately; unchanged name succeeds without a DB write)

Hashing uses only the standard library (hashlib.pbkdf2_hmac + secrets)
so no new dependency is needed. Stored format:

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

Admin passwords seeded by 2_data.sql are legacy plaintext ("123").
authenticate_admin() accepts them once and transparently upgrades the
row to a salted hash, so existing installs keep working.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timezone

import db

_HASH_PREFIX = "pbkdf2_sha256"
_ITERATIONS = 260_000
_SALT_BYTES = 16

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,30}$")

# Password policy (URS Feature#5.md):
# SRS-077 (registration): 8-64 chars, length only — no blocklist, no forced
#   complexity mix.
# SRS-089/SRS-090 (change/reset new password): 8-64 chars + blocklist
#   (NIST SP 800-63B style) + must differ from the old one on change.
# The 64-char cap also bounds hashing cost and matches the DB column.
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 64
MAX_EMAIL_LEN = 255

COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "12345678", "123456789",
    "1234567890", "qwerty", "qwerty123", "abc123", "11111111",
    "123123123", "letmein", "welcome", "welcome1", "admin123",
    "iloveyou", "monkey", "dragon", "football", "baseball",
    "superman", "trustno1", "master", "shadow", "sunshine",
    "princess", "qazwsx", "password12", "changeme", "cvision",
    "cvision123",
})


def check_password_policy(password: str) -> None:
    """Enforce the change/reset new-password policy (SRS-089, SRS-090).

    8-64 chars, not on the blocklist. Raises AuthValidationException.
    """
    if not password:
        raise AuthValidationException("Password is required.")
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthValidationException(
            f"Password must be at least {MIN_PASSWORD_LEN} characters."
        )
    if len(password) > MAX_PASSWORD_LEN:
        raise AuthValidationException(
            f"Password must be at most {MAX_PASSWORD_LEN} characters."
        )
    if password.strip().lower() in COMMON_PASSWORDS:
        raise AuthValidationException(
            "That password is too common — pick a less predictable one."
        )


def check_registration_password(password: str) -> None:
    """Enforce the registration password rule (SRS-077): 8-64 chars only.

    Deliberately no blocklist here — SRS-077 specifies length only, while
    the blocklist applies to change/reset new passwords (SRS-089, SRS-090).
    Raises AuthValidationException.
    """
    if not password:
        raise AuthValidationException("Password is required.")
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthValidationException(
            f"Password must be at least {MIN_PASSWORD_LEN} characters."
        )
    if len(password) > MAX_PASSWORD_LEN:
        raise AuthValidationException(
            f"Password must be at most {MAX_PASSWORD_LEN} characters."
        )


class AuthValidationException(ValueError):
    """Registration input failed validation (missing/bad format)."""


class UsernameTakenException(AuthValidationException):
    """Username already exists (SRS-078)."""


class EmailTakenException(AuthValidationException):
    """Email already exists (SRS-078)."""


class UnauthenticatedUploadException(PermissionError):
    """CV upload attempted without a valid Jobseeker session (SRS-085)."""


# ---------------------------------------------------------------------
# Hashing (SRS-082)
# ---------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with a random salt. Never returns plaintext."""
    if not password:
        raise AuthValidationException("Password is required.")
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_HASH_PREFIX}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def _is_hash_format(stored: str | None) -> bool:
    return bool(stored) and stored.startswith(_HASH_PREFIX + "$")


def verify_password(password: str, stored: str | None) -> bool:
    """Compare a plaintext candidate against a stored salted hash.

    Uses secrets.compare_digest so timing does not leak prefix matches.
    Returns False (never raises) for missing/legacy values — legacy admin
    rows are handled by authenticate_admin(), not here.
    """
    if not password or not _is_hash_format(stored):
        return False
    try:
        _, iter_s, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), int(iter_s),
        )
        return secrets.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------

def ensure_auth_tables() -> None:
    """Create the jobseeker table if it does not exist yet.

    Safe to call on every startup (Streamlit Cloud has no migration step).
    The admin table already exists; its passwords are upgraded lazily.
    Also creates auth_session, which holds the persistent login tokens
    that survive a browser refresh (Streamlit's session_state does not —
    a refresh starts a new session and clears it).
    """
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS jobseeker (
            id            VARCHAR(36)  NOT NULL PRIMARY KEY,
            username      VARCHAR(100) NOT NULL UNIQUE,
            email         VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at    TIMESTAMPTZ  NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_session (
            token        VARCHAR(128) NOT NULL PRIMARY KEY,
            jobseeker_id VARCHAR(36)  NULL,
            admin_id     VARCHAR(36)  NULL,
            created_at   TIMESTAMPTZ  NULL,
            expires_at   TIMESTAMPTZ  NOT NULL
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_js ON auth_session (jobseeker_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_admin ON auth_session (admin_id)"
    )


# ---------------------------------------------------------------------
# Validation + availability (SRS-077, SRS-078)
# ---------------------------------------------------------------------

def _clean_username(username: str | None) -> str:
    return (username or "").strip()


def _clean_email(email: str | None) -> str:
    return (email or "").strip().lower()


def validate_registration(username: str, email: str, password: str) -> tuple[str, str]:
    """Validate registration format only, before any duplicate check (SRS-077).

    Username 3-30 chars [A-Za-z0-9_.-], email standard format max 255
    chars, password 8-64 chars. Returns cleaned (username, email).
    """
    username = _clean_username(username)
    email = _clean_email(email)
    if not username:
        raise AuthValidationException("Username is required.")
    if not _USERNAME_RE.match(username):
        raise AuthValidationException(
            "Username must be 3-30 characters: letters, digits, _ . -"
        )
    if not email:
        raise AuthValidationException("Email is required.")
    if len(email) > MAX_EMAIL_LEN:
        raise AuthValidationException("Email must be at most 255 characters.")
    if not _EMAIL_RE.match(email):
        raise AuthValidationException("Enter a valid email address.")
    check_registration_password(password)
    return username, email


def is_username_taken(username: str) -> bool:
    """Inline duplicate check for the registration form (SRS-078)."""
    username = _clean_username(username)
    if not username:
        return False
    rows = db.query("SELECT id FROM jobseeker WHERE username = %s", (username,))
    return bool(rows)


def is_email_taken(email: str) -> bool:
    """Inline duplicate check for the registration form (SRS-078)."""
    email = _clean_email(email)
    if not email:
        return False
    rows = db.query("SELECT id FROM jobseeker WHERE email = %s", (email,))
    return bool(rows)


# ---------------------------------------------------------------------
# Jobseeker (URS-010, URS-011)
# ---------------------------------------------------------------------

def register_jobseeker(username: str, email: str, password: str) -> dict:
    """Create a Jobseeker account (SRS-077, SRS-078, SRS-082).

    Validates format first, then checks username/email uniqueness before
    inserting, and stores only a salted hash.
    Raises UsernameTakenException / EmailTakenException / AuthValidationException.
    Never stores or logs the plaintext password.
    """
    username, email = validate_registration(username, email, password)
    if is_username_taken(username):
        raise UsernameTakenException("That username is already registered.")
    if is_email_taken(email):
        raise EmailTakenException("That email is already registered.")
    jobseeker_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO jobseeker (id, username, email, password_hash, created_at)"
        " VALUES (%s, %s, %s, %s, %s)",
        (jobseeker_id, username, email, hash_password(password),
         datetime.now(timezone.utc)),
    )
    return {"id": jobseeker_id, "username": username, "email": email}


def authenticate_jobseeker(identifier: str, password: str) -> dict | None:
    """Login with username OR email in one field (SRS-080, SRS-083).

    Matches the identifier then verifies against the stored hash with
    constant-time comparison; returns a generic None on any failure with
    no account-enumeration detail.
    Returns {id, username, email} on success, None on failure.
    """
    identifier = (identifier or "").strip()
    if not identifier or not password:
        return None
    if "@" in identifier:
        rows = db.query(
            "SELECT id, username, email, password_hash FROM jobseeker"
            " WHERE email = %s",
            (_clean_email(identifier),),
        )
    else:
        rows = db.query(
            "SELECT id, username, email, password_hash FROM jobseeker"
            " WHERE username = %s",
            (_clean_username(identifier),),
        )
    if not rows:
        return None
    row = rows[0]
    if not verify_password(password, row.get("password_hash")):
        return None
    return {"id": row["id"], "username": row["username"], "email": row["email"]}


def get_jobseeker_by_id(jobseeker_id: str) -> dict | None:
    """Fetch a Jobseeker by id (session restore)."""
    if not jobseeker_id:
        return None
    rows = db.query(
        "SELECT id, username, email FROM jobseeker WHERE id = %s",
        (str(jobseeker_id),),
    )
    return dict(rows[0]) if rows else None


def require_jobseeker(jobseeker_id: str | None) -> str:
    """Server-side upload guard (SRS-085). Raises unless authenticated."""
    if not jobseeker_id:
        raise UnauthenticatedUploadException(
            "Log in to upload a CV."
        )
    return str(jobseeker_id)


def _validate_new_password(password: str) -> None:
    check_password_policy(password)


def change_jobseeker_password(jobseeker_id: str, current_password: str,
                              new_password: str) -> None:
    """Change password for a signed-in Jobseeker (SRS-089, SRS-082, SRS-083).

    Verifies the current password against the stored hash, rejects a new
    password outside 8-64 chars, on the blocklist, or the same as the old
    one, then stores only the new salted hash. Wrong current password
    yields a generic failure and changes nothing.
    Raises AuthValidationException on any violation.
    """
    if not jobseeker_id:
        raise AuthValidationException("Not signed in.")
    _validate_new_password(new_password)
    if current_password == new_password:
        raise AuthValidationException("New password must differ from the old one.")
    rows = db.query(
        "SELECT id, password_hash FROM jobseeker WHERE id = %s",
        (str(jobseeker_id),),
    )
    if not rows:
        raise AuthValidationException("Account not found.")
    if not verify_password(current_password or "", rows[0].get("password_hash")):
        raise AuthValidationException("Current password is incorrect.")
    db.execute(
        "UPDATE jobseeker SET password_hash = %s WHERE id = %s",
        (hash_password(new_password), str(jobseeker_id)),
    )


def change_jobseeker_username(jobseeker_id: str, new_username: str) -> dict:
    """Change the display name (username) for a signed-in Jobseeker (SRS-091).

    Follows the registration rule (3-30 chars [A-Za-z0-9_.-]), must not
    duplicate another account; submitting the current unchanged username
    succeeds without a DB write and returns the existing account. The
    caller updates the session display name immediately on success.
    Returns {id, username, email}.
    Raises AuthValidationException / UsernameTakenException.
    """
    if not jobseeker_id:
        raise AuthValidationException("Not signed in.")
    cleaned = _clean_username(new_username)
    if not cleaned:
        raise AuthValidationException("Username is required.")
    if not _USERNAME_RE.match(cleaned):
        raise AuthValidationException(
            "Username must be 3-30 characters: letters, digits, _ . -"
        )
    rows = db.query(
        "SELECT id, username, email FROM jobseeker WHERE id = %s",
        (str(jobseeker_id),),
    )
    if not rows:
        raise AuthValidationException("Account not found.")
    current = rows[0].get("username") or ""
    if cleaned == current:
        return {"id": rows[0]["id"], "username": current,
                "email": rows[0].get("email")}
    if is_username_taken(cleaned):
        raise UsernameTakenException("That username is already registered.")
    db.execute(
        "UPDATE jobseeker SET username = %s WHERE id = %s",
        (cleaned, str(jobseeker_id)),
    )
    return {"id": rows[0]["id"], "username": cleaned,
            "email": rows[0].get("email")}


def reset_jobseeker_password(username: str, email: str, new_password: str,
                               new_password_confirmation: str | None = None) -> dict:
    """Forgot-password reset without an email server (SRS-090, SRS-082).

    The username AND matching account email must both match the same
    account, plus new-password confirmation that must match new_password.
    On success stores only the new salted hash; on mismatch shows a
    generic failure and changes nothing.
    Returns {id, username, email}. Raises AuthValidationException.
    """
    username = _clean_username(username)
    email = _clean_email(email)
    if new_password_confirmation is None:
        raise AuthValidationException("Password confirmation is required.")
    if new_password != new_password_confirmation:
        raise AuthValidationException("New passwords do not match.")
    _validate_new_password(new_password)
    if not username or not email:
        raise AuthValidationException("Username and email are both required.")
    rows = db.query(
        "SELECT id, username, email FROM jobseeker WHERE username = %s",
        (username,),
    )
    if not rows or _clean_email(rows[0].get("email")) != email:
        raise AuthValidationException(
            "No account matches that username and email."
        )
    db.execute(
        "UPDATE jobseeker SET password_hash = %s WHERE id = %s",
        (hash_password(new_password), rows[0]["id"]),
    )
    return {"id": rows[0]["id"], "username": rows[0]["username"],
            "email": rows[0]["email"]}


# ---------------------------------------------------------------------
# Administrator (URS-011, URS-015)
# ---------------------------------------------------------------------

def authenticate_admin(username: str, password: str) -> dict | None:
    """Verify admin credentials against the stored hash (SRS-079, SRS-080, SRS-082, SRS-083).

    Independent of any Jobseeker credentials, using constant-time
    comparison with a generic None on failure. Accepts legacy plaintext
    rows once and upgrades them to a salted hash.
    Returns {id, username} on success, None on failure.
    """
    username = (username or "").strip()
    if not username or not password:
        return None
    rows = db.query(
        "SELECT id, username, password FROM admin WHERE username = %s",
        (username,),
    )
    if not rows:
        return None
    row = rows[0]
    stored = row.get("password")
    if _is_hash_format(stored):
        if not verify_password(password, stored):
            return None
    else:
        # Legacy plaintext seed ("123"). Constant-time compare, then upgrade.
        if not secrets.compare_digest(str(stored or ""), password):
            return None
        try:
            db.execute(
                "UPDATE admin SET password = %s WHERE id = %s",
                (hash_password(password), row.get("id")),
            )
        except Exception:
            pass  # login still succeeds; upgrade is best-effort
    return {"id": row.get("id"), "username": row.get("username")}


# ---------------------------------------------------------------------
# Persistent sessions (survive browser refresh)
# ---------------------------------------------------------------------
# Streamlit's session_state is tied to the websocket connection: a
# browser refresh starts a new session and clears it, logging the user
# out. The fix is a random token stored server-side (this table) and
# echoed in the URL query params (which the browser keeps on refresh).
# On startup each page validates the token from the URL and restores
# the session. Tokens expire after 30 days; logout deletes them.

SESSION_DAYS = 30
JOBSEEKER_TOKEN_PARAM = "auth_token"
ADMIN_TOKEN_PARAM = "admin_token"


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _session_expiry() -> datetime:
    from datetime import timedelta
    return datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)


def create_jobseeker_session(jobseeker_id: str) -> str:
    """Mint a persistent login token for a Jobseeker. Returns the token."""
    try:
        ensure_auth_tables()
    except Exception:
        pass
    token = _new_token()
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO auth_session (token, jobseeker_id, admin_id,"
        " created_at, expires_at) VALUES (%s, %s, NULL, %s, %s)",
        (token, str(jobseeker_id), now, _session_expiry()),
    )
    return token


def create_admin_session(admin_id: str) -> str:
    """Mint a persistent login token for an Administrator. Returns the token."""
    try:
        ensure_auth_tables()
    except Exception:
        pass
    token = _new_token()
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO auth_session (token, jobseeker_id, admin_id,"
        " created_at, expires_at) VALUES (%s, NULL, %s, %s, %s)",
        (token, str(admin_id), now, _session_expiry()),
    )
    return token


def get_jobseeker_by_session(token: str | None) -> dict | None:
    """Validate a jobseeker token; return {id, username, email} or None.

    Expired/unknown tokens return None (and the expired row is removed
    best-effort so the table does not fill with dead tokens).
    """
    if not token:
        return None
    try:
        rows = db.query(
            "SELECT s.jobseeker_id, s.expires_at,"
            " j.username, j.email FROM auth_session s"
            " LEFT JOIN jobseeker j ON j.id = s.jobseeker_id"
            " WHERE s.token = %s AND s.jobseeker_id IS NOT NULL",
            (str(token),),
        )
    except Exception:
        return None
    if not rows:
        return None
    row = rows[0]
    try:
        exp = row.get("expires_at")
        if exp is not None:
            if getattr(exp, "tzinfo", None) is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                try:
                    db.execute(
                        "DELETE FROM auth_session WHERE token = %s",
                        (str(token),),
                    )
                except Exception:
                    pass
                return None
    except Exception:
        pass
    if not row.get("jobseeker_id") or not row.get("username"):
        return None
    return {"id": row["jobseeker_id"],
            "username": row["username"], "email": row.get("email")}


def get_admin_by_session(token: str | None) -> dict | None:
    """Validate an admin token; return {id, username} or None."""
    if not token:
        return None
    try:
        rows = db.query(
            "SELECT s.admin_id, s.expires_at,"
            " a.username FROM auth_session s"
            " LEFT JOIN admin a ON a.id = s.admin_id"
            " WHERE s.token = %s AND s.admin_id IS NOT NULL",
            (str(token),),
        )
    except Exception:
        return None
    if not rows:
        return None
    row = rows[0]
    try:
        exp = row.get("expires_at")
        if exp is not None:
            if getattr(exp, "tzinfo", None) is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                try:
                    db.execute(
                        "DELETE FROM auth_session WHERE token = %s",
                        (str(token),),
                    )
                except Exception:
                    pass
                return None
    except Exception:
        pass
    if not row.get("admin_id") or not row.get("username"):
        return None
    return {"id": row.get("admin_id"), "username": row.get("username")}


def delete_session(token: str | None) -> None:
    """Remove a session token (logout). Never raises."""
    if not token:
        return
    try:
        db.execute("DELETE FROM auth_session WHERE token = %s", (str(token),))
    except Exception:
        pass
