"""
db.py — Storage Layer

Shared MySQL connection pooling and transaction handling used by
scraper_service.py, job_service.py and log_service.py. This is the
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
never live in source:
    DB_HOST      default "localhost"
    DB_PORT      default "3306"
    DB_USER      default "root"
    DB_PASSWORD  default ""
    DB_NAME      default "cvision"
    DB_POOL_SIZE default "5"
"""

import os
import threading
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling

# Loaded here, at import, rather than by each entry point.
#
# Every module that reaches the database imports this one, so doing it here
# means the settings are in place before any caller can possibly connect.
# Leaving it to callers was a real bug: enrich_jobs.py called fetch_listings()
# — a database read — before its own load_dotenv(), and verify_integration.py
# tested the connection thousands of characters before loading .env. Both
# failed with "Unable to connect to the database." on a perfectly healthy
# MySQL, because DB_PASSWORD had not been read yet.
#
# Optional: a deployment that sets real environment variables needs no .env,
# and python-dotenv never overrides variables that are already set.
try:
    from dotenv import load_dotenv
    load_dotenv()
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
    password is set, never its value.
    """
    return (f"host={os.environ.get('DB_HOST', 'localhost')} "
            f"port={os.environ.get('DB_PORT', '3306')} "
            f"user={os.environ.get('DB_USER', 'root')} "
            f"database={os.environ.get('DB_NAME', 'cvision')} "
            f"password={'set' if os.environ.get('DB_PASSWORD') else 'NOT SET'}")


def _pool_config():
    return {
        "pool_name": _POOL_NAME,
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "cvision"),
        "autocommit": False,
    }


def get_connection():
    """
    M-029 — Opens, or reuses, the pooled MySQL connection shared by
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
                    _pool = pooling.MySQLConnectionPool(**_pool_config())
                except mysql.connector.Error as ex:
                    raise DatabaseError(
                        "Unable to connect to the database.",
                        detail=f"{ex}  [{describe_settings()}]",
                    ) from ex
    try:
        return _pool.get_connection()
    except mysql.connector.Error as ex:
        raise DatabaseError(
            "Unable to connect to the database.",
            detail=f"{ex}  [{describe_settings()}]",
        ) from ex


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
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            cursor.close()
    except mysql.connector.Error as ex:
        raise DatabaseError("Unable to read from the database.", detail=str(ex)) from ex
    finally:
        conn.close()  # returns the connection to the pool


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
    except mysql.connector.Error as ex:
        conn.rollback()
        raise DatabaseError(f"Write failed: {ex}") from ex
    finally:
        conn.close()


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
        conn.close()