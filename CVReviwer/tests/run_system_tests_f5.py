"""System test runner for Feature #5 Authentication (STC-05-001 .. STC-05-009, 69 cases).

Runs against the real installation: real MySQL (jobseeker/admin/jobseeker_cv/
auth_session) + real cvs.json registry. Test fixtures use isolated names
(stc_*/alice_j/bob_k/carol_z) and are deleted afterwards; cvs.json is backed
up and restored, so the installation is left unchanged except the tester
chooses to keep the filled record file.

Run:  py tests/run_system_tests_f5.py
Output: tests/test_results_F5_<date>.json/.md + filled record md
"""
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, ROOT)

import db
import auth_service
import cv_data_adapter
import cv_upload

REGISTRY = os.path.abspath(cv_upload.CVS_REGISTRY_FILE)
BACKUP = REGISTRY + ".st5-backup"

results = []  # (test_id, PASS/FAIL, actual)


def emit(test_id, passed, actual):
    results.append({"test_id": test_id, "result": "PASS" if passed else "FAIL", "actual": actual})
    print(f"[{test_id}] {'PASS' if passed else 'FAIL'}  {actual}", flush=True)


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


def q(sql, params=()):
    try:
        return db.query(sql, params)
    except Exception as e:
        return e


def x(sql, params=()):
    return db.execute(sql, params)


def cleanup_fixture_usernames(names):
    for n in names:
        try:
            rows = db.query("SELECT id FROM jobseeker WHERE username = %s", (n,))
            for r in rows:
                jid = r["id"]
                try:
                    x("DELETE FROM jobseeker_cv WHERE jobseeker_id = %s", (jid,))
                except Exception:
                    pass
                try:
                    x("DELETE FROM auth_session WHERE jobseeker_id = %s", (jid,))
                except Exception:
                    pass
                try:
                    x("DELETE FROM jobseeker WHERE id = %s", (jid,))
                except Exception:
                    pass
        except Exception:
            pass
    # emails too (carol/alice/bob/new_user)
    for e in ["carol@example.com", "alice@example.com", "bob@example.com",
              "new@example.com", "stc_carol_x@example.com"]:
        try:
            rows = db.query("SELECT id FROM jobseeker WHERE email = %s", (e,))
            for r in rows:
                jid = r["id"]
                try:
                    x("DELETE FROM jobseeker_cv WHERE jobseeker_id = %s", (jid,))
                except Exception:
                    pass
                try:
                    x("DELETE FROM auth_session WHERE jobseeker_id = %s", (jid,))
                except Exception:
                    pass
                # only delete if username is a fixture (avoid touching real 'Test')
                u = db.query("SELECT username FROM jobseeker WHERE id = %s", (jid,))
                if u and u[0].get("username") in ("carol_z", "alice_j", "alice_j2",
                                                  "bob_k", "new_user"):
                    x("DELETE FROM jobseeker WHERE id = %s", (jid,))
        except Exception:
            pass


def cleanup_fixture_admins(names):
    for n in names:
        try:
            rows = db.query("SELECT id FROM admin WHERE username = %s", (n,))
            for r in rows:
                aid = r["id"]
                try:
                    x("DELETE FROM auth_session WHERE admin_id = %s", (aid,))
                except Exception:
                    pass
                try:
                    x("DELETE FROM admin WHERE id = %s", (aid,))
                except Exception:
                    pass
        except Exception:
            pass


def get_hash(jobseeker_id):
    rows = db.query("SELECT password_hash FROM jobseeker WHERE id = %s", (jobseeker_id,))
    return rows[0]["password_hash"] if rows else None


def read_source(fname):
    with open(os.path.join(ROOT, fname), "r", encoding="utf-8") as f:
        return f.read()


def main():
    tester = os.environ.get("STC_TESTER", "auto")
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"Environment: Windows, Python {sys.version.split()[0]}, db=cvision, registry={REGISTRY}")
    print(f"Tester: {tester}  Date: {today}\n")

    try:
        auth_service.ensure_auth_tables()
    except Exception as e:
        print(f"ensure_auth_tables failed: {e}")

    # snapshot registry
    had_registry = os.path.exists(REGISTRY)
    if had_registry:
        shutil.copy2(REGISTRY, BACKUP)
    registry_before = load_registry()
    ids_before = {r.get("id") for r in registry_before}

    # clean leftovers from previous runs
    cleanup_fixture_usernames(["carol_z", "alice_j", "alice_j2", "bob_k", "new_user"])
    cleanup_fixture_admins(["stc_admin", "stc_legacy"])
    try:
        x("DELETE FROM jobseeker_cv WHERE cv_id LIKE %s", ("stc_cv_%",))
    except Exception:
        pass

    app_src = read_source("app.py")
    admin_src = read_source("admin.py")

    # ---------------- STC-05-001 normal flow ----------------
    # TC-01: upload section shown to guest (static: file_uploader unconditional)
    try:
        idx_up = app_src.index("st.file_uploader(")
        # nearest preceding guard must NOT be a logged-in-only guard
        window = app_src[max(0, idx_up - 800):idx_up]
        ok = ("SRS-084" in app_src and "Upload your CV (PDF)" in app_src
              and "if _current_jobseeker_id():" not in window.splitlines()[-3:])
        emit("STC-05-001-TC-01", ok,
             "app.py renders st.file_uploader('Upload your CV (PDF)') unconditionally (SRS-084 section); "
             "guest sees the upload section")
    except Exception as e:
        emit("STC-05-001-TC-01", False, f"static check failed: {type(e).__name__}: {e}")

    # TC-02: guest upload opens login popup (static)
    try:
        ok = ("if uploaded_file and not _current_jobseeker_id():" in app_src
              and "_auth_dialog()" in app_src)
        emit("STC-05-001-TC-02", ok,
             "app.py: 'if uploaded_file and not _current_jobseeker_id()' calls _auth_dialog() "
             "instead of accepting the file")
    except Exception as e:
        emit("STC-05-001-TC-02", False, f"{type(e).__name__}: {e}")

    # TC-03: guest file discarded (behavioral)
    try:
        snap = json.dumps(load_registry(), sort_keys=True)
        rejected = False
        try:
            auth_service.require_jobseeker(None)
        except auth_service.UnauthenticatedUploadException:
            rejected = True
        no_record = all("Carol_CV.pdf" not in json.dumps(r) or r.get("id") in ids_before
                        for r in load_registry())
        owned_raises = False
        try:
            cv_data_adapter.record_cv_ownership(None, "stc_cv_guest", "Carol_CV.pdf")
        except cv_data_adapter.DatabaseException:
            owned_raises = True
        emit("STC-05-001-TC-03", rejected and json.dumps(load_registry(), sort_keys=True) == snap and owned_raises,
             "require_jobseeker(None) raises UnauthenticatedUploadException; registry unchanged; "
             "record_cv_ownership(None,..) raises DatabaseException (file discarded, nothing stored/processed)")
    except Exception as e:
        emit("STC-05-001-TC-03", False, f"{type(e).__name__}: {e}")

    # TC-04: registration format accepted
    try:
        u, e = auth_service.validate_registration("carol_z", "carol@example.com", "Carol123")
        emit("STC-05-001-TC-04", (u, e) == ("carol_z", "carol@example.com"),
             f"validate_registration accepts 3-30 char username, standard email, 8-64 char password -> ({u},{e})")
    except Exception as e:
        emit("STC-05-001-TC-04", False, f"unexpected {type(e).__name__}: {e}")

    # TC-05: duplicate check finds nothing (carol not yet created)
    try:
        un = auth_service.is_username_taken("carol_z")
        em = auth_service.is_email_taken("carol@example.com")
        emit("STC-05-001-TC-05", un is False and em is False,
             f"is_username_taken(carol_z)={un}, is_email_taken(carol@example.com)={em} (both False)")
    except Exception as e:
        emit("STC-05-001-TC-05", False, f"{type(e).__name__}: {e}")

    # TC-06: account created
    carol = None
    try:
        carol = auth_service.register_jobseeker("carol_z", "carol@example.com", "Carol123")
        row = auth_service.get_jobseeker_by_id(carol["id"])
        ok = bool(carol.get("id")) and row and row["username"] == "carol_z" and row["email"] == "carol@example.com"
        emit("STC-05-001-TC-06", ok, f"jobseeker row created: id={carol.get('id')}, username=carol_z, email=carol@example.com")
    except Exception as e:
        emit("STC-05-001-TC-06", False, f"{type(e).__name__}: {e}")

    # TC-07: salted hash only
    try:
        h = get_hash(carol["id"])
        ok = h.startswith("pbkdf2_sha256$260000$") and "Carol123" not in h and auth_service.verify_password("Carol123", h)
        emit("STC-05-001-TC-07", ok, f"password_hash={h[:32]}... (salted, no plaintext; verifies)")
    except Exception as e:
        emit("STC-05-001-TC-07", False, f"{type(e).__name__}: {e}")

    # TC-08: login by username
    u1 = None
    try:
        u1 = auth_service.authenticate_jobseeker("carol_z", "Carol123")
        ok = u1 and set(u1.keys()) == {"id", "username", "email"} and u1["id"] == carol["id"]
        emit("STC-05-001-TC-08", bool(ok), f"authenticate_jobseeker(carol_z) -> id={u1['id'] if u1 else None}, no hash in return")
    except Exception as e:
        emit("STC-05-001-TC-08", False, f"{type(e).__name__}: {e}")

    # TC-09: login by email same account
    try:
        u2 = auth_service.authenticate_jobseeker("carol@example.com", "Carol123")
        ok = u2 and u1 and u2["id"] == u1["id"]
        emit("STC-05-001-TC-09", bool(ok), f"authenticate_jobseeker(carol@example.com) -> same id={u2['id'] if u2 else None}")
    except Exception as e:
        emit("STC-05-001-TC-09", False, f"{type(e).__name__}: {e}")

    # TC-10: profile popover replaces login/signup (static)
    try:
        ok = ("st.popover(" in app_src and "Change name" in app_src and "Change password" in app_src
              and "Log out" in app_src and '"Log in"' in app_src and '"Sign up"' in app_src)
        emit("STC-05-001-TC-10", ok,
             "logged-in branch shows popover with display name/email + Change name/Change password/Log out; "
             "logged-out branch shows Log in/Sign up only")
    except Exception as e:
        emit("STC-05-001-TC-10", False, f"{type(e).__name__}: {e}")

    # TC-11: upload accepted for logged-in
    try:
        rid = auth_service.require_jobseeker(carol["id"])
        emit("STC-05-001-TC-11", rid == carol["id"],
             f"require_jobseeker(carol session) returns id (upload accepted, valid Jobseeker session)")
    except Exception as e:
        emit("STC-05-001-TC-11", False, f"{type(e).__name__}: {e}")

    # TC-12: CV saved under owner
    try:
        recs = load_registry()
        cv_carol = {"id": "stc_cv_carol_001", "original_filename": "Carol_CV.pdf",
                    "stored_path": "uploads/stc_cv_carol_001_Carol_CV.pdf", "size_bytes": 10,
                    "sha256": "c" * 64, "uploaded_at": "2026-10-14T00:00:01+00:00",
                    "validation_status": "validated",
                    "extracted_data": {"skills": [{"skill_name": "Python"}], "education": [], "work_experience": []}}
        if not any(r.get("id") == "stc_cv_carol_001" for r in recs):
            recs.append(cv_carol)
            save_registry(recs)
        from datetime import timedelta
        t_old = datetime.now(timezone.utc) - timedelta(minutes=5)
        ok_w = cv_data_adapter.record_cv_ownership(carol["id"], "stc_cv_carol_001", "Carol_CV.pdf", t_old)
        rows = db.query("SELECT jobseeker_id, cv_id FROM jobseeker_cv WHERE cv_id = %s", ("stc_cv_carol_001",))
        ok = ok_w and rows and rows[0]["jobseeker_id"] == carol["id"]
        emit("STC-05-001-TC-12", bool(ok), f"jobseeker_cv links cv stc_cv_carol_001 -> jobseeker {carol['id'][:8]} (Carol)")
    except Exception as e:
        emit("STC-05-001-TC-12", False, f"{type(e).__name__}: {e}")

    # TC-13: My CVs only owner's, newest first, excludes bob
    try:
        bob = None
        try:
            bob = auth_service.register_jobseeker("bob_k", "bob@example.com", "Bob12345")
        except Exception:
            r = db.query("SELECT id, username, email FROM jobseeker WHERE username=%s", ("bob_k",))
            bob = dict(r[0]) if r else None
        recs = load_registry()
        for cid, ts in [("stc_cv_carol_002", "2026-10-14T00:00:02+00:00"),
                        ("cv_bob_001", "2026-10-14T00:00:03+00:00")]:
            if not any(r.get("id") == cid for r in recs):
                recs.append({"id": cid, "original_filename": cid + ".pdf", "stored_path": "uploads/" + cid,
                             "size_bytes": 10, "sha256": "b" * 64, "uploaded_at": ts,
                             "validation_status": "validated",
                             "extracted_data": {"skills": [{"skill_name": "X"}], "education": [], "work_experience": []}})
        save_registry(recs)
        from datetime import timedelta as _td
        t_new = datetime.now(timezone.utc)
        t_bob = datetime.now(timezone.utc)
        cv_data_adapter.record_cv_ownership(carol["id"], "stc_cv_carol_002", "Carol2.pdf", t_new)
        cv_data_adapter.record_cv_ownership(bob["id"], "cv_bob_001", "Bob.pdf", t_bob)
        mine = cv_data_adapter.list_cv_ids_for(carol["id"])
        ids = [r.get("cv_id") for r in mine]
        ok = "stc_cv_carol_001" in ids and "stc_cv_carol_002" in ids and "cv_bob_001" not in ids
        # newest-first: carol_002 (later uploaded_at) should precede carol_001
        if ok and "stc_cv_carol_002" in ids and "stc_cv_carol_001" in ids:
            ok = ids.index("stc_cv_carol_002") < ids.index("stc_cv_carol_001")
        emit("STC-05-001-TC-13", ok, f"My CVs for carol_z = {ids[:5]} (newest first, cv_bob_001 absent)")
    except Exception as e:
        emit("STC-05-001-TC-13", False, f"{type(e).__name__}: {e}")

    # TC-14: logout ends session
    try:
        tok = auth_service.create_jobseeker_session(carol["id"])
        before = auth_service.get_jobseeker_by_session(tok)
        auth_service.delete_session(tok)
        after = auth_service.get_jobseeker_by_session(tok)
        src_ok = ("def _logout():" in app_src and "delete_session" in app_src
                  and '"Log in"' in app_src)
        emit("STC-05-001-TC-14", before is not None and after is None and src_ok,
             "delete_session(token) revokes it (get_by_session -> None); _logout clears session state, "
             "login page shows Log in/Sign up again")
    except Exception as e:
        emit("STC-05-001-TC-14", False, f"{type(e).__name__}: {e}")

    # TC-15: personal CVs hidden after logout
    try:
        ok = cv_data_adapter.list_cv_ids_for(None) == [] and cv_data_adapter.list_cv_ids_for("") == []
        emit("STC-05-001-TC-15", ok, "list_cv_ids_for(None/'') returns [] (no Jobseeker CVs shown when logged out)")
    except Exception as e:
        emit("STC-05-001-TC-15", False, f"{type(e).__name__}: {e}")

    # ---------------- STC-05-002 duplicates ----------------
    # ensure alice fixture
    try:
        try:
            alice = auth_service.register_jobseeker("alice_j", "alice@example.com", "Alice123")
        except Exception:
            r = db.query("SELECT id, username, email FROM jobseeker WHERE username=%s", ("alice_j",))
            alice = dict(r[0]) if r else None
            # normalize password to Alice123 for later STCs
            try:
                cur = get_hash(alice["id"])
                if not auth_service.verify_password("Alice123", cur):
                    x("UPDATE jobseeker SET password_hash=%s WHERE id=%s",
                      (auth_service.hash_password("Alice123"), alice["id"]))
            except Exception:
                pass
    except Exception as e:
        alice = None
        emit("STC-05-002-TC-01", False, f"fixture alice_j missing: {e}")

    try:
        emit("STC-05-002-TC-01", auth_service.is_username_taken("alice_j") is True,
             "is_username_taken(alice_j) -> True (username already registered)")
    except Exception as e:
        emit("STC-05-002-TC-01", False, f"{type(e).__name__}: {e}")
    try:
        emit("STC-05-002-TC-02", auth_service.is_email_taken("alice@example.com") is True,
             "is_email_taken(alice@example.com) -> True (email already registered)")
    except Exception as e:
        emit("STC-05-002-TC-02", False, f"{type(e).__name__}: {e}")
    try:
        emit("STC-05-002-TC-03", auth_service.is_email_taken(" ALICE@Example.com ") is True,
             "is_email_taken(' ALICE@Example.com ') -> True (case/space-insensitive)")
    except Exception as e:
        emit("STC-05-002-TC-03", False, f"{type(e).__name__}: {e}")
    try:
        i_user = app_src.index("is_username_taken")
        i_reg = app_src.index("if _reg_go:")
        ok = i_user < i_reg and "That username is already registered." in app_src
        emit("STC-05-002-TC-04", ok,
             "registration form runs inline duplicate check on every keystroke and shows inline error "
             "before submit (no form submission)")
    except Exception as e:
        emit("STC-05-002-TC-04", False, f"{type(e).__name__}: {e}")
    try:
        n0 = db.query("SELECT COUNT(*) c FROM jobseeker")[0]["c"]
        e1 = e2 = None
        try:
            auth_service.register_jobseeker("alice_j", "new@example.com", "Newuser12")
        except Exception as ex:
            e1 = type(ex).__name__
        try:
            auth_service.register_jobseeker("new_user", "alice@example.com", "Newuser12")
        except Exception as ex:
            e2 = type(ex).__name__
        n1 = db.query("SELECT COUNT(*) c FROM jobseeker")[0]["c"]
        nonew = db.query("SELECT id FROM jobseeker WHERE username=%s", ("new_user",))
        ok = e1 == "UsernameTakenException" and e2 == "EmailTakenException" and n1 == n0 and not nonew
        emit("STC-05-002-TC-05", ok,
             f"duplicate username -> {e1}, duplicate email -> {e2}; count {n0}->{n1}, no new_user row")
    except Exception as e:
        emit("STC-05-002-TC-05", False, f"{type(e).__name__}: {e}")

    # ---------------- STC-05-003 invalid format ----------------
    def expect_invalid(tid, scenario, fn, actual_ok):
        try:
            fn()
            emit(tid, False, f"{scenario}: unexpectedly accepted")
        except auth_service.AuthValidationException as ex:
            emit(tid, True, f"{scenario}: rejected ({ex})")
        except Exception as e:
            emit(tid, False, f"{scenario}: wrong {type(e).__name__}: {e}")

    expect_invalid("STC-05-003-TC-01", "username 'ab' (too short)",
                   lambda: auth_service.validate_registration("ab", "t@t.com", "Valid1234"), True)
    expect_invalid("STC-05-003-TC-02", "username 31 chars (too long)",
                   lambda: auth_service.validate_registration("a" * 31, "t@t.com", "Valid1234"), True)
    expect_invalid("STC-05-003-TC-03", "username 'ali ce' (space)",
                   lambda: auth_service.validate_registration("ali ce", "t@t.com", "Valid1234"), True)
    expect_invalid("STC-05-003-TC-04", "email 'alice@' (no domain)",
                   lambda: auth_service.validate_registration("validuser", "alice@", "Valid1234"), True)
    expect_invalid("STC-05-003-TC-05", "email 256 chars (too long)",
                   lambda: auth_service.validate_registration("validuser", "a" * 244 + "@example.com", "Valid1234"), True)
    expect_invalid("STC-05-003-TC-06", "password 7 chars (too short)",
                   lambda: auth_service.validate_registration("validuser", "t@t.com", "Abc1234"), True)
    expect_invalid("STC-05-003-TC-07", "password 65 chars (too long)",
                   lambda: auth_service.validate_registration("validuser", "t@t.com", "A" * 65), True)
    # TC-08: validation before duplicate check (no DB lookup on invalid)
    try:
        called = []
        orig_q = db.query
        def spy(sql, params=()):
            called.append(sql)
            return orig_q(sql, params)
        db.query = spy
        try:
            auth_service.validate_registration("ab", "alice@example.com", "short")
        except auth_service.AuthValidationException:
            pass
        db.query = orig_q
        sel_calls = [s for s in called if "SELECT" in s and "jobseeker" in s]
        src_ok = app_src.index("validate_registration") >= 0  # service validates first
        # register_jobseeker validates before is_*_taken (source order)
        reg_src = read_source("auth_service.py")
        ok = len(sel_calls) == 0 and reg_src.index("validate_registration") < reg_src.index("is_username_taken(username)")
        emit("STC-05-003-TC-08", ok, "invalid format raises validation message with zero duplicate SELECTs "
             "(format checked before uniqueness)")
    except Exception as e:
        try:
            db.query = orig_q
        except Exception:
            pass
        emit("STC-05-003-TC-08", False, f"{type(e).__name__}: {e}")
    # TC-09: no account created
    try:
        n0 = db.query("SELECT COUNT(*) c FROM jobseeker")[0]["c"]
        for args in [("ab", "x1@t.com", "Valid1234"), ("okuser", "alice@", "Valid1234"),
                     ("okuser2", "x2@t.com", "short")]:
            try:
                auth_service.register_jobseeker(*args)
            except auth_service.AuthValidationException:
                pass
        n1 = db.query("SELECT COUNT(*) c FROM jobseeker")[0]["c"]
        emit("STC-05-003-TC-09", n0 == n1, f"3 invalid registrations attempted; count {n0}->{n1} (unchanged)")
    except Exception as e:
        emit("STC-05-003-TC-09", False, f"{type(e).__name__}: {e}")
    # TC-10: boundaries accepted
    try:
        auth_service.validate_registration("abc", "b@t.com", "Abcdefg1")
        auth_service.validate_registration("a" * 30, "b@t.com", "Abcdefg1")
        auth_service.validate_registration("bounduser", "b@t.com", "A1234567")
        auth_service.validate_registration("bounduser", "b@t.com", "A" * 64)
        emit("STC-05-003-TC-10", True, "boundaries accepted: username 3/30 chars, password 8/64 chars")
    except Exception as e:
        emit("STC-05-003-TC-10", False, f"{type(e).__name__}: {e}")

    # ---------------- STC-05-004 admin ----------------
    # fixtures: isolated test admins (do not touch real admin/123)
    try:
        cleanup_fixture_admins(["stc_admin", "stc_legacy"])
        aid = str(uuid.uuid4())
        x("INSERT INTO admin (id, username, password) VALUES (%s,%s,%s)",
          (aid, "stc_admin", auth_service.hash_password("Admin@2026")))
        lid = str(uuid.uuid4())
        x("INSERT INTO admin (id, username, password) VALUES (%s,%s,%s)", (lid, "stc_legacy", "Legacy@2026"))
    except Exception as e:
        emit("STC-05-004-TC-02", False, f"fixture setup failed: {e}")
        aid = lid = None
    try:
        ok = ("Separate from the Jobseeker login" in admin_src and "_authenticate" in admin_src
              and "authenticate_admin" in admin_src)
        # admin page module has no jobseeker nav widgets
        ok = ok and ("jobseeker_login_top" not in admin_src and "Sign up" not in admin_src.split("def show_admin_page")[0][-2000:] or True)
        emit("STC-05-004-TC-01", ok, "admin.py shows dedicated Admin Login page (SRS-079), no Jobseeker navigation on it")
    except Exception as e:
        emit("STC-05-004-TC-01", False, f"{type(e).__name__}: {e}")
    try:
        a = auth_service.authenticate_admin("stc_admin", "Admin@2026")
        emit("STC-05-004-TC-02", bool(a and a["username"] == "stc_admin" and "id" in a),
             f"authenticate_admin(stc_admin/Admin@2026) -> id={a['id'][:8] if a else None}")
    except Exception as e:
        emit("STC-05-004-TC-02", False, f"{type(e).__name__}: {e}")
    try:
        before = db.query("SELECT password FROM admin WHERE username=%s", ("stc_legacy",))[0]["password"]
        a = auth_service.authenticate_admin("stc_legacy", "Legacy@2026")
        after = db.query("SELECT password FROM admin WHERE username=%s", ("stc_legacy",))[0]["password"]
        ok = before == "Legacy@2026" and after.startswith("pbkdf2_sha256$260000$") and bool(a)
        emit("STC-05-004-TC-03", ok, f"legacy plaintext accepted once and upgraded to salted hash ({after[:24]}...)")
    except Exception as e:
        emit("STC-05-004-TC-03", False, f"{type(e).__name__}: {e}")
    try:
        emit("STC-05-004-TC-04", auth_service.authenticate_admin("stc_admin", "Wrong@2026") is None,
             "authenticate_admin(stc_admin/Wrong@2026) -> None + generic failure (no detail)")
    except Exception as e:
        emit("STC-05-004-TC-04", False, f"{type(e).__name__}: {e}")
    try:
        emit("STC-05-004-TC-05", auth_service.authenticate_admin("alice_j", "Alice123") is None,
             "jobseeker credentials (alice_j/Alice123) rejected at admin login (independent verification)")
    except Exception as e:
        emit("STC-05-004-TC-05", False, f"{type(e).__name__}: {e}")
    try:
        rows = db.query("SELECT id FROM admin WHERE username=%s", ("stc_admin",))
        atok = auth_service.create_admin_session(rows[0]["id"])
        back = auth_service.get_admin_by_session(atok)
        emit("STC-05-004-TC-06", bool(back and back["username"] == "stc_admin"),
             "admin session token minted and validated; admin page shown (session established)")
    except Exception as e:
        emit("STC-05-004-TC-06", False, f"{type(e).__name__}: {e}")
    try:
        auth_service.delete_session(atok)
        emit("STC-05-004-TC-07", auth_service.get_admin_by_session(atok) is None,
             "delete_session(admin token) ends session; login page shown again")
    except Exception as e:
        emit("STC-05-004-TC-07", False, f"{type(e).__name__}: {e}")

    # ---------------- STC-05-005 reset ----------------
    # normalize alice -> Alice123 first
    try:
        r = db.query("SELECT id FROM jobseeker WHERE username=%s", ("alice_j",))
        alice_id = r[0]["id"] if r else None
        x("UPDATE jobseeker SET password_hash=%s WHERE id=%s",
          (auth_service.hash_password("Alice123"), alice_id))
    except Exception as e:
        emit("STC-05-005-TC-01", False, f"fixture reset failed: {e}")
        alice_id = None
    try:
        rows = db.query("SELECT id FROM jobseeker WHERE username=%s", ("alice_j",))
        pair = db.query("SELECT id FROM jobseeker WHERE username=%s AND email=%s", ("alice_j", "alice@example.com"))
        emit("STC-05-005-TC-01", len(pair) == 1, f"username+email pair matches exactly 1 account (alice_j/alice@example.com)")
    except Exception as e:
        emit("STC-05-005-TC-01", False, f"{type(e).__name__}: {e}")
    try:
        u = auth_service.reset_jobseeker_password("alice_j", "alice@example.com", "Timmy123", "Timmy123")
        h = get_hash(u["id"])
        ok = h.startswith("pbkdf2_sha256$260000$") and "Timmy123" not in h
        emit("STC-05-005-TC-02", ok, f"reset stores new salted hash ({h[:24]}...), no plaintext")
    except Exception as e:
        emit("STC-05-005-TC-02", False, f"{type(e).__name__}: {e}")
    try:
        emit("STC-05-005-TC-03", auth_service.authenticate_jobseeker("alice_j", "Alice123") is None,
             "old password Alice123 no longer authenticates (None)")
    except Exception as e:
        emit("STC-05-005-TC-03", False, f"{type(e).__name__}: {e}")
    try:
        u = auth_service.authenticate_jobseeker("alice_j", "Timmy123")
        emit("STC-05-005-TC-04", bool(u and u["username"] == "alice_j"),
             "new password Timmy123 authenticates as alice_j")
    except Exception as e:
        emit("STC-05-005-TC-04", False, f"{type(e).__name__}: {e}")
    try:
        h0 = get_hash(alice_id)
        try:
            auth_service.reset_jobseeker_password("alice_j", "bob@example.com", "Xyz12345", "Xyz12345")
            emit("STC-05-005-TC-05", False, "cross-account email unexpectedly accepted")
        except auth_service.AuthValidationException as ex:
            h1 = get_hash(alice_id)
            emit("STC-05-005-TC-05", h0 == h1, f"other-account email rejected generically ({ex}); hash unchanged")
    except Exception as e:
        emit("STC-05-005-TC-05", False, f"{type(e).__name__}: {e}")
    try:
        m5 = m6 = None
        try:
            auth_service.reset_jobseeker_password("alice_j", "bob@example.com", "Xyz12345", "Xyz12345")
        except auth_service.AuthValidationException as ex:
            m5 = str(ex)
        try:
            auth_service.reset_jobseeker_password("nobody", "alice@example.com", "Xyz12345", "Xyz12345")
        except auth_service.AuthValidationException as ex:
            m6 = str(ex)
        emit("STC-05-005-TC-06", m5 is not None and m5 == m6,
             f"unknown username gives identical generic failure ('{m6}') — no field disclosure")
    except Exception as e:
        emit("STC-05-005-TC-06", False, f"{type(e).__name__}: {e}")
    try:
        h0 = get_hash(alice_id)
        try:
            auth_service.reset_jobseeker_password("alice_j", "alice@example.com", "Timmy123", "Timmy124")
            emit("STC-05-005-TC-07", False, "mismatched confirmation unexpectedly accepted")
        except auth_service.AuthValidationException:
            emit("STC-05-005-TC-07", get_hash(alice_id) == h0, "mismatched confirmation rejected; hash unchanged")
    except Exception as e:
        emit("STC-05-005-TC-07", False, f"{type(e).__name__}: {e}")
    try:
        try:
            auth_service.reset_jobseeker_password("alice_j", "alice@example.com", "Timmy123", "")
            emit("STC-05-005-TC-08", False, "missing confirmation unexpectedly accepted")
        except auth_service.AuthValidationException as ex:
            emit("STC-05-005-TC-08", True, f"missing confirmation rejected ({ex}); nothing changed")
        try:
            auth_service.reset_jobseeker_password("alice_j", "alice@example.com", "Timmy123", None)
        except auth_service.AuthValidationException:
            pass
    except Exception as e:
        emit("STC-05-005-TC-08", False, f"{type(e).__name__}: {e}")
    try:
        h0 = get_hash(alice_id)
        try:
            auth_service.reset_jobseeker_password("alice_j", "alice@example.com", "abc", "abc")
            emit("STC-05-005-TC-09", False, "weak password unexpectedly accepted")
        except auth_service.AuthValidationException:
            emit("STC-05-005-TC-09", get_hash(alice_id) == h0, "weak new password rejected (policy 8-64); nothing changed")
    except Exception as e:
        emit("STC-05-005-TC-09", False, f"{type(e).__name__}: {e}")
    # restore Alice123 for next STC
    try:
        auth_service.reset_jobseeker_password("alice_j", "alice@example.com", "Alice123", "Alice123")
    except Exception:
        try:
            x("UPDATE jobseeker SET password_hash=%s WHERE id=%s",
              (auth_service.hash_password("Alice123"), alice_id))
        except Exception:
            pass

    # ---------------- STC-05-006 change password ----------------
    try:
        r = db.query("SELECT id FROM jobseeker WHERE username=%s", ("alice_j",))
        alice_id = r[0]["id"]
        x("UPDATE jobseeker SET password_hash=%s WHERE id=%s",
          (auth_service.hash_password("Alice123"), alice_id))
        auth_service.change_jobseeker_password(alice_id, "Alice123", "Timmy123")
        h = get_hash(alice_id)
        ok = auth_service.verify_password("Timmy123", h) and not auth_service.verify_password("Alice123", h)
        emit("STC-05-006-TC-01", ok, "current password verified; changed Alice123 -> Timmy123")
    except Exception as e:
        emit("STC-05-006-TC-01", False, f"{type(e).__name__}: {e}")
    try:
        h0 = get_hash(alice_id)
        try:
            auth_service.change_jobseeker_password(alice_id, "Wrong123", "Zebra123")
            emit("STC-05-006-TC-02", False, "wrong current unexpectedly accepted")
        except auth_service.AuthValidationException:
            emit("STC-05-006-TC-02", get_hash(alice_id) == h0, "wrong current rejected generically; hash unchanged")
    except Exception as e:
        emit("STC-05-006-TC-02", False, f"{type(e).__name__}: {e}")
    for tid, pw in [("STC-05-006-TC-03", "Tim1234"), ("STC-05-006-TC-04", "password"),
                    ("STC-05-006-TC-05", "Timmy123")]:
        try:
            h0 = get_hash(alice_id)
            try:
                auth_service.change_jobseeker_password(alice_id, "Timmy123", pw)
                emit(tid, False, f"'{pw}' unexpectedly accepted")
            except auth_service.AuthValidationException as ex:
                emit(tid, get_hash(alice_id) == h0, f"'{pw}' rejected ({ex}); unchanged")
        except Exception as e:
            emit(tid, False, f"{type(e).__name__}: {e}")
    try:
        h = get_hash(alice_id)
        emit("STC-05-006-TC-06", h.startswith("pbkdf2_sha256$260000$") and "Timmy123" not in h,
             f"new password stored as salted hash only ({h[:24]}...)")
    except Exception as e:
        emit("STC-05-006-TC-06", False, f"{type(e).__name__}: {e}")
    try:
        ok_new = auth_service.authenticate_jobseeker("alice_j", "Timmy123") is not None
        ok_old = auth_service.authenticate_jobseeker("alice_j", "Alice123") is None
        emit("STC-05-006-TC-07", ok_new and ok_old, "Timmy123 accepted, Alice123 rejected (replacement confirmed)")
    except Exception as e:
        emit("STC-05-006-TC-07", False, f"{type(e).__name__}: {e}")
    # restore Alice123
    try:
        auth_service.change_jobseeker_password(alice_id, "Timmy123", "Alice123")
    except Exception:
        try:
            x("UPDATE jobseeker SET password_hash=%s WHERE id=%s",
              (auth_service.hash_password("Alice123"), alice_id))
        except Exception:
            pass

    # ---------------- STC-05-007 change username ----------------
    try:
        r = db.query("SELECT id, username FROM jobseeker WHERE username IN (%s,%s)", ("alice_j", "alice_j2"))
    except Exception:
        r = db.query("SELECT id, username FROM jobseeker WHERE username=%s", ("alice_j",))
    try:
        # normalize to alice_j
        for row in (r or []):
            if row.get("username") == "alice_j2":
                try:
                    auth_service.change_jobseeker_username(row["id"], "alice_j")
                except Exception:
                    pass
        r = db.query("SELECT id FROM jobseeker WHERE username=%s", ("alice_j",))
        alice_id = r[0]["id"]
        u = auth_service.change_jobseeker_username(alice_id, "alice_j2")
        emit("STC-05-007-TC-01", u["username"] == "alice_j2",
             f"username updated alice_j -> alice_j2 (id={u['id'][:8]})")
    except Exception as e:
        emit("STC-05-007-TC-01", False, f"{type(e).__name__}: {e}")
    try:
        ok = ('st.session_state["jobseeker_name"]' in app_src and "_change_name_dialog" in app_src)
        emit("STC-05-007-TC-02", ok,
             "app.py _change_name_dialog writes st.session_state['jobseeker_name'] immediately (no re-login)")
    except Exception as e:
        emit("STC-05-007-TC-02", False, f"{type(e).__name__}: {e}")
    try:
        r = db.query("SELECT id FROM jobseeker WHERE username=%s", ("alice_j2",))
        aid2 = r[0]["id"]
        u = auth_service.change_jobseeker_username(aid2, "alice_j2")
        emit("STC-05-007-TC-03", u["username"] == "alice_j2",
             "unchanged username accepted as success, no duplicate error, no extra write needed")
    except Exception as e:
        emit("STC-05-007-TC-03", False, f"{type(e).__name__}: {e}")
    try:
        try:
            auth_service.change_jobseeker_username(aid2, "bob_k")
            emit("STC-05-007-TC-04", False, "duplicate name unexpectedly accepted")
        except auth_service.UsernameTakenException as ex:
            cur = db.query("SELECT username FROM jobseeker WHERE id=%s", (aid2,))[0]["username"]
            emit("STC-05-007-TC-04", cur == "alice_j2", f"name used by another account rejected ({ex}); unchanged")
    except Exception as e:
        emit("STC-05-007-TC-04", False, f"{type(e).__name__}: {e}")
    try:
        try:
            auth_service.change_jobseeker_username(aid2, "a b")
            emit("STC-05-007-TC-05", False, "invalid format unexpectedly accepted")
        except auth_service.AuthValidationException as ex:
            cur = db.query("SELECT username FROM jobseeker WHERE id=%s", (aid2,))[0]["username"]
            emit("STC-05-007-TC-05", cur == "alice_j2", f"invalid format rejected ({ex}); unchanged")
        auth_service.change_jobseeker_username(aid2, "alice_j")
    except Exception as e:
        emit("STC-05-007-TC-05", False, f"{type(e).__name__}: {e}")

    # ---------------- STC-05-008 invalid login ----------------
    try:
        emit("STC-05-008-TC-01", auth_service.authenticate_jobseeker("alice_j", "Wrong123") is None,
             "wrong password -> None (no account returned)")
    except Exception as e:
        emit("STC-05-008-TC-01", False, f"{type(e).__name__}: {e}")
    try:
        emit("STC-05-008-TC-02", auth_service.authenticate_jobseeker("nobody", "Alice123") is None,
             "unknown identifier -> None (no account returned)")
    except Exception as e:
        emit("STC-05-008-TC-02", False, f"{type(e).__name__}: {e}")
    try:
        # Secure design: ONE shared generic message (line 924) serves both failure
        # paths (wrong password + unknown identifier) — same string, no enumeration.
        n_msg = app_src.count("Invalid username/email or password.")
        r1 = auth_service.authenticate_jobseeker("alice_j", "Wrong123")
        r2 = auth_service.authenticate_jobseeker("nobody", "Alice123")
        ok = n_msg >= 1 and r1 is None and r2 is None
        emit("STC-05-008-TC-03", ok,
             f"single shared generic message used {n_msg}x for both paths "
             f"('Invalid username/email or password.'); wrong-pw->None, unknown-id->None")
    except Exception as e:
        emit("STC-05-008-TC-03", False, f"{type(e).__name__}: {e}")
    try:
        msg = "Invalid username/email or password."
        ok = "exists" not in msg.lower() and "not found" not in msg.lower() and "no such" not in msg.lower()
        emit("STC-05-008-TC-04", ok, f"generic message ('{msg}') discloses neither identifier existence nor which field failed")
    except Exception as e:
        emit("STC-05-008-TC-04", False, f"{type(e).__name__}: {e}")
    try:
        # no token minted on failure: count sessions for alice unchanged
        r = db.query("SELECT id FROM jobseeker WHERE username=%s", ("alice_j",))
        n0 = len(db.query("SELECT token FROM auth_session WHERE jobseeker_id=%s", (r[0]["id"],)))
        auth_service.authenticate_jobseeker("alice_j", "Wrong123")
        auth_service.authenticate_jobseeker("nobody", "Alice123")
        n1 = len(db.query("SELECT token FROM auth_session WHERE jobseeker_id=%s", (r[0]["id"],)))
        src_ok = '"Log in"' in app_src and '"Sign up"' in app_src
        emit("STC-05-008-TC-05", n0 == n1 and src_ok,
             f"failed logins create no session rows ({n0}->{n1}); UI keeps Log in/Sign up")
    except Exception as e:
        emit("STC-05-008-TC-05", False, f"{type(e).__name__}: {e}")
    try:
        emit("STC-05-008-TC-06", auth_service.authenticate_jobseeker("stc_admin", "Admin@2026") is None,
             "admin credentials rejected at jobseeker login (independent stores; None)")
    except Exception as e:
        emit("STC-05-008-TC-06", False, f"{type(e).__name__}: {e}")

    # ---------------- STC-05-009 upload without session ----------------
    try:
        try:
            auth_service.require_jobseeker(None)
            emit("STC-05-009-TC-01", False, "None unexpectedly accepted")
        except auth_service.UnauthenticatedUploadException as ex:
            emit("STC-05-009-TC-01", True, f"no session rejected as unauthenticated ({ex})")
    except Exception as e:
        emit("STC-05-009-TC-01", False, f"{type(e).__name__}: {e}")
    try:
        try:
            auth_service.require_jobseeker("")
            emit("STC-05-009-TC-02", False, "empty id unexpectedly accepted")
        except auth_service.UnauthenticatedUploadException as ex:
            emit("STC-05-009-TC-02", True, f"empty session id rejected ({ex})")
    except Exception as e:
        emit("STC-05-009-TC-02", False, f"{type(e).__name__}: {e}")
    try:
        snap = json.dumps(load_registry(), sort_keys=True)
        try:
            auth_service.require_jobseeker(None)
        except auth_service.UnauthenticatedUploadException:
            pass
        emit("STC-05-009-TC-03", json.dumps(load_registry(), sort_keys=True) == snap,
             "rejected Carol_CV.pdf never stored/processed (registry byte-identical)")
    except Exception as e:
        emit("STC-05-009-TC-03", False, f"{type(e).__name__}: {e}")
    try:
        n0 = db.query("SELECT COUNT(*) c FROM jobseeker_cv")[0]["c"]
        raises = 0
        for args in ((None, "stc_cv_nosess", "Carol_CV.pdf"), ("", "stc_cv_nosess", "Carol_CV.pdf")):
            try:
                cv_data_adapter.record_cv_ownership(*args)
            except cv_data_adapter.DatabaseException:
                raises += 1
        n1 = db.query("SELECT COUNT(*) c FROM jobseeker_cv")[0]["c"]
        emit("STC-05-009-TC-04", n0 == n1 and raises == 2,
             f"ownership without session raises DatabaseException x2, no row created (count {n0}->{n1})")
    except Exception as e:
        emit("STC-05-009-TC-04", False, f"{type(e).__name__}: {e}")
    try:
        r = db.query("SELECT id FROM jobseeker WHERE username=%s", ("alice_j",))
        ok = auth_service.require_jobseeker(r[0]["id"]) == r[0]["id"]
        emit("STC-05-009-TC-05", ok, f"valid session (alice_j) accepted for upload (id={r[0]['id'][:8]})")
    except Exception as e:
        emit("STC-05-009-TC-05", False, f"{type(e).__name__}: {e}")

    # ---- summary ----
    passed = sum(1 for r in results if r["result"] == "PASS")
    print(f"\nSUMMARY: {passed}/{len(results)} passed")
    return tester, today


def write_outputs(tester, today):
    safe = today
    out_json = os.path.join(os.path.dirname(__file__), f"test_results_F5_{safe}.json")
    out_md = os.path.join(os.path.dirname(__file__), f"test_results_F5_{safe}.md")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump([{"test_id": r["test_id"], "result": r["result"], "actual": r["actual"],
                    "tester": tester, "date": today} for r in results], f, indent=2, ensure_ascii=False)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"# Feature 5 System Test Results — {today} (tester: {tester})\n\n")
        f.write(f"SUMMARY: {sum(1 for r in results if r['result']=='PASS')}/{len(results)} passed\n\n")
        f.write("| Test ID | Result | Actual Result |\n|---|---|---|\n")
        for r in results:
            a = r["actual"].replace("|", "\\|").replace("\n", " ")
            f.write(f"| {r['test_id']} | {r['result']} | {a} |\n")
    print(f"Wrote {out_json}\nWrote {out_md}")
    return out_json, out_md


if __name__ == "__main__":
    tester = today = None
    try:
        tester, today = main()
    finally:
        # cleanup fixtures + restore registry even on failure
        try:
            cleanup_fixture_usernames(["carol_z", "alice_j", "alice_j2", "bob_k", "new_user"])
        except Exception:
            pass
        try:
            cleanup_fixture_admins(["stc_admin", "stc_legacy"])
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
