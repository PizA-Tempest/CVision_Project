"""Shared test helpers for the Feature 2 (Job Matching) suite.

Feature 2 talks to MySQL through db.py. These helpers install an in-memory
stand-in for it before match_service is imported, so the suite runs with no
database and no configuration — the same property Feature 3's suite has,
where a temp directory replaces the CV registry.

The fake honours the parts of SQL the code actually depends on: the
job_listing/job_enrichment join, rank ordering, LIMIT, and — importantly —
transaction rollback, so M-02-09's documented rollback behaviour is genuinely
exercised rather than assumed.
"""

import contextlib
import copy
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class FakeDatabaseError(Exception):
    """Stands in for db.DatabaseError."""


class FakeDB:
    """
    In-memory stand-in for db.py.

    Tables are plain dicts. commit()/rollback() are real: a transaction works
    on a deep copy and only merges back on a clean exit, so a failed insert
    genuinely leaves prior state untouched.
    """

    def __init__(self):
        self.listings = {}
        self.enrichment = {}
        self.matches = {}
        self.ownership = {}
        self.fail_on = None          # substring of a statement that should raise
        self.DatabaseError = FakeDatabaseError

    # -- installation ---------------------------------------------------

    def install(self):
        module = types.ModuleType("db")
        module.DatabaseError = FakeDatabaseError
        module.query = self.query
        module.execute = self.execute
        module.transaction = self.transaction
        sys.modules["db"] = module

        # match_service imports job_service lazily for the 365-day rule.
        job_service = types.ModuleType("job_service")
        job_service.is_system_outdated = self._is_system_outdated
        sys.modules["job_service"] = job_service
        return module

    @staticmethod
    def _is_system_outdated(job):
        posted = job.get("job_posted_date")
        if not posted:
            return False
        if isinstance(posted, str):
            try:
                posted = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            except ValueError:
                return False
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - posted) >= timedelta(days=365)

    # -- seeding --------------------------------------------------------

    def add_listing(self, listing_id, *, title="Developer", company="ACME",
                    location="Bangkok", url=None, skills=None, education=None,
                    education_requirement=None, experience_years=None,
                    outdated_manual=False, days_old=10, enriched=True):
        self.listings[listing_id] = {
            "url": url or f"https://example.com/jobs/{listing_id}",
            "job_title": title,
            "company_name": company,
            "job_location": location,
            "job_details": "",
            "job_employment_type": None,
            "job_posted_date": datetime.now(timezone.utc) - timedelta(days=days_old),
            "salary": None,
            "outdated_manual": outdated_manual,
        }
        if enriched:
            self.enrichment[listing_id] = {
                "skills": json.dumps(skills or []),
                "education": education,
                "education_requirement": json.dumps(education_requirement)
                    if education_requirement else None,
                "experience_years": experience_years,
                "work_mode": None,
                "benefits": "[]",
                "translated_description": "A job.",
            }
        return listing_id

    # -- the db.py interface --------------------------------------------

    def query(self, sql, params=()):
        statement = " ".join(sql.split())
        self._maybe_fail(statement)

        if "FROM job_listing l JOIN job_enrichment e" in statement:
            rows = []
            for listing_id, listing in self.listings.items():
                if listing_id not in self.enrichment:
                    continue
                rows.append({**listing, "id": listing_id, **self.enrichment[listing_id]})
            return self._limit(rows, statement, params)

        if "FROM job_match m" in statement:
            rows = [m for m in self.matches.values() if m["cv_id"] == params[0]]
            rows.sort(key=lambda r: r["rank_position"])
            out = []
            for row in rows:
                listing = self.listings.get(row["job_listing_id"], {})
                enrichment = self.enrichment.get(row["job_listing_id"], {})
                out.append({
                    **row,
                    **{k: listing.get(k) for k in
                       ("url", "job_title", "company_name", "job_location",
                        "job_employment_type", "salary", "outdated_manual")},
                    "skills": enrichment.get("skills", "[]"),
                    "translated_description": enrichment.get("translated_description"),
                    "work_mode": enrichment.get("work_mode"),
                })
            return out

        if "FROM jobseeker_cv" in statement:
            rows = [r for r in self.ownership.values() if r["jobseeker_id"] == params[0]]
            rows.sort(key=lambda r: r["uploaded_at"], reverse=True)
            return rows

        if "FROM job_listing" in statement:
            rows = [{"id": k, **v} for k, v in self.listings.items()]
            return self._limit(rows, statement, params)

        return []

    def execute(self, sql, params=()):
        statement = " ".join(sql.split())
        self._maybe_fail(statement)
        if statement.startswith("INSERT INTO jobseeker_cv"):
            self.ownership[params[2]] = {
                "cv_id": params[2], "jobseeker_id": params[1],
                "original_filename": params[3], "uploaded_at": params[4],
            }
        return 1

    @contextlib.contextmanager
    def transaction(self):
        snapshot = copy.deepcopy(self.matches)
        cursor = _FakeCursor(self)
        try:
            yield _FakeConnection(cursor)
        except Exception as ex:
            self.matches = snapshot
            raise FakeDatabaseError(f"Transaction failed and was rolled back: {ex}") from ex

    # -- internals ------------------------------------------------------

    def _maybe_fail(self, statement):
        if self.fail_on and self.fail_on in statement:
            raise FakeDatabaseError(f"simulated failure on: {self.fail_on}")

    @staticmethod
    def _limit(rows, statement, params):
        if statement.rstrip().endswith("LIMIT %s") and params:
            return rows[: int(params[-1])]
        return rows


class _FakeCursor:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=()):
        statement = " ".join(sql.split())
        self.db._maybe_fail(statement)
        if statement.startswith("DELETE FROM job_match"):
            for key in [k for k, v in self.db.matches.items() if v["cv_id"] == params[0]]:
                del self.db.matches[key]
        elif statement.startswith("INSERT INTO job_match"):
            self.db.matches[params[0]] = {
                "id": params[0], "cv_id": params[1], "job_listing_id": params[2],
                "match_score": params[3], "matched_skills": params[4],
                "missing_categories": params[5], "rank_position": params[6],
                "computed_at": params[7],
            }

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, **kwargs):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def write_cv_registry(path, records):
    """Writes a cvs.json in the shape M-03-09 storeExtractedCVInfo produces."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)


def cv_record(cv_id="cv-test-001", *, skills=None, education=None,
              work_experience=None, extracted=True, filename="cv.pdf"):
    """One registry record, with or without the extracted_data M-03-09 adds."""
    record = {
        "id": cv_id,
        "jobseekerId": "John Doe",
        "original_filename": filename,
        "stored_path": f"uploads/{cv_id}_{filename}",
        "size_bytes": 1024,
        "sha256": "0" * 64,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "validation_status": "validated",
    }
    if extracted:
        record["extracted_data"] = {
            "skills": skills if skills is not None else [{"skill_name": "Python"}],
            "education": education if education is not None else [],
            "work_experience": work_experience if work_experience is not None else [],
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
    return record
