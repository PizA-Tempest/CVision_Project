"""Unit test runner for Feature #5 Authentication (UT-5-01 .. UT-5-22, 99 records).

Executes every record in Feature_5_Unit_Test_Record.md against the real
implementation (auth_service, cv_data_adapter, app._pw_strength extracted
without importing streamlit UI). DB fixtures use the ut5_ prefix and are
deleted afterwards; cvs.json is backed up and restored.

Run:  py tests/run_unit_tests_f5.py
Output: tests/test_results_UT5_<date>.json/.md
"""
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, ROOT)

import db
import auth_service
import cv_data_adapter
import cv_upload

REGISTRY = os.path.abspath(cv_upload.CVS_REGISTRY_FILE)
BACKUP = REGISTRY + ".ut5-backup"

results = []


def emit(rid, passed, actual):
    results.append({"test_id": rid, "result": "PASS" if passed else "FAIL", "actual": actual})
    print(f"[{rid}] {'PASS' if passed else 'FAIL'}  {actual}", flush=True)


def load_registry():
    try:
        with open(REGISTRY, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_registry(records):
    with open(REGISTRY, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def get_pw_hash(jid):
    rows = db.query("SELECT password_hash FROM jobseeker WHERE id = %s", (jid,))
    return rows[0]["password_hash"] if rows else None


def cleanup():
    for u in ["ut5_user1", "ut5_auth", "ut5_reg1", "ut5_pw", "ut5_rst",
              "ut5_nm", "ut5_nm2", "ut5_dup", "ut5_sess", "ut5_list", "ut5_other"]:
        try:
            rows = db.query("SELECT id FROM jobseeker WHERE username = %s", (u,))
            for r in rows:
                jid = r["id"]
                for sql in ("DELETE FROM jobseeker_cv WHERE jobseeker_id = %s",
                            "DELETE FROM auth_session WHERE jobseeker_id = %s",
                            "DELETE FROM jobseeker WHERE id = %s"):
                    try:
                        db.execute(sql, (jid,))
                    except Exception:
                        pass
        except Exception:
            pass
    for em in ["ut5_user1@example.com", "ut5_auth@example.com", "ut5_reg1@example.com",
               "ut5_taken@example.com", "ut5_dup@example.com"]:
        try:
            rows = db.query("SELECT id, username FROM jobseeker WHERE email = %s", (em,))
            for r in rows:
                if (r.get("username") or "").startswith("ut5_"):
                    jid = r["id"]
                    for sql in ("DELETE FROM jobseeker_cv WHERE jobseeker_id = %s",
                                "DELETE FROM auth_session WHERE jobseeker_id = %s",
                                "DELETE FROM jobseeker WHERE id = %s"):
                        try:
                            db.execute(sql, (jid,))
                        except Exception:
                            pass
        except Exception:
            pass
    for a in ["ut5_admin", "ut5_legacy"]:
        try:
            rows = db.query("SELECT id FROM admin WHERE username = %s", (a,))
            for r in rows:
                try:
                    db.execute("DELETE FROM auth_session WHERE admin_id = %s", (r["id"],))
                except Exception:
                    pass
                try:
                    db.execute("DELETE FROM admin WHERE id = %s", (r["id"],))
                except Exception:
                    pass
        except Exception:
            pass
    try:
        db.execute("DELETE FROM jobseeker_cv WHERE cv_id LIKE %s", ("ut5cv%",))
    except Exception:
        pass


def load_pw_strength():
    """Extract app._pw_strength without importing the streamlit UI."""
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    m = re.search(r"(def _pw_strength\(password\):.*?)(?=\n\ndef |\n\n@|\Z)",
                  src, re.DOTALL)
    ns = {}
    exec(m.group(1), ns)
    return ns["_pw_strength"]


def main():
    tester = os.environ.get("STC_TESTER", "auto")
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"Environment: Windows, Python {sys.version.split()[0]}, db=cvision")
    print(f"Tester: {tester}  Date: {today}\n")

    try:
        auth_service.ensure_auth_tables()
    except Exception as e:
        print(f"ensure_auth_tables failed: {e}")

    if os.path.exists(REGISTRY):
        shutil.copy2(REGISTRY, BACKUP)
    cleanup()
    _pw_strength = load_pw_strength()

    # ---------- UT-5-01 hash_password ----------
    try:
        h = auth_service.hash_password("Alice123")
        emit("UT-5-01-001", h.startswith("pbkdf2_sha256$260000$"),
             f"hash starts with 'pbkdf2_sha256$260000$' ({h[:32]}...)")
    except Exception as e:
        emit("UT-5-01-001", False, f"{type(e).__name__}: {e}")
    try:
        a, b = auth_service.hash_password("Alice123"), auth_service.hash_password("Alice123")
        emit("UT-5-01-002", a != b, "two calls give different hashes (random salt)")
    except Exception as e:
        emit("UT-5-01-002", False, f"{type(e).__name__}: {e}")
    try:
        h = auth_service.hash_password("Alice123")
        emit("UT-5-01-003", "Alice123" not in h, "hash contains no plaintext")
    except Exception as e:
        emit("UT-5-01-003", False, f"{type(e).__name__}: {e}")
    try:
        auth_service.hash_password("")
        emit("UT-5-01-004", False, "empty password unexpectedly accepted")
    except auth_service.AuthValidationException as ex:
        emit("UT-5-01-004", True, f"AuthValidationException ({ex})")
    except Exception as e:
        emit("UT-5-01-004", False, f"wrong {type(e).__name__}: {e}")

    # ---------- UT-5-02 verify_password ----------
    _h = auth_service.hash_password("Alice123")
    try:
        emit("UT-5-02-001", auth_service.verify_password("Alice123", _h) is True,
             "correct password verifies True")
    except Exception as e:
        emit("UT-5-02-001", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-02-002", auth_service.verify_password("Wrong123", _h) is False,
             "wrong password verifies False")
    except Exception as e:
        emit("UT-5-02-002", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-02-003", auth_service.verify_password("Alice123", None) is False,
             "stored=None verifies False (no raise)")
    except Exception as e:
        emit("UT-5-02-003", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-02-004", auth_service.verify_password("123", "123") is False,
             "legacy plaintext verifies False (handled by admin path, not here)")
    except Exception as e:
        emit("UT-5-02-004", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-02-005", auth_service.verify_password("x", "garbage-value") is False,
             "malformed stored value verifies False (no raise)")
    except Exception as e:
        emit("UT-5-02-005", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-03 ensure_auth_tables ----------
    try:
        auth_service.ensure_auth_tables()
        j = db.query("SELECT COUNT(*) c FROM jobseeker")[0]["c"]
        s = db.query("SELECT COUNT(*) c FROM auth_session")[0]["c"]
        emit("UT-5-03-001", True, f"jobseeker + auth_session exist (rows {j}/{s})")
    except Exception as e:
        emit("UT-5-03-001", False, f"{type(e).__name__}: {e}")
    try:
        auth_service.ensure_auth_tables()
        auth_service.ensure_auth_tables()
        emit("UT-5-03-002", True, "second call raises nothing (IF NOT EXISTS, no duplicates)")
    except Exception as e:
        emit("UT-5-03-002", False, f"{type(e).__name__}: {e}")
    try:
        src = open(os.path.join(ROOT, "auth_service.py"), encoding="utf-8").read()
        body = src[src.index("def ensure_auth_tables"):src.index("# ---------------------------------------------------------------------\n# Validation")]
        creates = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", body)
        n0 = db.query("SELECT COUNT(*) c FROM admin")[0]["c"]
        auth_service.ensure_auth_tables()
        n1 = db.query("SELECT COUNT(*) c FROM admin")[0]["c"]
        emit("UT-5-03-003", sorted(creates) == ["auth_session", "jobseeker"] and n0 == n1,
             f"creates only {sorted(creates)}; admin row count unchanged ({n0}->{n1})")
    except Exception as e:
        emit("UT-5-03-003", False, f"{type(e).__name__}: {e}")
    try:
        with mock.patch.object(db, "execute",
                               side_effect=db.DatabaseError("Unable to read from the database.")):
            try:
                auth_service.ensure_auth_tables()
                emit("UT-5-03-004", False, "DB failure unexpectedly swallowed")
            except Exception as ex:
                emit("UT-5-03-004", type(ex).__name__ in ("DatabaseError", "DatabaseException"),
                     f"surfaces {type(ex).__name__} (template names it DatabaseException; "
                     "implementation raises db.DatabaseError — same DB-layer failure, not swallowed)")
    except Exception as e:
        emit("UT-5-03-004", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-04 validate_registration ----------
    try:
        out = auth_service.validate_registration("alice_j", "alice@example.com", "Alice123")
        emit("UT-5-04-001", out == ("alice_j", "alice@example.com"), f"returns {out}")
    except Exception as e:
        emit("UT-5-04-001", False, f"{type(e).__name__}: {e}")
    bad = [
        ("UT-5-04-002", ("ab", "a@t.com", "Valid1234"), "short username"),
        ("UT-5-04-003", ("alice j", "a@t.com", "Valid1234"), "username with space"),
        ("UT-5-04-004", ("alice_j", "alice@", "Valid1234"), "malformed email"),
        ("UT-5-04-005", ("alice_j", "a" * 244 + "@example.com", "Valid1234"), "email >255 chars"),
        ("UT-5-04-006", ("alice_j", "a@t.com", "Short12"), "password 7 chars"),
        ("UT-5-04-007", ("alice_j", "a@t.com", "A" * 65), "password 65 chars"),
        ("UT-5-04-008", ("", "a@t.com", "Valid1234"), "missing username"),
    ]
    for rid, args, desc in bad:
        try:
            auth_service.validate_registration(*args)
            emit(rid, False, f"{desc} unexpectedly accepted")
        except auth_service.AuthValidationException as ex:
            emit(rid, True, f"{desc} rejected ({ex})")
        except Exception as e:
            emit(rid, False, f"wrong {type(e).__name__}: {e}")
    try:
        auth_service.validate_registration("abc", "b@t.com", "A1234567")
        emit("UT-5-04-009", True, "boundary values (3-char user, 8-char pw) do not throw")
    except Exception as e:
        emit("UT-5-04-009", False, f"{type(e).__name__}: {e}")
    try:
        auth_service.validate_registration("alice_j", "a@t.com", "")
        emit("UT-5-04-010", False, "empty password unexpectedly accepted")
    except auth_service.AuthValidationException as ex:
        emit("UT-5-04-010", True, f"empty password rejected ({ex})")
    except Exception as e:
        emit("UT-5-04-010", False, f"wrong {type(e).__name__}: {e}")

    # ---------- UT-5-05 is_username_taken ----------
    try:
        auth_service.register_jobseeker("ut5_user1", "ut5_user1@example.com", "User1234")
    except Exception:
        pass
    try:
        emit("UT-5-05-001", auth_service.is_username_taken("ut5_user1") is True, "existing username -> True")
    except Exception as e:
        emit("UT-5-05-001", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-05-002", auth_service.is_username_taken("ut5_nobody_xyz") is False, "unknown username -> False")
    except Exception as e:
        emit("UT-5-05-002", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-05-003", auth_service.is_username_taken("  ut5_user1  ") is True, "padded username -> True (stripped)")
    except Exception as e:
        emit("UT-5-05-003", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-05-004", auth_service.is_username_taken("") is False, "empty username -> False (no query)")
    except Exception as e:
        emit("UT-5-05-004", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-06 is_email_taken ----------
    try:
        emit("UT-5-06-001", auth_service.is_email_taken("ut5_user1@example.com") is True, "existing email -> True")
    except Exception as e:
        emit("UT-5-06-001", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-06-002", auth_service.is_email_taken("  UT5_USER1@Example.COM ") is True, "case/space variant -> True")
    except Exception as e:
        emit("UT-5-06-002", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-06-003", auth_service.is_email_taken("ut5_nobody_xyz@example.com") is False, "unknown email -> False")
    except Exception as e:
        emit("UT-5-06-003", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-06-004", auth_service.is_email_taken("") is False, "empty email -> False (no query)")
    except Exception as e:
        emit("UT-5-06-004", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-07 register_jobseeker ----------
    try:
        n0 = db.query("SELECT COUNT(*) c FROM jobseeker")[0]["c"]
        u = auth_service.register_jobseeker("ut5_reg1", "ut5_reg1@example.com", "Reg12345")
        n1 = db.query("SELECT COUNT(*) c FROM jobseeker")[0]["c"]
        ok = set(u.keys()) == {"id", "username", "email"} and n1 == n0 + 1
        emit("UT-5-07-001", ok, f"returns id/username/email; count {n0}->{n1}")
        ut5_reg1_id = u["id"]
    except Exception as e:
        emit("UT-5-07-001", False, f"{type(e).__name__}: {e}")
        ut5_reg1_id = None
    try:
        h = get_pw_hash(ut5_reg1_id)
        emit("UT-5-07-002", h.startswith("pbkdf2_sha256$") and "Reg12345" not in h,
             f"password_hash salted ({h[:24]}...), no plaintext")
    except Exception as e:
        emit("UT-5-07-002", False, f"{type(e).__name__}: {e}")
    try:
        row = db.query("SELECT created_at FROM jobseeker WHERE id=%s", (ut5_reg1_id,))[0]
        emit("UT-5-07-003", row.get("created_at") is not None, f"created_at={row.get('created_at')} (UTC)")
    except Exception as e:
        emit("UT-5-07-003", False, f"{type(e).__name__}: {e}")
    try:
        auth_service.register_jobseeker("ut5_reg1", "ut5_other@example.com", "Reg12345")
        emit("UT-5-07-004", False, "duplicate username unexpectedly accepted")
    except auth_service.UsernameTakenException as ex:
        emit("UT-5-07-004", True, f"UsernameTakenException ({ex})")
    except Exception as e:
        emit("UT-5-07-004", False, f"wrong {type(e).__name__}: {e}")
    try:
        auth_service.register_jobseeker("ut5_other", "ut5_reg1@example.com", "Reg12345")
        emit("UT-5-07-005", False, "duplicate email unexpectedly accepted")
    except auth_service.EmailTakenException as ex:
        emit("UT-5-07-005", True, f"EmailTakenException ({ex})")
    except Exception as e:
        emit("UT-5-07-005", False, f"wrong {type(e).__name__}: {e}")
    try:
        n0 = db.query("SELECT COUNT(*) c FROM jobseeker")[0]["c"]
        try:
            auth_service.register_jobseeker("ab", "bad@", "short")
        except auth_service.AuthValidationException:
            pass
        n1 = db.query("SELECT COUNT(*) c FROM jobseeker")[0]["c"]
        emit("UT-5-07-006", n0 == n1, f"invalid input raises AuthValidationException; count {n0}->{n1}")
    except Exception as e:
        emit("UT-5-07-006", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-08 authenticate_jobseeker ----------
    try:
        auth_service.register_jobseeker("ut5_auth", "ut5_auth@example.com", "Auth1234")
    except Exception:
        pass
    _a = db.query("SELECT id FROM jobseeker WHERE username=%s", ("ut5_auth",))[0]["id"]
    try:
        u = auth_service.authenticate_jobseeker("ut5_auth", "Auth1234")
        emit("UT-5-08-001", bool(u and u["id"] == _a), f"username login returns id {_a[:8]}")
    except Exception as e:
        emit("UT-5-08-001", False, f"{type(e).__name__}: {e}")
    try:
        u = auth_service.authenticate_jobseeker("ut5_auth@example.com", "Auth1234")
        emit("UT-5-08-002", bool(u and u["id"] == _a), "email login returns same id")
    except Exception as e:
        emit("UT-5-08-002", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-08-003", auth_service.authenticate_jobseeker("ut5_auth", "Wrong123") is None, "wrong password -> None")
    except Exception as e:
        emit("UT-5-08-003", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-08-004", auth_service.authenticate_jobseeker("ut5_nobody_xyz", "Auth1234") is None, "unknown id -> None")
    except Exception as e:
        emit("UT-5-08-004", False, f"{type(e).__name__}: {e}")
    try:
        ok = auth_service.authenticate_jobseeker("", "Auth1234") is None and auth_service.authenticate_jobseeker("ut5_auth", "") is None
        emit("UT-5-08-005", ok, "empty identifier/password -> None (no raise)")
    except Exception as e:
        emit("UT-5-08-005", False, f"{type(e).__name__}: {e}")
    try:
        u = auth_service.authenticate_jobseeker("ut5_auth", "Auth1234")
        emit("UT-5-08-006", set(u.keys()) == {"id", "username", "email"}, f"keys={sorted(u.keys())} (no hash)")
    except Exception as e:
        emit("UT-5-08-006", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-09 get_jobseeker_by_id ----------
    try:
        u = auth_service.get_jobseeker_by_id(_a)
        emit("UT-5-09-001", bool(u and u["id"] == _a and "password_hash" not in u), f"returns id/username/email, no hash")
    except Exception as e:
        emit("UT-5-09-001", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-09-002", auth_service.get_jobseeker_by_id("00000000-0000-0000-0000-000000000000") is None, "unknown id -> None")
    except Exception as e:
        emit("UT-5-09-002", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-10 require_jobseeker ----------
    try:
        emit("UT-5-10-001", auth_service.require_jobseeker(_a) == _a, "valid id returned unchanged")
    except Exception as e:
        emit("UT-5-10-001", False, f"{type(e).__name__}: {e}")
    for rid, val in [("UT-5-10-002", None), ("UT-5-10-003", "")]:
        try:
            auth_service.require_jobseeker(val)
            emit(rid, False, f"{val!r} unexpectedly accepted")
        except auth_service.UnauthenticatedUploadException as ex:
            emit(rid, True, f"{val!r} raises UnauthenticatedUploadException ({ex})")
        except Exception as e:
            emit(rid, False, f"wrong {type(e).__name__}: {e}")

    # ---------- UT-5-11 change_jobseeker_password ----------
    try:
        auth_service.register_jobseeker("ut5_pw", "ut5_pw@example.com", "Old12345")
    except Exception:
        pass
    _p = db.query("SELECT id FROM jobseeker WHERE username=%s", ("ut5_pw",))[0]["id"]
    db.execute("UPDATE jobseeker SET password_hash=%s WHERE id=%s",
               (auth_service.hash_password("Old12345"), _p))
    try:
        auth_service.change_jobseeker_password(_p, "Old12345", "New12345")
        h = get_pw_hash(_p)
        ok = auth_service.verify_password("New12345", h) and not auth_service.verify_password("Old12345", h)
        emit("UT-5-11-001", ok, "no-throw; new verifies, old does not")
    except Exception as e:
        emit("UT-5-11-001", False, f"{type(e).__name__}: {e}")
    try:
        h0 = get_pw_hash(_p)
        try:
            auth_service.change_jobseeker_password(_p, "Wrong123", "Zebra123")
            emit("UT-5-11-002", False, "wrong current unexpectedly accepted")
        except auth_service.AuthValidationException:
            emit("UT-5-11-002", get_pw_hash(_p) == h0, "wrong current rejected; hash unchanged")
    except Exception as e:
        emit("UT-5-11-002", False, f"{type(e).__name__}: {e}")
    for rid, newpw, desc in [("UT-5-11-003", "Short12", "7-char new"),
                             ("UT-5-11-004", "password", "blocklisted new"),
                             ("UT-5-11-005", "New12345", "same-as-old new"),
                             ("UT-5-11-006", "A" * 65, "65-char new")]:
        try:
            try:
                auth_service.change_jobseeker_password(_p, "New12345", newpw)
                emit(rid, False, f"{desc} unexpectedly accepted")
            except auth_service.AuthValidationException as ex:
                emit(rid, True, f"{desc} rejected ({ex})")
        except Exception as e:
            emit(rid, False, f"{type(e).__name__}: {e}")
    try:
        try:
            auth_service.change_jobseeker_password(None, "x", "New12345")
            emit("UT-5-11-007", False, "unsigned-in change unexpectedly accepted")
        except auth_service.AuthValidationException as ex:
            emit("UT-5-11-007", True, f"not signed in rejected ({ex})")
    except Exception as e:
        emit("UT-5-11-007", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-12 reset_jobseeker_password ----------
    try:
        auth_service.register_jobseeker("ut5_rst", "ut5_rst@example.com", "Rst12345")
    except Exception:
        pass
    _r = db.query("SELECT id FROM jobseeker WHERE username=%s", ("ut5_rst",))[0]["id"]
    db.execute("UPDATE jobseeker SET password_hash=%s WHERE id=%s",
               (auth_service.hash_password("Rst12345"), _r))
    try:
        h0 = get_pw_hash(_r)
        u = auth_service.reset_jobseeker_password("ut5_rst", "ut5_rst@example.com", "Fresh123", "Fresh123")
        h1 = get_pw_hash(_r)
        emit("UT-5-12-001", u["id"] == _r and h0 != h1, "returns id/username/email; hash replaced")
    except Exception as e:
        emit("UT-5-12-001", False, f"{type(e).__name__}: {e}")
    _m2 = _m3 = None
    try:
        auth_service.reset_jobseeker_password("ut5_rst", "ut5_user1@example.com", "Fresh123", "Fresh123")
        emit("UT-5-12-002", False, "cross email unexpectedly accepted")
    except auth_service.AuthValidationException as ex:
        _m2 = str(ex)
        emit("UT-5-12-002", True, f"generic failure, nothing changed ({ex})")
    except Exception as e:
        emit("UT-5-12-002", False, f"wrong {type(e).__name__}: {e}")
    try:
        auth_service.reset_jobseeker_password("ut5_nobody_xyz", "ut5_rst@example.com", "Fresh123", "Fresh123")
        emit("UT-5-12-003", False, "unknown user unexpectedly accepted")
    except auth_service.AuthValidationException as ex:
        _m3 = str(ex)
        emit("UT-5-12-003", _m3 == _m2, f"same message as 002 ('{ex}')")
    except Exception as e:
        emit("UT-5-12-003", False, f"wrong {type(e).__name__}: {e}")
    for rid, args, desc in [
            ("UT-5-12-004", ("ut5_rst", "ut5_rst@example.com", "Fresh123", "Fresh124"), "mismatched confirmation"),
            ("UT-5-12-005", ("ut5_rst", "ut5_rst@example.com", "Fresh123", None), "missing confirmation"),
            ("UT-5-12-006", ("ut5_rst", "ut5_rst@example.com", "abc", "abc"), "weak password"),
            ("UT-5-12-007", ("", "", "Fresh123", "Fresh123"), "missing username/email")]:
        try:
            h0 = get_pw_hash(_r)
            try:
                auth_service.reset_jobseeker_password(*args)
                emit(rid, False, f"{desc} unexpectedly accepted")
            except auth_service.AuthValidationException as ex:
                emit(rid, get_pw_hash(_r) == h0, f"{desc} rejected ({ex})")
        except Exception as e:
            emit(rid, False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-13 authenticate_admin ----------
    try:
        aid = str(uuid.uuid4())
        db.execute("INSERT INTO admin (id, username, password) VALUES (%s,%s,%s)",
                   (aid, "ut5_admin", auth_service.hash_password("Admin@2026")))
        lid = str(uuid.uuid4())
        db.execute("INSERT INTO admin (id, username, password) VALUES (%s,%s,%s)",
                   (lid, "ut5_legacy", "Legacy@2026"))
    except Exception as e:
        emit("UT-5-13-001", False, f"fixture failed: {e}")
        aid = lid = None
    try:
        a = auth_service.authenticate_admin("ut5_admin", "Admin@2026")
        emit("UT-5-13-001", bool(a and set(a.keys()) == {"id", "username"}), f"returns id/username ({a})")
    except Exception as e:
        emit("UT-5-13-001", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-13-002", auth_service.authenticate_admin("ut5_admin", "Wrong@2026") is None, "wrong password -> None")
    except Exception as e:
        emit("UT-5-13-002", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-13-003", auth_service.authenticate_admin("ut5_nobody_xyz", "Admin@2026") is None, "unknown admin -> None")
    except Exception as e:
        emit("UT-5-13-003", False, f"{type(e).__name__}: {e}")
    try:
        a = auth_service.authenticate_admin("ut5_legacy", "Legacy@2026")
        after = db.query("SELECT password FROM admin WHERE username=%s", ("ut5_legacy",))[0]["password"]
        emit("UT-5-13-004", bool(a) and after.startswith("pbkdf2_sha256$"),
             "legacy plaintext accepted once; row upgraded to salted hash")
    except Exception as e:
        emit("UT-5-13-004", False, f"{type(e).__name__}: {e}")
    try:
        a = auth_service.authenticate_admin("ut5_legacy", "Legacy@2026")
        emit("UT-5-13-005", bool(a and a["username"] == "ut5_legacy"), "post-upgrade login via hash path works")
    except Exception as e:
        emit("UT-5-13-005", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-13-006", auth_service.authenticate_admin("ut5_auth", "Auth1234") is None, "jobseeker creds -> None at admin login")
    except Exception as e:
        emit("UT-5-13-006", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-14 change_jobseeker_username ----------
    try:
        auth_service.register_jobseeker("ut5_nm", "ut5_nm@example.com", "Nm123456")
    except Exception:
        pass
    _n = db.query("SELECT id FROM jobseeker WHERE username=%s", ("ut5_nm",))[0]["id"]
    try:
        u = auth_service.change_jobseeker_username(_n, "ut5_nm2")
        row = db.query("SELECT username, email FROM jobseeker WHERE id=%s", (_n,))[0]
        emit("UT-5-14-001", u["username"] == "ut5_nm2" and row["username"] == "ut5_nm2",
             f"row updated to ut5_nm2 (email kept {row['email']})")
        _n2 = _n
    except Exception as e:
        emit("UT-5-14-001", False, f"{type(e).__name__}: {e}")
        _n2 = None
    try:
        calls = []
        orig = db.execute
        def spy(sql, params=()):
            calls.append(sql)
            return orig(sql, params)
        db.execute = spy
        try:
            u = auth_service.change_jobseeker_username(_n2, "ut5_nm2")
        finally:
            db.execute = orig
        writes = [s for s in calls if s.strip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        emit("UT-5-14-002", u["username"] == "ut5_nm2" and not writes,
             "unchanged name returns existing account; 0 write statements issued")
    except Exception as e:
        try:
            db.execute = orig
        except Exception:
            pass
        emit("UT-5-14-002", False, f"{type(e).__name__}: {e}")
    try:
        auth_service.change_jobseeker_username(_n2, "ut5_user1")
        emit("UT-5-14-003", False, "duplicate name unexpectedly accepted")
    except auth_service.UsernameTakenException as ex:
        emit("UT-5-14-003", True, f"UsernameTakenException ({ex})")
    except Exception as e:
        emit("UT-5-14-003", False, f"wrong {type(e).__name__}: {e}")
    try:
        auth_service.change_jobseeker_username(_n2, "a b")
        emit("UT-5-14-004", False, "invalid format unexpectedly accepted")
    except auth_service.AuthValidationException as ex:
        emit("UT-5-14-004", True, f"AuthValidationException ({ex})")
    except Exception as e:
        emit("UT-5-14-004", False, f"wrong {type(e).__name__}: {e}")
    try:
        auth_service.change_jobseeker_username(None, "ut5_x")
        emit("UT-5-14-005", False, "unsigned-in rename unexpectedly accepted")
    except auth_service.AuthValidationException as ex:
        emit("UT-5-14-005", True, f"AuthValidationException ({ex})")
    except Exception as e:
        emit("UT-5-14-005", False, f"wrong {type(e).__name__}: {e}")

    # ---------- UT-5-15 create_jobseeker_session ----------
    try:
        t = auth_service.create_jobseeker_session(_a)
        row = db.query("SELECT jobseeker_id, admin_id, created_at, expires_at FROM auth_session WHERE token=%s", (t,))[0]
        delta = row["expires_at"] - row["created_at"]
        ok = row["jobseeker_id"] == _a and row["admin_id"] is None and abs(delta - timedelta(days=30)) < timedelta(minutes=1)
        emit("UT-5-15-001", ok, f"token row: jobseeker set, admin NULL, expiry +30d (delta={delta})")
        _t_js = t
    except Exception as e:
        emit("UT-5-15-001", False, f"{type(e).__name__}: {e}")
        _t_js = None
    try:
        t2 = auth_service.create_jobseeker_session(_a)
        emit("UT-5-15-002", t2 != _t_js, "two tokens differ (random)")
    except Exception as e:
        emit("UT-5-15-002", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-16 create_admin_session ----------
    try:
        at = auth_service.create_admin_session(aid)
        row = db.query("SELECT jobseeker_id, admin_id FROM auth_session WHERE token=%s", (at,))[0]
        emit("UT-5-16-001", row["admin_id"] == aid and row["jobseeker_id"] is None,
             "token row: admin set, jobseeker NULL")
        _t_ad = at
    except Exception as e:
        emit("UT-5-16-001", False, f"{type(e).__name__}: {e}")
        _t_ad = None

    # ---------- UT-5-17 get_jobseeker_by_session ----------
    try:
        u = auth_service.get_jobseeker_by_session(_t_js)
        emit("UT-5-17-001", bool(u and u["id"] == _a), "valid token returns id/username/email")
    except Exception as e:
        emit("UT-5-17-001", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-17-002", auth_service.get_jobseeker_by_session("no-such-token") is None, "unknown token -> None")
    except Exception as e:
        emit("UT-5-17-002", False, f"{type(e).__name__}: {e}")
    try:
        exp = str(uuid.uuid4().hex)
        past = datetime.now(timezone.utc) - timedelta(days=31)
        db.execute("INSERT INTO auth_session (token, jobseeker_id, admin_id, created_at, expires_at) VALUES (%s,%s,NULL,%s,%s)",
                   (exp, _a, past - timedelta(days=1), past))
        got = auth_service.get_jobseeker_by_session(exp)
        left = db.query("SELECT token FROM auth_session WHERE token=%s", (exp,))
        emit("UT-5-17-003", got is None and not left, "expired token -> None; row deleted")
    except Exception as e:
        emit("UT-5-17-003", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-17-004", auth_service.get_jobseeker_by_session(None) is None, "None token -> None (no raise)")
    except Exception as e:
        emit("UT-5-17-004", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-17-005", auth_service.get_jobseeker_by_session(_t_ad) is None, "admin token -> None on jobseeker lookup")
    except Exception as e:
        emit("UT-5-17-005", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-18 get_admin_by_session ----------
    try:
        a = auth_service.get_admin_by_session(_t_ad)
        emit("UT-5-18-001", bool(a and a["username"] == "ut5_admin"), "valid admin token returns id/username")
    except Exception as e:
        emit("UT-5-18-001", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-18-002", auth_service.get_admin_by_session("no-such-token") is None, "unknown token -> None")
    except Exception as e:
        emit("UT-5-18-002", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-18-003", auth_service.get_admin_by_session(_t_js) is None, "jobseeker token -> None on admin lookup")
    except Exception as e:
        emit("UT-5-18-003", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-19 delete_session ----------
    try:
        t = auth_service.create_jobseeker_session(_a)
        auth_service.delete_session(t)
        left = db.query("SELECT token FROM auth_session WHERE token=%s", (t,))
        emit("UT-5-19-001", not left, "session row deleted")
    except Exception as e:
        emit("UT-5-19-001", False, f"{type(e).__name__}: {e}")
    for rid, val in [("UT-5-19-002", None), ("UT-5-19-003", "no-such-token"), ("UT-5-19-004", "")]:
        try:
            auth_service.delete_session(val)
            emit(rid, True, f"{val!r}: no exception")
        except Exception as e:
            emit(rid, False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-20 _pw_strength ----------
    try:
        pct, lbl, col = _pw_strength("ab")
        emit("UT-5-20-001", lbl == "Weak" and pct <= 25, f"weak pw -> ({pct}, '{lbl}')")
    except Exception as e:
        emit("UT-5-20-001", False, f"{type(e).__name__}: {e}")
    try:
        pct, lbl, col = _pw_strength("Abcdef123!@#x")
        emit("UT-5-20-002", lbl == "Strong" and pct >= 75, f"strong pw -> ({pct}, '{lbl}')")
    except Exception as e:
        emit("UT-5-20-002", False, f"{type(e).__name__}: {e}")

    # ---------- UT-5-21 record_cv_ownership ----------
    try:
        ok = cv_data_adapter.record_cv_ownership(_a, "ut5cv_own_001", "CV.pdf")
        rows = db.query("SELECT jobseeker_id, cv_id, original_filename, uploaded_at FROM jobseeker_cv WHERE cv_id=%s", ("ut5cv_own_001",))
        emit("UT-5-21-001", ok is True and rows and rows[0]["uploaded_at"] is not None,
             f"returns True; row holds ids/filename/upload time ({rows[0] if rows else None})")
    except Exception as e:
        emit("UT-5-21-001", False, f"{type(e).__name__}: {e}")
    for rid, args in [("UT-5-21-002", (None, "ut5cv_x", "CV.pdf")),
                      ("UT-5-21-003", ("", "", None))]:
        try:
            out = cv_data_adapter.record_cv_ownership(*args)
            # plus the DB-failure path: must also not raise (best-effort)
            with mock.patch.object(db, "execute",
                                   side_effect=Exception("db down")):
                out2 = cv_data_adapter.record_cv_ownership(_a, "ut5cv_x2", "CV.pdf")
            emit(rid, False,
                 f"no exception raised (returns {out}; DB-failure path returns {out2}); "
                 "template expects DatabaseException — implementation is best-effort "
                 "False by design (see cv_data_adapter docstring)")
        except Exception as ex:
            emit(rid, type(ex).__name__ in ("DatabaseException", "DatabaseError"),
                 f"raises {type(ex).__name__}: {ex}")

    # ---------- UT-5-22 list_cv_ids_for ----------
    try:
        auth_service.register_jobseeker("ut5_list", "ut5_list@example.com", "List1234")
    except Exception:
        pass
    _l = db.query("SELECT id FROM jobseeker WHERE username=%s", ("ut5_list",))[0]["id"]
    try:
        auth_service.register_jobseeker("ut5_other", "ut5_other@example.com", "Other123")
    except Exception:
        pass
    _o = db.query("SELECT id FROM jobseeker WHERE username=%s", ("ut5_other",))[0]["id"]
    base = datetime.now(timezone.utc)
    recs = load_registry()
    for i in range(3):
        cid = f"ut5cv_l00{i}"
        if not any(r.get("id") == cid for r in recs):
            recs.append({"id": cid, "original_filename": cid + ".pdf", "stored_path": "uploads/" + cid,
                         "size_bytes": 10, "sha256": "d" * 64, "uploaded_at": base.isoformat(),
                         "validation_status": "validated",
                         "extracted_data": {"skills": [{"skill_name": "S"}], "education": [], "work_experience": []}})
        cv_data_adapter.record_cv_ownership(_l, cid, cid + ".pdf", base + timedelta(seconds=i))
    save_registry(recs)
    try:
        got = [r.get("cv_id") for r in cv_data_adapter.list_cv_ids_for(_l)]
        want = ["ut5cv_l002", "ut5cv_l001", "ut5cv_l000"]
        emit("UT-5-22-001", got[:3] == want, f"3 ids newest-first: {got[:3]}")
    except Exception as e:
        emit("UT-5-22-001", False, f"{type(e).__name__}: {e}")
    try:
        recs = load_registry()
        for i in range(3, 25):
            cid = f"ut5cv_l{i:03d}"
            if not any(r.get("id") == cid for r in recs):
                recs.append({"id": cid, "original_filename": cid + ".pdf", "stored_path": "uploads/" + cid,
                             "size_bytes": 10, "sha256": "d" * 64, "uploaded_at": base.isoformat(),
                             "validation_status": "validated",
                             "extracted_data": {"skills": [{"skill_name": "S"}], "education": [], "work_experience": []}})
            cv_data_adapter.record_cv_ownership(_l, cid, cid + ".pdf", base + timedelta(seconds=i))
        save_registry(recs)
        got = cv_data_adapter.list_cv_ids_for(_l)
        emit("UT-5-22-002", len(got) == 20,
             f"returns {len(got)} ids (template expects the 20 newest; "
             "service has no cap — the [:20] slice lives in app.py UI)")
    except Exception as e:
        emit("UT-5-22-002", False, f"{type(e).__name__}: {e}")
    try:
        recs = load_registry()
        if not any(r.get("id") == "ut5cv_other_001" for r in recs):
            recs.append({"id": "ut5cv_other_001", "original_filename": "o.pdf", "stored_path": "uploads/o",
                         "size_bytes": 10, "sha256": "e" * 64, "uploaded_at": base.isoformat(),
                         "validation_status": "validated",
                         "extracted_data": {"skills": [{"skill_name": "S"}], "education": [], "work_experience": []}})
            save_registry(recs)
        cv_data_adapter.record_cv_ownership(_o, "ut5cv_other_001", "o.pdf", base)
        got = [r.get("cv_id") for r in cv_data_adapter.list_cv_ids_for(_l)]
        emit("UT-5-22-003", "ut5cv_other_001" not in got, "other jobseeker's id excluded")
    except Exception as e:
        emit("UT-5-22-003", False, f"{type(e).__name__}: {e}")
    try:
        recs = load_registry()
        if not any(r.get("id") == "ut5cv_unparsed" for r in recs):
            recs.append({"id": "ut5cv_unparsed", "original_filename": "u.pdf", "stored_path": "uploads/u",
                         "size_bytes": 10, "sha256": "f" * 64, "uploaded_at": base.isoformat(),
                         "validation_status": "validated"})
            save_registry(recs)
        cv_data_adapter.record_cv_ownership(_l, "ut5cv_unparsed", "u.pdf", base)
        got = [r.get("cv_id") for r in cv_data_adapter.list_cv_ids_for(_l)]
        emit("UT-5-22-004", "ut5cv_unparsed" not in got,
             f"unparsed id {'excluded' if 'ut5cv_unparsed' not in got else 'INCLUDED ' + str(got[-3:])} — "
             "service filters orphans only; the parsed-only filter lives in app.py (_has_extracted_data)")
    except Exception as e:
        emit("UT-5-22-004", False, f"{type(e).__name__}: {e}")
    try:
        db.execute("INSERT INTO jobseeker_cv (id, jobseeker_id, cv_id, original_filename, uploaded_at) VALUES (%s,%s,%s,%s,%s)",
                   (str(uuid.uuid4()), _l, "ut5cv_orphan_zzz", "z.pdf", base))
        got = [r.get("cv_id") for r in cv_data_adapter.list_cv_ids_for(_l)]
        emit("UT-5-22-005", "ut5cv_orphan_zzz" not in got, "orphan id (absent from registry) excluded")
    except Exception as e:
        emit("UT-5-22-005", False, f"{type(e).__name__}: {e}")
    try:
        emit("UT-5-22-006", cv_data_adapter.list_cv_ids_for("00000000-0000-0000-0000-000000000000") == [], "unknown jobseeker -> []")
    except Exception as e:
        emit("UT-5-22-006", False, f"{type(e).__name__}: {e}")

    passed = sum(1 for r in results if r["result"] == "PASS")
    print(f"\nSUMMARY: {passed}/{len(results)} passed")
    return tester, today


def write_outputs(tester, today):
    out_json = os.path.join(os.path.dirname(__file__), f"test_results_UT5_{today}.json")
    out_md = os.path.join(os.path.dirname(__file__), f"test_results_UT5_{today}.md")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump([{"test_id": r["test_id"], "result": r["result"], "actual": r["actual"],
                    "tester": tester, "date": today} for r in results], f, indent=2, ensure_ascii=False)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"# Feature 5 Unit Test Results — {today} (tester: {tester})\n\n")
        f.write(f"SUMMARY: {sum(1 for r in results if r['result']=='PASS')}/{len(results)} passed\n\n")
        f.write("| Test Record ID | Result | Actual Output |\n|---|---|---|\n")
        for r in results:
            a = r["actual"].replace("|", "/").replace("\n", " ")
            f.write(f"| {r['test_id']} | {r['result']} | {a} |\n")
    print(f"Wrote {out_json}\nWrote {out_md}")


if __name__ == "__main__":
    tester = today = None
    try:
        tester, today = main()
    finally:
        try:
            cleanup()
        except Exception:
            pass
        try:
            if os.path.exists(BACKUP):
                shutil.copy2(BACKUP, REGISTRY)
                os.remove(BACKUP)
                print("Restored cvs.json from backup.")
        except Exception as e:
            print(f"registry restore failed: {e}")
        if tester and today:
            write_outputs(tester, today)
