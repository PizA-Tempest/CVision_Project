"""
db.py — Storage Layer

Shared PostgreSQL (Supabase) connection pooling and transaction handling
used by scraper_service.py, job_service.py and log_service.py. This is the
only module in CVision that opens connections and commits — every
service module goes through query() / execute() / transaction() below
rather than connecting for itself.

Two calls come from admin.py rather than a service, against File
Structure's line that db.py is used by the three services: the login
lookup against the Admin table (no service owns Admin — authentication
is Feature #5, outside this refactor) and the Log tab's read of
log_entry (kept in preference to adding an undocumented
log_service.get_recent_logs() wrapper, since query() is already
M-030). Both are recorded in TBD_and_Conflicts.md.

Implements M-029 (get_connection), M-030 (query), M-031 (execute),
and M-032 (transaction) from the Method Description.

Connection settings are read from environment variables so credentials
never live in source. Prefer DATABASE_URL (the Supabase connection
string); the DB_* variables remain as a fallback:

    DATABASE_URL   postgresql://user:pass@host:5432/dbname?sslmode=require
    DB_HOST        default "localhost"
    DB_PORT        default "5432"
    DB_USER        default "postgres"
    DB_PASSWORD    default ""
    DB_NAME        default "cvision"
    DB_POOL_SIZE   default "5"
"""

import os
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

# Loaded here, at import, rather than by each entry point.
#
# Every module that reaches the database imports this one, so doing it here
# means the settings are in place before any caller can possibly connect.
# Leaving it to callers was a real bug: enrich_jobs.py called fetch_listings()
# — a database read — before its own load_dotenv(), and verify_integration.py
# tested the connection thousands of characters before loading .env. Both
# failed with "Unable to connect to the database." on a perfectly healthy
# database, because DB_PASSWORD had not been read yet.
#
# Optional: a deployment that sets real environment variables needs no .env,
# and python-dotenv never overrides variables that are already set.
try:
    from dotenv import load_dotenv
    from pathlib import Path as _Path
    load_dotenv(_Path(__file__).resolve().parent / ".env")
except ImportError:
    pass


class DatabaseError(Exception):
    """Raised whenever a database operation cannot be completed —
    connection unreachable, credentials rejected, a statement is
    rejected, or a commit/rollback fails.

    The message is the fixed text the Method Description's test cases
    specify, so it carries no detail about what actually went wrong. The
    driver's own error is preserved twice over: as this exception's
    __cause__, and as its `detail` attribute, which also names the settings
    that were in effect. Callers that report to a developer rather than an
    end user should show one of them — "Unable to connect to the database"
    on its own gives no way to tell a wrong password from a stopped server.
    """

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail


_POOL_NAME = "cvision_pool"
_pool = None
_pool_lock = threading.Lock()


def describe_settings():
    """
    The connection settings in effect, for error messages. Reports whether a
    password is set, never its value. When DATABASE_URL is present only the
    host/port/database portion is shown.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        safe = url
        if "@" in url and "://" in url:
            prefix, rest = url.split("://", 1)
            if "@" in rest:
                creds, hostpart = rest.rsplit("@", 1)
                user = creds.split(":", 1)[0]
                safe = f"{prefix}://{user}:***@{hostpart}"
        return f"url={safe}"
    return (f"host={os.environ.get('DB_HOST', 'localhost')} "
            f"port={os.environ.get('DB_PORT', '5432')} "
            f"user={os.environ.get('DB_USER', 'postgres')} "
            f"database={os.environ.get('DB_NAME', 'cvision')} "
            f"password={'set' if os.environ.get('DB_PASSWORD') else 'NOT SET'}")


def _dsn():
    """Build the connection DSN. DATABASE_URL wins when set (Supabase)."""
    url = os.environ.get("DATABASE_URL")
    if url:
        if "sslmode=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}sslmode=require"
        return url
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "")
    dbname = os.environ.get("DB_NAME", "cvision")
    sslmode = os.environ.get("DB_SSLMODE", "prefer")
    return (f"host={host} port={port} user={user} "
            f"password={password} dbname={dbname} sslmode={sslmode}")


def get_connection():
    """
    M-029 — Opens, or reuses, the pooled PostgreSQL connection shared by
    every service module.

    The pool itself is created once per process, the first time any
    service module needs it. Every call after that — from
    scraper_service.py, job_service.py, log_service.py, or from
    query()/execute()/transaction() below — hands out a free
    connection from that same pool instead of opening a new one.

    Callers are responsible for closing what they get back (query()
    and execute() already do this); closing a pooled connection
    returns it to the pool rather than dropping it.

    Throws:
        DatabaseError — "Unable to connect to the database." when the
        database is unreachable or the configured credentials are
        rejected (UT-1-29-003). The driver's own error is kept as the
        exception's __cause__ for debugging, but the message itself is
        the exact text the test case specifies.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                try:
                    _pool = pg_pool.ThreadedConnectionPool(
                        1,
                        int(os.environ.get("DB_POOL_SIZE", "5")),
                        dsn=_dsn(),
                    )
                except psycopg2.Error as ex:
                    raise DatabaseError(
                        "Unable to connect to the database.",
                        detail=f"{ex}  [{describe_settings()}]",
                    ) from ex
    try:
        return _pool.getconn()
    except psycopg2.Error as ex:
        raise DatabaseError(
            "Unable to connect to the database.",
            detail=f"{ex}  [{describe_settings()}]",
        ) from ex


def _putconn(conn, close=False):
    if _pool is not None and conn is not None:
        try:
            _pool.putconn(conn, close=close)
        except Exception:
            pass


def query(sql, params=()):
    """
    M-030 — Runs a SELECT statement and returns the resulting rows.
    The single read path used by every service module.

    Parameters:
        sql: str — SELECT statement, with %s placeholders in place
             of literal values.
        params: tuple — values bound to those placeholders.

    Returns:
        list[dict] — the matching rows; [] when nothing matches.

    Throws:
        DatabaseError — "Unable to read from the database." when the
        statement is rejected or the connection is lost mid-query
        (UT-1-30-003). Driver detail is preserved as __cause__.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            cursor.close()
    except psycopg2.Error as ex:
        conn.rollback()
        raise DatabaseError("Unable to read from the database.", detail=str(ex)) from ex
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        _putconn(conn)


def execute(sql, params=()):
    """
    M-031 — Runs an INSERT, UPDATE or DELETE statement and returns
    the number of affected rows. The single write path used by every
    service module for single-statement writes.

    Parameters:
        sql: str — the statement to run, with %s placeholders in
             place of literal values.
        params: tuple — values bound to those placeholders.

    Returns:
        int — rows inserted, updated, or deleted.

    Throws:
        DatabaseError — the statement violates a constraint, or the
        write cannot be committed.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
    except psycopg2.Error as ex:
        conn.rollback()
        raise DatabaseError(f"Write failed: {ex}") from ex
    finally:
        _putconn(conn)


@contextmanager
def transaction():
    """
    M-032 — Groups several writes into a single commit, rolling the
    whole group back if any one of them fails.

    Used by scraper_service.execute() (M-009) so a fetch run's
    inserted job listings and updated scraper.last_request_date
    either both persist, or neither does.

    Usage:
        with db.transaction() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO job_listing (...) VALUES (...)", params)
            cur.execute("UPDATE scraper SET last_request_date = %s WHERE id = %s", params)
        # commits automatically on clean exit; rolls back on any exception

    Throws:
        DatabaseError — the transaction cannot be committed; the
        whole group is rolled back and no partial write survives.
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as ex:
        conn.rollback()
        raise DatabaseError(f"Transaction failed and was rolled back: {ex}") from ex
    finally:
        _putconn(conn)
