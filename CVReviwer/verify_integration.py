"""
verify_integration.py — end-to-end check of the Feature 1 / 2 / 3 integration

Runs the real pipeline against the real database and, optionally, the real AI
service, then reports what works and what does not. Read-only apart from one
CV it uploads and can clean up afterwards.

    python verify_integration.py                 # full check, uploads a test CV
    python verify_integration.py --no-ai         # skip anything costing API calls
    python verify_integration.py --keep          # leave the test CV in place
    python verify_integration.py --cv path.pdf   # use a real CV instead

WHY THIS EXISTS
===============
Every test in tests/ runs against fakes: an in-memory stand-in for db.py and a
temp-file CV registry. That is the right thing for a test suite — fast, no
configuration, no cost — but it means nothing in the project has ever touched
a real MySQL server, a real PDF pipeline and a real OpenAI call in one go.
This script is what closes that gap, and it should be run once after setup and
again after any schema change.

It checks, in dependency order:

    1.  database reachable                     db.py / M-01-29
    2.  Feature 1 schema present
    3.  Feature 2 schema present
    4.  job listings exist                     Feature 1 has scraped something
    5.  enrichment coverage                    enrich_jobs.py has run
    6.  active listings visible to matching    M-02-02 / SRS-048
    7.  CV upload chain                        M-03-01, 04, 05, 06
    8.  sensitive-data masking                 M-03-11, 12, 13
    9.  AI extraction                          stands in for M-03-07 / M-03-14
    10. extraction validated and stored        M-03-08, M-03-09, M-03-10
    11. CV data readable by Feature 2          M-02-01
    12. matching, ranking, persistence         M-02-02 .. M-02-09
    13. results readable for display           M-02-10
    14. posting links usable                   M-02-11 / SRS-062
    15. ownership index                        Feature 5 groundwork

Exit code is 0 when every required check passes, 1 otherwise, so it can gate a
deployment.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import traceback
from datetime import datetime, timezone

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
_results: list[tuple[str, str, str]] = []


def record(status, label, detail=""):
    _results.append((status, label, detail))
    symbol = {PASS: "  PASS ", FAIL: "  FAIL ", WARN: "  WARN ", SKIP: "  SKIP "}[status]
    print(f"{symbol}{label}" + (f"\n         {detail}" if detail else ""))
    return status == PASS


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


def _stub_heavy_imports():
    """
    Stand in for the ML packages embed.py imports at module level.

    embed.py imports SentenceTransformer and tqdm at the top of the file even
    though only its batch pipeline uses them, so importing it to reach any
    M-03 method loads the whole ML stack — and fails outright if it is not
    installed. None of the methods this script exercises touch them. Recorded
    in TBD_and_Conflicts.md Part 4; stubbed here so a missing ML stack does
    not stop the integration check.
    """
    for name, build in (
        ("sentence_transformers", lambda: _stub_module(
            "sentence_transformers", SentenceTransformer=type(
                "SentenceTransformer", (), {
                    "__init__": lambda self, *a, **k: None,
                    "encode": lambda self, *a, **k: (_ for _ in ()).throw(
                        NotImplementedError("stubbed")),
                }))),
        ("tqdm", lambda: _stub_module("tqdm", tqdm=lambda it=None, *a, **k: it)),
    ):
        if name in sys.modules:
            continue
        try:
            __import__(name)
        except ImportError:
            build()


def _stub_module(name, **attributes):
    import types as _types
    module = _types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _make_test_pdf(text):
    """
    A minimal one-page PDF with extractable text, built with pikepdf.

    The text is wrapped across lines rather than truncated: an earlier version
    wrote only the first 60 characters, so the email and phone number never
    reached the page and the masking check silently had nothing to detect. A
    check that passes because it was given nothing to do is worse than no
    check at all.
    """
    import pikepdf
    from pikepdf import Name, Dictionary, Array

    wrapped, current = [], ""
    for word in text.split():
        if len(current) + len(word) + 1 > 70:
            wrapped.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        wrapped.append(current)

    def _escape(value):
        return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    body = ("BT /F1 11 Tf 40 750 Td 16 TL\n"
            + "\n".join(f"({_escape(line)}) Tj T*" for line in wrapped)
            + "\nET")

    pdf = pikepdf.Pdf.new()
    stream = pdf.make_stream(body.encode("latin-1", "replace"))
    font = pdf.make_indirect(Dictionary(
        Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica))
    page = pdf.make_indirect(Dictionary(
        Type=Name.Page, MediaBox=Array([0, 0, 612, 792]), Contents=stream,
        Resources=Dictionary(Font=Dictionary(F1=font))))
    pdf.pages.append(pikepdf.Page(page))
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


class _UploadedFile:
    """Mimics the Streamlit UploadedFile the M-03 methods expect."""

    def __init__(self, name, data, mime="application/pdf"):
        self.name = name
        self.type = mime
        self._data = data

    def getvalue(self):
        return self._data

    def read(self):
        return self._data


SAMPLE_CV = (
    "Somchai Jaidee - Software Engineer. "
    "Email somchai.j@example.com Phone 081-234-5678. "
    "Skills: Python, JavaScript, React, SQL, REST APIs. "
    "Education: Bachelor of Science in Computer Science, Chiang Mai University, 2019-2023. "
    "Experience: Software Developer at Acme Co, 2021 to 2024."
)


def main():
    parser = argparse.ArgumentParser(description="End-to-end integration check.")
    parser.add_argument("--no-ai", action="store_true",
                        help="skip the steps that call OpenAI")
    parser.add_argument("--keep", action="store_true",
                        help="leave the uploaded test CV in place")
    parser.add_argument("--cv", metavar="PATH", default=None,
                        help="use a real PDF instead of the generated sample")
    args = parser.parse_args()

    _stub_heavy_imports()

    print("CVision — end-to-end integration check")
    print(f"Started {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")

    # ---------------------------------------------------------------
    section("1-3. Storage")
    # ---------------------------------------------------------------
    try:
        import db
    except ImportError as ex:
        record(FAIL, "db.py importable", str(ex))
        return _summary()

    try:
        db.query("SELECT 1")
        record(PASS, "database reachable (M-01-29)",
               f"{os.environ.get('DB_USER', 'root')}@"
               f"{os.environ.get('DB_HOST', 'localhost')}/"
               f"{os.environ.get('DB_NAME', 'cvision')}")
    except Exception as ex:
        record(FAIL, "database reachable (M-01-29)",
               getattr(ex, "detail", None) or str(ex))
        print("\n  Check the DB_* values in .env and that MySQL is running.")
        print(f"  Settings in effect: {db.describe_settings()}")
        return _summary()

    tables = {row["TABLE_NAME"].lower() if "TABLE_NAME" in row else
              list(row.values())[0].lower()
              for row in db.query(
                  "SELECT TABLE_NAME FROM information_schema.tables "
                  "WHERE table_schema = DATABASE()")}

    for table in ("admin", "provider_profile", "scraper", "schedule",
                  "job_listing", "log_entry"):
        record(PASS if table in tables else FAIL,
               f"Feature 1 table `{table}`",
               "" if table in tables else "run schema.sql")

    for table in ("job_enrichment", "job_match", "jobseeker_cv"):
        record(PASS if table in tables else FAIL,
               f"Feature 2 table `{table}`",
               "" if table in tables else "run schema_f2.sql")

    if "education_requirement" not in {
        c["COLUMN_NAME"] if "COLUMN_NAME" in c else list(c.values())[0]
        for c in db.query("SELECT COLUMN_NAME FROM information_schema.columns "
                          "WHERE table_schema = DATABASE() AND table_name = 'job_enrichment'")
    }:
        record(WARN, "job_enrichment.education_requirement present",
               "older schema; re-run schema_f2.sql for structured education matching")
    else:
        record(PASS, "job_enrichment.education_requirement present")

    # ---------------------------------------------------------------
    section("4-6. Job data")
    # ---------------------------------------------------------------
    listing_count = db.query("SELECT COUNT(*) AS n FROM job_listing")[0]["n"]
    record(PASS if listing_count else FAIL, f"job listings present ({listing_count})",
           "" if listing_count else "run a scraper from the admin panel first")

    enriched_count = db.query("SELECT COUNT(*) AS n FROM job_enrichment")[0]["n"]
    if not enriched_count:
        record(FAIL, "enrichment present (0)",
               "run: python enrich_jobs.py")
    elif enriched_count < listing_count:
        record(WARN, f"enrichment coverage ({enriched_count}/{listing_count})",
               "un-enriched listings are invisible to matching; run enrich_jobs.py")
    else:
        record(PASS, f"enrichment coverage ({enriched_count}/{listing_count})")

    import match_service
    try:
        active = match_service.retrieve_active_job_listings()
        if active:
            record(PASS, f"active listings for matching ({len(active)}) (M-02-02)")
        else:
            record(FAIL, "active listings for matching (0) (M-02-02)",
                   "every listing is outdated or un-enriched — nothing to match against")
    except Exception as ex:
        record(FAIL, "active listings for matching (M-02-02)", str(ex))
        active = []

    # ---------------------------------------------------------------
    section("7-10. CV pipeline (Feature 3)")
    # ---------------------------------------------------------------
    import cv_upload
    import embed
    import cv_data_adapter

    if args.cv:
        with open(args.cv, "rb") as fh:
            payload = fh.read()
        uploaded = _UploadedFile(os.path.basename(args.cv), payload)
    else:
        try:
            uploaded = _UploadedFile("integration_check.pdf", _make_test_pdf(SAMPLE_CV))
        except Exception as ex:
            record(FAIL, "build a test PDF", f"{ex} — pass --cv PATH instead")
            return _summary()

    cv_id = None
    try:
        upload = cv_upload.uploadCVFile(uploaded, "John Doe")
        cv_id = upload["cvFileId"]
        record(PASS, "CV validated and stored (M-03-01 -> 04, 05)", f"cv_id={cv_id}")
    except Exception as ex:
        record(FAIL, "CV validated and stored (M-03-01)", str(ex))
        return _summary()

    try:
        raw_text = cv_upload.extractTextFromCV(cv_id)
        record(PASS, f"text extracted (M-03-06)", f"{len(raw_text)} characters")
    except Exception as ex:
        record(FAIL, "text extracted (M-03-06)", str(ex))
        return _summary(cv_id, args.keep)

    try:
        detected = embed.detectSensitiveInfo(raw_text)
        masked = embed.maskSensitiveInfo(raw_text, detected)
        embed.verifySensitiveDataProtection(masked.sanitizedText, detected)
        found = [name for name, value in (
            ("email", detected.emailOriginal), ("phone", detected.phoneOriginal),
            ("address", detected.addressOriginal),
            ("ID", detected.identificationOriginal)) if value]
        record(PASS, "sensitive data masked (M-03-11, 12, 13)",
               f"detected: {', '.join(found) if found else 'nothing'}")
        # Known limitation, recorded in TBD_and_Conflicts.md Part 4.
        if "somchai.j@example.com" in raw_text and not detected.emailOriginal:
            record(WARN, "email detection", "an email in the CV was not detected")
        if not args.cv and not detected.phoneOriginal:
            record(WARN, "phone detection",
                   "the Thai phone number was not detected, so it is not masked "
                   "(known Feature 3 issue: US-centric regex, UT-3-11-004)")
    except Exception as ex:
        record(FAIL, "sensitive data masked (M-03-11, 12, 13)", str(ex))
        return _summary(cv_id, args.keep)

    if args.no_ai:
        record(SKIP, "AI extraction (--no-ai)")
        record(SKIP, "extraction stored (M-03-08, M-03-09)")
        return _summary(cv_id, args.keep)

    if not os.getenv("OPENAI_API_KEY"):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
    if not os.getenv("OPENAI_API_KEY"):
        record(FAIL, "OPENAI_API_KEY available", "set it in .env or use --no-ai")
        return _summary(cv_id, args.keep)

    try:
        # Imported here so --no-ai does not need streamlit installed.
        import app
        result = app._extract_structured_info(cv_id, masked.sanitizedText)
        record(PASS, "AI extraction (stands in for M-03-07 / M-03-14)",
               f"{len(result.skills)} skills, {len(result.education)} education, "
               f"{len(result.workExperience)} experience")
        if not result.skills:
            record(WARN, "skills extracted", "no skills came back from the model")
    except Exception as ex:
        record(FAIL, "AI extraction", f"{type(ex).__name__}: {ex}")
        return _summary(cv_id, args.keep)

    try:
        cv_upload.validateExtractionResult(result)
        cv_upload.storeExtractedCVInfo(cv_id, result)
        shown = embed.displayExtractedCVInfo(cv_id)
        record(PASS, "extraction validated, stored and displayable "
                     "(M-03-08, M-03-09, M-03-10)",
               f"categories: {', '.join(k for k in shown if shown.get(k))}")
    except Exception as ex:
        record(FAIL, "extraction validated and stored (M-03-08, M-03-09)", str(ex))
        return _summary(cv_id, args.keep)

    # ---------------------------------------------------------------
    section("11-15. Matching (Feature 2)")
    # ---------------------------------------------------------------
    import match_controller

    try:
        cv_data = match_controller.retrieve_cv_data(cv_id)
        record(PASS, "CV data readable by Feature 2 (M-02-01)",
               f"available: {', '.join(cv_data_adapter.available_categories(cv_data))}")
    except Exception as ex:
        record(FAIL, "CV data readable by Feature 2 (M-02-01)", str(ex))
        return _summary(cv_id, args.keep)

    try:
        ranked = match_controller.generate_job_matches(cv_id)
        if ranked:
            top = ranked[0]
            record(PASS, f"matched, ranked and stored ({len(ranked)}) (M-02-02 .. M-02-09)",
                   f"top: {top.score:.3f} with {len(top.matched_skills)} matched skill(s)")
        else:
            record(WARN, "matched, ranked and stored (0)",
                   "no active listings — SRS-057's empty state")
    except Exception as ex:
        record(FAIL, "matched, ranked and stored (M-02-02 .. M-02-09)",
               f"{type(ex).__name__}: {ex}")
        return _summary(cv_id, args.keep)

    try:
        rows = match_controller.display_job_match_results(cv_id)
        ordered = [r["rank_position"] for r in rows] == list(range(1, len(rows) + 1))
        in_range = all(0.0 <= float(r["match_score"]) <= 1.0 for r in rows)
        record(PASS if ordered and in_range else FAIL,
               f"results readable in rank order ({len(rows)}) (M-02-10)",
               "" if ordered and in_range else
               "rank positions or scores are out of order/range")
    except Exception as ex:
        record(FAIL, "results readable (M-02-10)", str(ex))
        rows = []

    unusable = 0
    for row in rows:
        try:
            match_controller.open_job_posting(row.get("url"))
        except match_controller.JobPostingUnavailableException:
            unusable += 1
    if rows:
        record(PASS if unusable == 0 else WARN,
               f"posting links usable ({len(rows) - unusable}/{len(rows)}) (M-02-11)",
               "" if unusable == 0 else
               f"{unusable} listing(s) have unusable URLs; SRS-062 disables just those cards")

    owned = cv_data_adapter.list_cv_ids_for("John Doe")
    record(PASS if any(r["cv_id"] == cv_id for r in owned) else WARN,
           f"ownership index updated ({len(owned)} CV(s))",
           "" if owned else "record_cv_ownership did not write a row")

    return _summary(cv_id, args.keep)


def _summary(cv_id=None, keep=False):
    if cv_id and not keep:
        try:
            import db
            import cv_upload
            db.execute("DELETE FROM job_match WHERE cv_id = %s", (cv_id,))
            db.execute("DELETE FROM jobseeker_cv WHERE cv_id = %s", (cv_id,))
            records = cv_upload._load_cvs()
            remaining = [r for r in records if r.get("id") != cv_id]
            removed = next((r for r in records if r.get("id") == cv_id), None)
            cv_upload._save_cvs(remaining)
            if removed and os.path.exists(removed.get("stored_path", "")):
                os.remove(removed["stored_path"])
            print(f"\n  Cleaned up test CV {cv_id}")
        except Exception as ex:
            print(f"\n  Could not fully clean up test CV {cv_id}: {ex}")

    counts = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}
    for status, _, _ in _results:
        counts[status] += 1

    print(f"\n{'=' * 58}")
    print(f"  PASS {counts[PASS]}   FAIL {counts[FAIL]}   "
          f"WARN {counts[WARN]}   SKIP {counts[SKIP]}")
    if counts[FAIL]:
        print("\n  Failed checks:")
        for status, label, detail in _results:
            if status == FAIL:
                print(f"    - {label}" + (f": {detail}" if detail else ""))
    if counts[WARN]:
        print("\n  Warnings (not fatal):")
        for status, label, detail in _results:
            if status == WARN:
                print(f"    - {label}" + (f": {detail}" if detail else ""))
    print(f"{'=' * 58}")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(1)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)