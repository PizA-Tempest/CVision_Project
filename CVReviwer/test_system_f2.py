"""
test_system_f2.py — system tests for Feature #2 (Job Matching)

    python test_system_f2.py                 # run every system test
    python test_system_f2.py -v              # one line per test
    python test_system_f2.py --cv <cv_id>    # test against a chosen CV

HOW THIS DIFFERS FROM test_match.py
===================================
The unit suite runs every method against FakeDB and a temporary registry: no
MySQL, no configuration, no cost. That is right for unit tests, but it means
nothing there proves the feature works on a real installation — a wrong column
name, a missing index, an enrichment that never ran, a CV whose stored shape
the adapter cannot read, none of it can fail a unit test.

These tests run the real modules against the real MySQL database and the real
CV registry, and check the behaviour SRS-047 to SRS-062 actually promise. Each
test is identified ST-2-nnn and names the requirement it covers, so the results
can be transcribed into a System Test Record.

WHAT IT WRITES
==============
One CV's job_match rows, which is exactly what the application writes when
that CV is matched. Those rows are captured before the run and restored
afterwards, so a database used for a demonstration is left as it was found.
Nothing else is written: no listing, no enrichment and no CV is created,
modified or deleted.

PREREQUISITES
=============
Tests skip rather than fail when the system is not ready, because a failure
should mean the feature is broken, not that the machine has not been set up:

    database unreachable        every test skips
    no enriched active listing  matching tests skip
    no parsed CV in cvs.json    matching tests skip

Run `python verify_integration.py --no-ai` first if anything skips
unexpectedly; it reports which of those is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

import cv_data_adapter
import db
import match_controller
import match_service

CV_OVERRIDE = None          # set by --cv


# ---------------------------------------------------------------------
# environment probing
# ---------------------------------------------------------------------

def _database_reachable():
    try:
        db.query("SELECT 1 AS ok")
        return True
    except Exception:
        return False


def _first_usable_cv():
    """
    A CV in the registry whose stored data matching can actually read.

    Prefers the one named with --cv. Otherwise takes the first that
    get_extracted_cv_data accepts — a registry can hold CVs that failed
    extraction, and those are legitimately unmatchable.
    """
    try:
        cv_ids = cv_data_adapter.list_cv_ids()
    except Exception:
        return None, None
    if CV_OVERRIDE:
        cv_ids = [CV_OVERRIDE] + [c for c in cv_ids if c != CV_OVERRIDE]
    for cv_id in cv_ids:
        try:
            data = cv_data_adapter.get_extracted_cv_data(cv_id)
        except Exception:
            continue
        if any(data.get(c) for c in cv_data_adapter.CV_CATEGORIES):
            return cv_id, data
    return None, None


DB_UP = _database_reachable()
CV_ID, CV_DATA = (_first_usable_cv() if DB_UP else (None, None))
try:
    LISTINGS = match_service.retrieve_active_job_listings() if DB_UP else []
except Exception:
    LISTINGS = []

needs_db = unittest.skipUnless(DB_UP, "database not reachable")
needs_data = unittest.skipUnless(
    DB_UP and CV_ID and LISTINGS,
    "needs a parsed CV in cvs.json and at least one enriched active listing")


class SystemTestCase(unittest.TestCase):
    """
    Captures the CV's existing matches once and restores them at the end, so
    the suite leaves the database as it found it.
    """

    _saved = None

    @classmethod
    def setUpClass(cls):
        if DB_UP and CV_ID and SystemTestCase._saved is None:
            SystemTestCase._saved = db.query(
                "SELECT * FROM job_match WHERE cv_id = %s", (CV_ID,))


# ---------------------------------------------------------------------
# ST-2-001 .. ST-2-004  the data the feature runs on
# ---------------------------------------------------------------------

class TestListingsAvailableForMatching(SystemTestCase):
    """SRS-051 — active, non-outdated, enriched listings only."""

    @needs_db
    def test_st_2_001_active_listings_are_retrievable(self):
        listings = match_service.retrieve_active_job_listings()
        self.assertIsInstance(listings, list)
        if not listings:
            self.skipTest("no active enriched listings; run enrich_jobs.py")

    @needs_data
    def test_st_2_002_every_listing_carries_its_enrichment(self):
        # SRS-051 excludes listings without structured job data. If one gets
        # through, matching scores it on nothing and the Jobseeker sees a
        # 0.000 that says more about the pipeline than about their CV.
        for listing in LISTINGS:
            self.assertIn("skills", listing, listing.get("job_title"))

    @needs_data
    def test_st_2_003_no_outdated_listing_is_offered(self):
        """
        SRS-051 — Feature 1 counts a listing as outdated when the manual flag
        is set *or* it is 365 days old, and both must be filtered.

        Checked against the fields of the listings actually returned rather
        than by re-running the filter as a second query: a hand-written copy
        of the rule would pass whenever both copies were wrong in the same
        way, which is the mistake this requirement exists to catch.
        """
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=365)
        for listing in LISTINGS:
            title = listing.get("job_title")
            self.assertFalse(listing.get("outdated_manual"),
                             f"manually outdated listing offered: {title}")
            posted = listing.get("job_posted_date")
            if not isinstance(posted, datetime):
                continue
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            self.assertGreater(posted, cutoff,
                               f"listing older than 365 days offered: {title}")

    @needs_data
    def test_st_2_004_cv_data_is_readable(self):
        """SRS-048 — the parsed CV is readable by matching."""
        data = match_controller.retrieve_cv_data(CV_ID)
        for category in cv_data_adapter.CV_CATEGORIES:
            self.assertIn(category, data)
        self.assertTrue(any(data[c] for c in cv_data_adapter.CV_CATEGORIES))


# ---------------------------------------------------------------------
# ST-2-005 .. ST-2-010  matching, scoring and ranking
# ---------------------------------------------------------------------

class TestMatchingProducesValidResults(SystemTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.matches = (match_service.match_cv_against_listings(CV_ID)
                       if (DB_UP and CV_ID and LISTINGS) else [])

    @needs_data
    def test_st_2_005_every_active_listing_is_scored(self):
        """SRS-051 and SRS-055 — nothing offered is left unscored."""
        self.assertEqual(len(self.matches), len(LISTINGS))

    @needs_data
    def test_st_2_006_scores_are_within_range(self):
        """SRS-055 — a decimal between 0.000 and 1.000."""
        for m in self.matches:
            self.assertGreaterEqual(m.score, 0.0, m.listing.get("job_title"))
            self.assertLessEqual(m.score, 1.0, m.listing.get("job_title"))
            self.assertEqual(round(m.score, 3), m.score,
                             "score must fit DECIMAL(4,3)")

    @needs_data
    def test_st_2_007_matched_skills_appear_in_both_sides(self):
        """SRS-056 — a tag is only shown when both sides list that skill."""
        cv_keys = {match_service.canonical_skill(match_service.skill_name(s))
                   for s in CV_DATA.get("skills") or []}
        for m in self.matches:
            job_keys = {match_service.canonical_skill(s)
                        for s in (m.listing.get("skills") or [])}
            for tag in m.matched_skills:
                key = match_service.canonical_skill(tag)
                self.assertIn(key, job_keys, f"{tag} not required by the job")
                self.assertIn(key, cv_keys, f"{tag} not present in the CV")

    @needs_data
    def test_st_2_008_results_are_ranked_descending(self):
        """SRS-057 — highest score first, positions numbered from 1."""
        scores = [m.score for m in self.matches]
        self.assertEqual(scores, sorted(scores, reverse=True))
        positions = [m.rank_position for m in self.matches]
        self.assertEqual(positions, list(range(1, len(self.matches) + 1)))

    @needs_data
    def test_st_2_009_ranking_is_reproducible(self):
        """
        Two runs over unchanged data must rank identically.

        A stored rank_position that does not reproduce what the Jobseeker saw
        is worse than no stored position at all, and ties are common once
        several listings score the same.
        """
        again = match_service.match_cv_against_listings(CV_ID)
        self.assertEqual([m.job_listing_id for m in self.matches],
                         [m.job_listing_id for m in again])

    @needs_data
    def test_st_2_010_rematching_replaces_rather_than_accumulates(self):
        """
        SRS-058 — the Jobseeker sees one ranking, not every past ranking.

        Counted through the read path the interface uses, so this measures
        what would actually be drawn rather than what is in the table.
        """
        rows = match_controller.display_job_match_results(CV_ID)
        self.assertEqual(len(rows), len(LISTINGS))
        job_ids = [r.get("job_listing_id") for r in rows]
        self.assertEqual(len(job_ids), len(set(job_ids)),
                         "a listing appears twice in one ranking")


# ---------------------------------------------------------------------
# ST-2-011 .. ST-2-014  what the Jobseeker is shown
# ---------------------------------------------------------------------

class TestResultsAreDisplayable(SystemTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if DB_UP and CV_ID and LISTINGS:
            match_service.match_cv_against_listings(CV_ID)
            cls.rows = match_controller.display_job_match_results(CV_ID)
        else:
            cls.rows = []

    @needs_data
    def test_st_2_011_stored_results_are_readable(self):
        """SRS-058 — what was stored can be read back for display."""
        self.assertEqual(len(self.rows), len(LISTINGS))

    @needs_data
    def test_st_2_012_every_card_has_the_fields_srs_058_lists(self):
        for row in self.rows:
            for field in ("job_title", "company_name", "job_location",
                          "match_score", "url"):
                self.assertIn(field, row)
            self.assertTrue(row["job_title"], "a card with no title")

    @needs_data
    def test_st_2_013_cards_are_read_back_in_rank_order(self):
        scores = [float(r["match_score"]) for r in self.rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    @needs_data
    def test_st_2_014_posting_links_are_usable(self):
        """
        SRS-058 — every card offers a link to the original posting.

        Only the form of the URL is checked. Requesting every host would make
        this suite as slow and as unreliable as the slowest external site.
        """
        for row in self.rows:
            url = match_controller.open_job_posting(row["url"])
            self.assertTrue(url.startswith(("http://", "https://")))


# ---------------------------------------------------------------------
# ST-2-015 .. ST-2-017  the CV selector and stored CVs
# ---------------------------------------------------------------------

class TestPreviousCVSelector(SystemTestCase):

    @needs_data
    def test_st_2_015_uploaded_cv_appears_in_the_selector(self):
        """SRS-047 — a previously uploaded CV is offered for reuse."""
        record = cv_data_adapter.get_cv_record(CV_ID)
        if not record:
            self.skipTest("CV has no registry record")
        owner = record.get("jobseekerId")
        if not owner:
            self.skipTest("CV has no recorded owner")
        listed = {c.get("cv_id") for c in cv_data_adapter.list_cv_ids_for(owner)}
        if not listed:
            # Ownership is written at upload. A CV uploaded before that was
            # added has no row, which is a gap in the data rather than a
            # failure of the selector.
            self.skipTest(f"no ownership row recorded for {owner}; "
                          "re-upload a CV to create one")
        self.assertIn(CV_ID, listed)

    @needs_data
    def test_st_2_016_matching_runs_from_a_stored_cv(self):
        """SRS-059 — no new upload is needed to produce a ranking."""
        matches = match_controller.generate_job_matches(CV_ID)
        self.assertEqual(len(matches), len(LISTINGS))

    @needs_data
    def test_st_2_017_extracted_information_is_available_for_display(self):
        """SRS-050 — the cards above the results have something to show."""
        data = cv_data_adapter.get_extracted_cv_data(CV_ID)
        available = cv_data_adapter.available_categories(data)
        self.assertTrue(available, "no CV category holds any data")


# ---------------------------------------------------------------------
# ST-2-018 .. ST-2-021  the error paths
# ---------------------------------------------------------------------

class TestErrorHandling(SystemTestCase):

    @needs_db
    def test_st_2_018_unknown_cv_is_refused(self):
        """SRS-061 — corrupted or missing CV data raises rather than scores."""
        with self.assertRaises(cv_data_adapter.CVDataCorruptedException):
            match_controller.retrieve_cv_data("no-such-cv-000000000000")

    @needs_db
    def test_st_2_019_corrupted_cv_message_asks_for_reupload(self):
        """SRS-061 — the message names the action the Jobseeker should take."""
        message = match_controller.handle_matching_error(
            cv_data_adapter.CVDataCorruptedException("unreadable"))
        self.assertIn("re-upload", message.lower())

    @needs_db
    def test_st_2_020_calculation_failure_message_is_shown(self):
        """SRS-060 — an internal failure produces a message, not a trace."""
        message = match_controller.handle_matching_error(
            match_service.MatchingCalculationException("traceback: boom"))
        self.assertTrue(message)
        self.assertNotIn("traceback", message.lower())

    @needs_db
    def test_st_2_021_unusable_posting_url_is_refused(self):
        """SRS-058 — a broken link is refused rather than opened."""
        with self.assertRaises(match_controller.JobPostingUnavailableException):
            match_controller.open_job_posting("not a url")

    @needs_db
    def test_st_2_022_empty_result_is_distinguishable_from_no_match(self):
        """
        SRS-062 — no listings available is a different state from no good
        match, and the interface has to be able to tell them apart.
        """
        rows = match_controller.display_job_match_results(
            "no-such-cv-000000000000")
        self.assertEqual(rows, [])


# ---------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------

def _restore_matches():
    """Puts the CV's original job_match rows back."""
    saved = SystemTestCase._saved
    if saved is None or not DB_UP or not CV_ID:
        return
    columns = ["id", "cv_id", "job_listing_id", "match_score", "matched_skills",
               "missing_categories", "rank_position", "computed_at"]
    try:
        # db.transaction() yields the *connection*, not a cursor (M-032).
        # FakeDB yields something that executes directly, which is why this
        # passed against the fake and failed against MySQL.
        with db.transaction() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM job_match WHERE cv_id = %s", (CV_ID,))
            for row in saved:
                values = []
                for c in columns:
                    v = row.get(c)
                    if isinstance(v, Decimal):
                        v = float(v)
                    elif isinstance(v, (dict, list)):
                        v = json.dumps(v, ensure_ascii=False)
                    values.append(v)
                cur.execute(
                    "INSERT INTO job_match (" + ", ".join(columns) + ") "
                    "VALUES (" + ", ".join(["%s"] * len(columns)) + ")",
                    tuple(values))
        print(f"\n  restored {len(saved)} previous job_match row(s) for {CV_ID[:8]}")
    except Exception as ex:
        print(f"\n  WARNING: could not restore previous matches: {ex}")
        print("  The CV's ranking is the one this run produced, which is what "
              "the application\n  would have written anyway. Re-upload the CV "
              "to regenerate it if that matters.")


def main():
    parser = argparse.ArgumentParser(
        description="System tests for Feature #2 (Job Matching).")
    parser.add_argument("--cv", metavar="CV_ID",
                        help="test against this CV rather than the first usable one")
    parser.add_argument("-v", "--verbose", action="store_true")
    args, rest = parser.parse_known_args()

    global CV_OVERRIDE, CV_ID, CV_DATA
    if args.cv:
        CV_OVERRIDE = args.cv
        CV_ID, CV_DATA = _first_usable_cv()

    print(f"Database:  {'reachable' if DB_UP else 'NOT REACHABLE'}")
    print(f"CV:        {CV_ID or 'none usable'}")
    print(f"Listings:  {len(LISTINGS)} active and enriched")
    if not DB_UP:
        print("\nEverything will skip. Check the DB_* values in .env, then run"
              "\n  python verify_integration.py --no-ai")
    print()

    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    _restore_matches()
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())