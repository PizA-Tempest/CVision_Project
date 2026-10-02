"""
auth_service.py — Feature #5: Authentication.

Owns Jobseeker registration / login and Administrator credential
verification. Streamlit pages (app.py, admin.py) call into this module;
no Streamlit calls live here so it stays directly testable.

URS coverage:
  URS-010 / SRS-063,069 — unique username+email, inline duplicate check
  URS-011 / SRS-064,070,071 — jobseeker login by username OR email,
      separate admin verification
  URS-012 / SRS-072 — salted password hashes, never plaintext
  URS-013 / SRS-073 — server-side upload guard (rejects unauthenticated)
  URS-014 / SRS-074 — ownership helpers live in cv_data_adapter; the
      jobseeker id produced here is what callers store/filter on
  URS-015 / SRS-075 — admin session is independent of jobseeker session
  URS-016 / SRS-076 — logout is done by callers clearing session state

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

MIN_PASSWORD_LEN = 6


class AuthValidationException(ValueError):
    """Registration input failed validation (missing/bad format)."""


class UsernameTakenException(AuthValidationException):
    """Username already exists (SRS-069)."""


class EmailTakenException(AuthValidationException):
    """Email already exists (SRS-069)."""


class UnauthenticatedUploadException(PermissionError):
    """CV upload attempted without a valid Jobseeker session (SRS-073)."""


# ---------------------------------------------------------------------
# Hashing (SRS-072)
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
            created_at    DATETIME(3)  NULL
        ) ENGINE=InnoDB
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_session (
            token        VARCHAR(128) NOT NULL PRIMARY KEY,
            jobseeker_id VARCHAR(36)  NULL,
            admin_id     VARCHAR(36)  NULL,
            created_at   DATETIME(3)  NULL,
            expires_at   DATETIME(3)  NOT NULL,
            KEY idx_auth_js (jobseeker_id),
            KEY idx_auth_admin (admin_id)
        ) ENGINE=InnoDB
        """
    )


# ---------------------------------------------------------------------
# Validation + availability (SRS-063, SRS-069)
# ---------------------------------------------------------------------

def _clean_username(username: str | None) -> str:
    return (username or "").strip()


def _clean_email(email: str | None) -> str:
    return (email or "").strip().lower()


def validate_registration(username: str, email: str, password: str) -> tuple[str, str]:
    """Validate format only (no DB). Returns cleaned (username, email)."""
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
    if not _EMAIL_RE.match(email):
        raise AuthValidationException("Enter a valid email address.")
    if not password:
        raise AuthValidationException("Password is required.")
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthValidationException(
            f"Password must be at least {MIN_PASSWORD_LEN} characters."
        )
    return username, email


def is_username_taken(username: str) -> bool:
    """Inline duplicate check for the registration form (SRS-063)."""
    username = _clean_username(username)
    if not username:
        return False
    rows = db.query("SELECT id FROM jobseeker WHERE username = %s", (username,))
    return bool(rows)


def is_email_taken(email: str) -> bool:
    """Inline duplicate check for the registration form (SRS-063)."""
    email = _clean_email(email)
    if not email:
        return False
    rows = db.query("SELECT id FROM jobseeker WHERE email = %s", (email,))
    return bool(rows)


# ---------------------------------------------------------------------
# Jobseeker (URS-010, URS-011)
# ---------------------------------------------------------------------

def register_jobseeker(username: str, email: str, password: str) -> dict:
    """Create a Jobseeker account (SRS-069, SRS-072).

    Checks uniqueness before inserting and stores only a salted hash.
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
    """Login with username OR email in one field (SRS-064, SRS-070).

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
    """Server-side upload guard (SRS-073). Raises unless authenticated."""
    if not jobseeker_id:
        raise UnauthenticatedUploadException(
            "Log in to upload a CV."
        )
    return str(jobseeker_id)


def _validate_new_password(password: str) -> None:
    if not password or len(password) < MIN_PASSWORD_LEN:
        raise AuthValidationException(
            f"Password must be at least {MIN_PASSWORD_LEN} characters."
        )


def change_jobseeker_password(jobseeker_id: str, current_password: str,
                              new_password: str) -> None:
    """Change password for a signed-in Jobseeker.

    Verifies the current password against the stored hash, then stores
    only the new salted hash. Raises AuthValidationException on wrong
    current password or weak new password.
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
    """Change the display name (username) for a signed-in Jobseeker.

    Validates format with the same rule as registration, rejects a
    duplicate, then updates the row. Returns {id, username, email}.
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


def reset_jobseeker_password(username: str, email: str, new_password: str) -> dict:
    """Forgot-password reset without an email server.

    The username AND email must both match the same account (identity
    check in place of an emailed token — note in production this should
    be an emailed reset link). Stores only the new salted hash.
    Returns {id, username, email}. Raises AuthValidationException.
    """
    username = _clean_username(username)
    email = _clean_email(email)
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
    """Verify admin credentials against the stored hash (SRS-071, SRS-072).

    Accepts legacy plaintext rows once and upgrades them to a salted hash.
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
