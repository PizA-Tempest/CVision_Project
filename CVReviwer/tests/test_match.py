"""Tests for Feature #2 (Job Matching) — M-02-01 through M-02-12.

Test IDs follow the project convention: UT-2-<method>-<case>, matching the
UT-3-<method>-<case> scheme Feature 3's suite uses.

No database and no API key are needed: f2_helpers installs an in-memory
stand-in for db.py, and the CV registry is a temp file.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from f2_helpers import FakeDB, cv_record, write_cv_registry

# db.py must be replaced before match_service imports it.
_DB = FakeDB()
_DB.install()

import cv_data_adapter
import match_controller
import match_service
from cv_data_adapter import CVDataCorruptedException
from match_controller import JobPostingUnavailableException
from match_service import (
    DatabaseException, EducationComparisonResult, ExperienceComparisonResult,
    JobMatchResult, MatchingCalculationException, SkillComparisonResult,
)


class FeatureTwoTestCase(unittest.TestCase):
    """Fresh in-memory database and CV registry for every test."""

    def setUp(self):
        self.db = _DB
        self.db.listings.clear()
        self.db.enrichment.clear()
        self.db.matches.clear()
        self.db.ownership.clear()
        self.db.fail_on = None

        self.tmp = tempfile.TemporaryDirectory()
        self.registry = os.path.join(self.tmp.name, "cvs.json")
        self._original_registry = cv_data_adapter.CV_REGISTRY_FILE
        cv_data_adapter.CV_REGISTRY_FILE = self.registry
        write_cv_registry(self.registry, [])

    def tearDown(self):
        cv_data_adapter.CV_REGISTRY_FILE = self._original_registry
        self.tmp.cleanup()


# ---------------------------------------------------------------------
# UT-2-01 — retrieveCVData (M-02-01)
# ---------------------------------------------------------------------

class TestRetrieveCVData(FeatureTwoTestCase):

    def test_ut_2_01_001_returns_all_three_categories(self):
        write_cv_registry(self.registry, [cv_record(
            skills=[{"skill_name": "Python"}],
            education=[{"degree": "BSc"}],
            work_experience=[{"company": "ACME"}],
        )])
        data = match_controller.retrieve_cv_data("cv-test-001")
        self.assertEqual(sorted(data), ["education", "skills", "work_experience"])
        self.assertEqual(len(data["skills"]), 1)

    def test_ut_2_01_002_missing_categories_are_empty_lists(self):
        write_cv_registry(self.registry, [cv_record(
            skills=[{"skill_name": "Python"}], education=[], work_experience=[])])
        data = match_controller.retrieve_cv_data("cv-test-001")
        self.assertEqual(data["education"], [])
        self.assertEqual(data["work_experience"], [])

    def test_ut_2_01_003_unknown_cv_raises(self):
        write_cv_registry(self.registry, [cv_record()])
        with self.assertRaises(CVDataCorruptedException):
            match_controller.retrieve_cv_data("no-such-cv")

    def test_ut_2_01_004_never_parsed_cv_raises(self):
        write_cv_registry(self.registry, [cv_record(extracted=False)])
        with self.assertRaises(CVDataCorruptedException):
            match_controller.retrieve_cv_data("cv-test-001")

    def test_ut_2_01_005_all_categories_empty_raises(self):
        write_cv_registry(self.registry, [cv_record(skills=[], education=[], work_experience=[])])
        with self.assertRaises(CVDataCorruptedException):
            match_controller.retrieve_cv_data("cv-test-001")

    def test_ut_2_01_006_malformed_extracted_data_raises(self):
        record = cv_record()
        record["extracted_data"] = "not a mapping"
        write_cv_registry(self.registry, [record])
        with self.assertRaises(CVDataCorruptedException):
            match_controller.retrieve_cv_data("cv-test-001")

    def test_ut_2_01_007_malformed_category_degrades_to_empty(self):
        record = cv_record()
        record["extracted_data"] = {"skills": [{"skill_name": "Python"}],
                                    "education": "not a list", "work_experience": None}
        write_cv_registry(self.registry, [record])
        data = match_controller.retrieve_cv_data("cv-test-001")
        self.assertEqual(data["education"], [])
        self.assertEqual(len(data["skills"]), 1)

    def test_ut_2_01_008_available_categories_reflects_content(self):
        write_cv_registry(self.registry, [cv_record(
            skills=[{"skill_name": "Python"}], education=[], work_experience=[{"company": "A"}])])
        data = match_controller.retrieve_cv_data("cv-test-001")
        self.assertEqual(cv_data_adapter.available_categories(data),
                         ["skills", "work_experience"])


# ---------------------------------------------------------------------
# UT-2-02 — retrieveActiveJobListings (M-02-02)
# ---------------------------------------------------------------------

class TestRetrieveActiveJobListings(FeatureTwoTestCase):

    def test_ut_2_02_001_returns_active_enriched_listings(self):
        self.db.add_listing("L1", skills=["Python"])
        self.db.add_listing("L2", skills=["Java"])
        self.assertEqual(len(match_service.retrieve_active_job_listings()), 2)

    def test_ut_2_02_002_filters_manually_outdated(self):
        self.db.add_listing("L1", skills=["Python"])
        self.db.add_listing("L2", skills=["Java"], outdated_manual=True)
        listings = match_service.retrieve_active_job_listings()
        self.assertEqual([l["id"] for l in listings], ["L1"])

    def test_ut_2_02_003_filters_system_outdated_365_days(self):
        self.db.add_listing("L1", skills=["Python"], days_old=10)
        self.db.add_listing("L2", skills=["Java"], days_old=400)
        listings = match_service.retrieve_active_job_listings()
        self.assertEqual([l["id"] for l in listings], ["L1"])

    def test_ut_2_02_004_boundary_exactly_365_days_excluded(self):
        self.db.add_listing("L1", skills=["Python"], days_old=365)
        self.assertEqual(match_service.retrieve_active_job_listings(), [])

    def test_ut_2_02_005_excludes_unenriched_listings(self):
        self.db.add_listing("L1", skills=["Python"])
        self.db.add_listing("L2", enriched=False)
        listings = match_service.retrieve_active_job_listings()
        self.assertEqual([l["id"] for l in listings], ["L1"])

    def test_ut_2_02_006_no_listings_returns_empty_list(self):
        self.assertEqual(match_service.retrieve_active_job_listings(), [])

    def test_ut_2_02_007_skills_decoded_from_json(self):
        self.db.add_listing("L1", skills=["Python", "SQL"])
        listing = match_service.retrieve_active_job_listings()[0]
        self.assertEqual(listing["skills"], ["Python", "SQL"])

    def test_ut_2_02_008_structured_education_requirement_decoded(self):
        self.db.add_listing("L1", skills=["Python"],
                            education_requirement={"min_degree_level": "bachelor",
                                                   "fields": ["computer science"]})
        listing = match_service.retrieve_active_job_listings()[0]
        self.assertEqual(listing["education_requirement"]["min_degree_level"], "bachelor")


# ---------------------------------------------------------------------
# UT-2-03 — compareSkills (M-02-03)
# ---------------------------------------------------------------------

class TestCompareSkills(FeatureTwoTestCase):

    def test_ut_2_03_001_full_overlap_ratio_one(self):
        result = match_service.compare_skills(["Python", "SQL"], ["Python", "SQL"])
        self.assertEqual(result.ratio, 1.0)
        self.assertEqual(sorted(result.matched), ["Python", "SQL"])

    def test_ut_2_03_002_partial_overlap(self):
        result = match_service.compare_skills(["Python"], ["Python", "Go", "Rust", "SQL"])
        self.assertEqual(result.ratio, 0.25)
        self.assertEqual(result.missing, ["Go", "Rust", "SQL"])

    def test_ut_2_03_003_case_insensitive(self):
        result = match_service.compare_skills(["python"], ["PYTHON"])
        self.assertEqual(result.matched, ["PYTHON"])

    def test_ut_2_03_004_no_overlap_ratio_zero(self):
        result = match_service.compare_skills(["Java"], ["Python"])
        self.assertEqual(result.ratio, 0.0)
        self.assertEqual(result.matched, [])

    def test_ut_2_03_005_job_lists_no_skills(self):
        result = match_service.compare_skills(["Python"], [])
        self.assertEqual(result.ratio, 0.0)

    def test_ut_2_03_006_cv_has_no_skills(self):
        result = match_service.compare_skills([], ["Python"])
        self.assertEqual(result.ratio, 0.0)
        self.assertEqual(result.missing, ["Python"])

    def test_ut_2_03_007_accepts_dict_and_string_skill_shapes(self):
        for shape in (["Python"], [{"skill_name": "Python"}], [{"name": "Python"}]):
            with self.subTest(shape=shape):
                self.assertEqual(match_service.compare_skills(shape, ["Python"]).matched,
                                 ["Python"])

    def test_ut_2_03_008_punctuation_tolerant(self):
        self.assertEqual(match_service.compare_skills(["Node.js"], ["node.js"]).matched,
                         ["node.js"])

    def test_ut_2_03_009_matched_uses_job_spelling(self):
        self.assertEqual(match_service.compare_skills(["python"], ["Python"]).matched,
                         ["Python"])


# ---------------------------------------------------------------------
# UT-2-04 — compareEducation (M-02-04)
# ---------------------------------------------------------------------

CV_BSC_SE = [{"institution": "Chiang Mai University",
              "degree": "Bachelor of Science in Software Engineering"}]


class TestCompareEducation(FeatureTwoTestCase):

    def test_ut_2_04_001_exact_level_and_field(self):
        result = match_service.compare_education(
            [{"degree": "Bachelor of Science in Computer Science"}],
            {"min_degree_level": "bachelor", "fields": ["computer science"]})
        self.assertTrue(result.meets_requirement)
        self.assertEqual(result.ratio, 1.0)

    def test_ut_2_04_002_below_required_level_does_not_meet(self):
        result = match_service.compare_education(
            CV_BSC_SE, {"min_degree_level": "master", "fields": []})
        self.assertFalse(result.meets_requirement)

    def test_ut_2_04_003_above_required_level_meets(self):
        result = match_service.compare_education(
            [{"degree": "Master of Science in Computer Science"}],
            {"min_degree_level": "bachelor", "fields": ["computer science"]})
        self.assertTrue(result.meets_requirement)

    def test_ut_2_04_004_no_requirement_scores_full(self):
        result = match_service.compare_education(CV_BSC_SE, None)
        self.assertEqual(result.ratio, 1.0)
        self.assertTrue(result.meets_requirement)

    def test_ut_2_04_005_no_cv_education_scores_zero(self):
        result = match_service.compare_education([], "Bachelor's degree")
        self.assertEqual(result.ratio, 0.0)
        self.assertFalse(result.meets_requirement)

    def test_ut_2_04_006_wrong_field_does_not_meet(self):
        result = match_service.compare_education(
            [{"degree": "Bachelor of Arts in Fine Arts"}],
            {"min_degree_level": "bachelor", "fields": ["computer science"]})
        self.assertFalse(result.meets_requirement)

    def test_ut_2_04_007_institution_name_is_not_a_degree_level(self):
        """Regression: 'ma' inside 'Chiang Mai' was read as a Master's."""
        self.assertEqual(match_service._degree_level("Chiang Mai University"), 0)
        self.assertEqual(match_service._degree_level("Bangkok University"), 0)

    def test_ut_2_04_008_plural_field_matches_singular(self):
        """Regression: 'Computer Sciences' failed to match a CS degree."""
        result = match_service.compare_education(
            CV_BSC_SE, "Degree in Computer Sciences or equivalent")
        self.assertTrue(result.meets_requirement)

    def test_ut_2_04_009_alternatives_are_disjunctive(self):
        """Regression: a precise requirement scored below a vague one."""
        vague = match_service.compare_education(CV_BSC_SE, "Bachelor's degree")
        precise = match_service.compare_education(
            CV_BSC_SE,
            "Bachelor's degree in software engineering, computer engineering, "
            "computer science or related fields")
        self.assertGreaterEqual(precise.ratio, vague.ratio)

    def test_ut_2_04_010_bachelor_satisfies_bachelor_or_master(self):
        """Regression: 'Bachelor/Master's' demanded a Master's."""
        result = match_service.compare_education(
            CV_BSC_SE, "Bachelor/Master's degree in Computer Science or related fields")
        self.assertTrue(result.meets_requirement)

    def test_ut_2_04_011_accepts_json_string_requirement(self):
        requirement = {"min_degree_level": "bachelor", "fields": ["computer science"]}
        as_dict = match_service.compare_education(CV_BSC_SE, requirement)
        as_json = match_service.compare_education(CV_BSC_SE, json.dumps(requirement))
        self.assertEqual(as_dict.ratio, as_json.ratio)

    def test_ut_2_04_012_ratio_within_srs_052_range(self):
        for requirement in (None, "Bachelor's degree", {"min_degree_level": "doctorate",
                                                        "fields": ["physics"]}):
            with self.subTest(requirement=requirement):
                ratio = match_service.compare_education(CV_BSC_SE, requirement).ratio
                self.assertGreaterEqual(ratio, 0.0)
                self.assertLessEqual(ratio, 1.0)


# ---------------------------------------------------------------------
# UT-2-05 — compareExperience (M-02-05)
# ---------------------------------------------------------------------

THREE_YEARS = [{"company": "ACME", "position": "Dev",
                "start_date": "2020", "end_date": "2023"}]


class TestCompareExperience(FeatureTwoTestCase):

    def test_ut_2_05_001_meets_requirement(self):
        result = match_service.compare_experience(THREE_YEARS, 2)
        self.assertTrue(result.is_relevant)
        self.assertEqual(result.ratio, 1.0)

    def test_ut_2_05_002_short_of_requirement_scores_proportionally(self):
        result = match_service.compare_experience(THREE_YEARS, 6)
        self.assertEqual(result.ratio, 0.5)
        self.assertFalse(result.is_relevant)

    def test_ut_2_05_003_exact_boundary_meets(self):
        result = match_service.compare_experience(THREE_YEARS, 3)
        self.assertTrue(result.is_relevant)
        self.assertEqual(result.ratio, 1.0)

    def test_ut_2_05_004_years_counted_correctly(self):
        self.assertEqual(match_service.compare_experience(THREE_YEARS, 1).cv_years, 3.0)

    def test_ut_2_05_005_open_ended_role_counts_to_now(self):
        result = match_service.compare_experience(
            [{"start_date": "Jan 2024", "end_date": "Present"}], 1)
        self.assertEqual(result.cv_years,
                         float(datetime.now(timezone.utc).year - 2024))

    def test_ut_2_05_006_no_requirement_with_experience(self):
        self.assertEqual(match_service.compare_experience(THREE_YEARS, None).ratio, 1.0)

    def test_ut_2_05_007_no_requirement_no_experience(self):
        self.assertEqual(match_service.compare_experience([], None).ratio, 0.5)

    def test_ut_2_05_008_unparseable_dates_still_credit_the_role(self):
        result = match_service.compare_experience([{"start_date": "a while ago"}], None)
        self.assertEqual(result.ratio, 0.75)

    def test_ut_2_05_009_zero_years_required(self):
        self.assertEqual(match_service.compare_experience([], 0).ratio, 1.0)

    def test_ut_2_05_010_multiple_roles_sum(self):
        roles = [{"start_date": "2018", "end_date": "2020"},
                 {"start_date": "2020", "end_date": "2023"}]
        self.assertEqual(match_service.compare_experience(roles, 1).cv_years, 5.0)


# ---------------------------------------------------------------------
# UT-2-06 — calculateMatchScore (M-02-06)
# ---------------------------------------------------------------------

ALL = ["skills", "education", "work_experience"]


def _results(skill=0.0, education=0.0, experience=0.0):
    return (SkillComparisonResult(ratio=skill),
            EducationComparisonResult(ratio=education),
            ExperienceComparisonResult(ratio=experience))


class TestCalculateMatchScore(FeatureTwoTestCase):

    def test_ut_2_06_001_all_perfect_scores_one(self):
        self.assertEqual(match_service.calculate_match_score(*_results(1.0, 1.0, 1.0), ALL), 1.0)

    def test_ut_2_06_002_all_zero_scores_zero(self):
        self.assertEqual(match_service.calculate_match_score(*_results(), ALL), 0.0)

    def test_ut_2_06_003_weighted_combination(self):
        score = match_service.calculate_match_score(*_results(0.5, 1.0, 1.0), ALL)
        self.assertEqual(score, round(0.5 * 0.50 + 1.0 * 0.20 + 1.0 * 0.30, 3))

    def test_ut_2_06_004_missing_categories_renormalise(self):
        """SRS-058: a skills-only CV is scored on skills alone, not penalised."""
        self.assertEqual(
            match_service.calculate_match_score(*_results(1.0), ["skills"]), 1.0)

    def test_ut_2_06_005_two_categories_renormalise(self):
        score = match_service.calculate_match_score(
            *_results(1.0), ["skills", "work_experience"])
        self.assertEqual(score, round(0.50 / 0.80, 3))

    def test_ut_2_06_006_score_rounded_to_three_decimals(self):
        score = match_service.calculate_match_score(*_results(1 / 3, 1 / 3, 1 / 3), ALL)
        self.assertEqual(score, round(score, 3))

    def test_ut_2_06_007_no_available_categories_raises(self):
        with self.assertRaises(MatchingCalculationException):
            match_service.calculate_match_score(*_results(1.0, 1.0, 1.0), [])

    def test_ut_2_06_008_unknown_category_raises(self):
        with self.assertRaises(MatchingCalculationException):
            match_service.calculate_match_score(*_results(1.0, 1.0, 1.0), ["nonsense"])

    def test_ut_2_06_009_nan_ratio_raises(self):
        with self.assertRaises(MatchingCalculationException):
            match_service.calculate_match_score(*_results(float("nan")), ["skills"])

    def test_ut_2_06_010_out_of_range_ratio_clamped(self):
        self.assertEqual(match_service.calculate_match_score(*_results(5.0), ["skills"]), 1.0)

    def test_ut_2_06_011_score_within_srs_052_range(self):
        for skill in (0.0, 0.33, 0.5, 0.99, 1.0):
            with self.subTest(skill=skill):
                score = match_service.calculate_match_score(*_results(skill, skill, skill), ALL)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)


# ---------------------------------------------------------------------
# UT-2-07 — identifyMatchedSkills (M-02-07)
# ---------------------------------------------------------------------

class TestIdentifyMatchedSkills(FeatureTwoTestCase):

    def test_ut_2_07_001_returns_overlapping_skills(self):
        self.assertEqual(
            match_service.identify_matched_skills(["Python", "SQL"], ["Python", "Go"]),
            ["Python"])

    def test_ut_2_07_002_no_overlap_returns_empty(self):
        self.assertEqual(match_service.identify_matched_skills(["Java"], ["Python"]), [])

    def test_ut_2_07_003_empty_cv_returns_empty(self):
        self.assertEqual(match_service.identify_matched_skills([], ["Python"]), [])

    def test_ut_2_07_004_empty_job_skills_returns_empty(self):
        self.assertEqual(match_service.identify_matched_skills(["Python"], []), [])

    def test_ut_2_07_005_case_insensitive(self):
        self.assertEqual(match_service.identify_matched_skills(["PYTHON"], ["python"]),
                         ["python"])

    def test_ut_2_07_006_agrees_with_compare_skills(self):
        cv, job = ["Python", "SQL"], ["Python", "Go", "SQL"]
        self.assertEqual(match_service.identify_matched_skills(cv, job),
                         match_service.compare_skills(cv, job).matched)


# ---------------------------------------------------------------------
# UT-2-08 — rankJobMatches (M-02-08)
# ---------------------------------------------------------------------

class TestRankJobMatches(FeatureTwoTestCase):

    def test_ut_2_08_001_sorted_descending_by_score(self):
        ranked = match_service.rank_job_matches([
            JobMatchResult("a", 0.2), JobMatchResult("b", 0.9), JobMatchResult("c", 0.5)])
        self.assertEqual([m.job_listing_id for m in ranked], ["b", "c", "a"])

    def test_ut_2_08_002_rank_positions_start_at_one(self):
        ranked = match_service.rank_job_matches(
            [JobMatchResult("a", 0.2), JobMatchResult("b", 0.9)])
        self.assertEqual([m.rank_position for m in ranked], [1, 2])

    def test_ut_2_08_003_tie_broken_by_matched_skill_count(self):
        ranked = match_service.rank_job_matches([
            JobMatchResult("z", 0.5, matched_skills=["a"]),
            JobMatchResult("y", 0.5, matched_skills=["a", "b"])])
        self.assertEqual([m.job_listing_id for m in ranked], ["y", "z"])

    def test_ut_2_08_004_full_tie_is_deterministic(self):
        first = match_service.rank_job_matches(
            [JobMatchResult("b", 0.5), JobMatchResult("a", 0.5)])
        second = match_service.rank_job_matches(
            [JobMatchResult("a", 0.5), JobMatchResult("b", 0.5)])
        self.assertEqual([m.job_listing_id for m in first],
                         [m.job_listing_id for m in second])

    def test_ut_2_08_005_empty_input_returns_empty(self):
        self.assertEqual(match_service.rank_job_matches([]), [])

    def test_ut_2_08_006_single_match_gets_rank_one(self):
        ranked = match_service.rank_job_matches([JobMatchResult("a", 0.4)])
        self.assertEqual(ranked[0].rank_position, 1)


# ---------------------------------------------------------------------
# UT-2-09 — storeJobMatchResults (M-02-09)
# ---------------------------------------------------------------------

class TestStoreJobMatchResults(FeatureTwoTestCase):

    def _matches(self):
        return match_service.rank_job_matches([
            JobMatchResult("L1", 0.8, matched_skills=["Python"]),
            JobMatchResult("L2", 0.4, missing_categories=["education"])])

    def test_ut_2_09_001_persists_every_match(self):
        match_service.store_job_match_results("cv-1", self._matches())
        self.assertEqual(len(self.db.matches), 2)

    def test_ut_2_09_002_stores_score_tags_and_missing_categories(self):
        match_service.store_job_match_results("cv-1", self._matches())
        stored = {m["job_listing_id"]: m for m in self.db.matches.values()}
        self.assertEqual(stored["L1"]["match_score"], 0.8)
        self.assertEqual(json.loads(stored["L1"]["matched_skills"]), ["Python"])
        self.assertEqual(json.loads(stored["L2"]["missing_categories"]), ["education"])

    def test_ut_2_09_003_rerun_replaces_rather_than_accumulates(self):
        match_service.store_job_match_results("cv-1", self._matches())
        match_service.store_job_match_results("cv-1", self._matches())
        self.assertEqual(len(self.db.matches), 2)

    def test_ut_2_09_004_other_cvs_are_untouched(self):
        match_service.store_job_match_results("cv-1", self._matches())
        match_service.store_job_match_results("cv-2", self._matches())
        self.assertEqual(len(self.db.matches), 4)

    def test_ut_2_09_005_insert_failure_raises_database_exception(self):
        self.db.fail_on = "INSERT INTO job_match"
        with self.assertRaises(DatabaseException):
            match_service.store_job_match_results("cv-1", self._matches())

    def test_ut_2_09_006_failed_write_rolls_back(self):
        match_service.store_job_match_results("cv-1", self._matches())
        before = dict(self.db.matches)
        self.db.fail_on = "INSERT INTO job_match"
        with self.assertRaises(DatabaseException):
            match_service.store_job_match_results("cv-2", self._matches())
        self.assertEqual(self.db.matches, before)

    def test_ut_2_09_007_missing_cv_id_raises(self):
        with self.assertRaises(DatabaseException):
            match_service.store_job_match_results("", self._matches())

    def test_ut_2_09_008_empty_match_list_is_accepted(self):
        match_service.store_job_match_results("cv-1", [])
        self.assertEqual(len(self.db.matches), 0)


# ---------------------------------------------------------------------
# UT-2-10 — displayJobMatchResults (M-02-10)
# ---------------------------------------------------------------------

class TestDisplayJobMatchResults(FeatureTwoTestCase):

    def _seed(self):
        self.db.add_listing("L1", title="Backend Developer", skills=["Python", "SQL"])
        self.db.add_listing("L2", title="Frontend Developer", skills=["React"])
        write_cv_registry(self.registry, [cv_record(
            skills=[{"skill_name": "Python"}], education=[], work_experience=[])])
        match_controller.generate_job_matches("cv-test-001")

    def test_ut_2_10_001_returns_rows_in_rank_order(self):
        self._seed()
        rows = match_controller.display_job_match_results("cv-test-001")
        self.assertEqual([r["rank_position"] for r in rows], [1, 2])

    def test_ut_2_10_002_carries_job_card_fields(self):
        self._seed()
        row = match_controller.display_job_match_results("cv-test-001")[0]
        for key in ("job_title", "company_name", "job_location", "url", "match_score"):
            self.assertIn(key, row)

    def test_ut_2_10_003_score_decoded_as_float(self):
        self._seed()
        row = match_controller.display_job_match_results("cv-test-001")[0]
        self.assertIsInstance(row["match_score"], float)

    def test_ut_2_10_004_matched_skills_decoded_as_list(self):
        self._seed()
        row = match_controller.display_job_match_results("cv-test-001")[0]
        self.assertIsInstance(row["matched_skills"], list)

    def test_ut_2_10_005_unknown_cv_returns_empty(self):
        self.assertEqual(match_controller.display_job_match_results("no-such-cv"), [])

    def test_ut_2_10_006_no_listings_returns_empty(self):
        """SRS-057: zero active listings yields nothing to display."""
        write_cv_registry(self.registry, [cv_record()])
        match_controller.generate_job_matches("cv-test-001")
        self.assertEqual(match_controller.display_job_match_results("cv-test-001"), [])


# ---------------------------------------------------------------------
# UT-2-11 — openJobPosting (M-02-11)
# ---------------------------------------------------------------------

class TestOpenJobPosting(FeatureTwoTestCase):

    def test_ut_2_11_001_valid_https_url_returned(self):
        url = "https://th.indeed.com/viewjob?jk=abc"
        self.assertEqual(match_controller.open_job_posting(url), url)

    def test_ut_2_11_002_valid_http_url_returned(self):
        self.assertEqual(match_controller.open_job_posting("http://example.com/j"),
                         "http://example.com/j")

    def test_ut_2_11_003_empty_url_raises(self):
        with self.assertRaises(JobPostingUnavailableException):
            match_controller.open_job_posting("")

    def test_ut_2_11_004_none_url_raises(self):
        with self.assertRaises(JobPostingUnavailableException):
            match_controller.open_job_posting(None)

    def test_ut_2_11_005_malformed_url_raises(self):
        with self.assertRaises(JobPostingUnavailableException):
            match_controller.open_job_posting("not a url")

    def test_ut_2_11_006_non_http_scheme_rejected(self):
        for url in ("ftp://example.com", "javascript:alert(1)", "file:///etc/passwd"):
            with self.subTest(url=url):
                with self.assertRaises(JobPostingUnavailableException):
                    match_controller.open_job_posting(url)

    def test_ut_2_11_007_surrounding_whitespace_tolerated(self):
        self.assertEqual(match_controller.open_job_posting("  https://example.com/j  "),
                         "https://example.com/j")


# ---------------------------------------------------------------------
# UT-2-12 — handleMatchingError (M-02-12)
# ---------------------------------------------------------------------

class TestHandleMatchingError(FeatureTwoTestCase):

    def test_ut_2_12_001_matching_calculation_exception(self):
        self.assertEqual(
            match_controller.handle_matching_error(MatchingCalculationException()),
            "Job matches could not be generated at this time")

    def test_ut_2_12_002_cv_data_corrupted_exception(self):
        self.assertEqual(
            match_controller.handle_matching_error(CVDataCorruptedException()),
            "Your CV data could not be read — please re-upload your CV")

    def test_ut_2_12_003_job_posting_unavailable_exception(self):
        self.assertEqual(
            match_controller.handle_matching_error(JobPostingUnavailableException()),
            "This job posting is no longer available")

    def test_ut_2_12_004_database_exception_maps_to_srs_060(self):
        self.assertEqual(
            match_controller.handle_matching_error(DatabaseException()),
            "Job matches could not be generated at this time")

    def test_ut_2_12_005_unknown_exception_falls_back(self):
        self.assertEqual(match_controller.handle_matching_error(ValueError("x")),
                         "An unexpected error occurred. Please try again")

    def test_ut_2_12_006_none_falls_back(self):
        self.assertEqual(match_controller.handle_matching_error(None),
                         "An unexpected error occurred. Please try again")

    def test_ut_2_12_007_always_returns_a_non_empty_string(self):
        for exception in (MatchingCalculationException(), CVDataCorruptedException(),
                          JobPostingUnavailableException(), DatabaseException(),
                          RuntimeError("boom"), None):
            with self.subTest(exception=exception):
                message = match_controller.handle_matching_error(exception)
                self.assertIsInstance(message, str)
                self.assertTrue(message)

    def test_ut_2_12_008_message_is_user_facing_not_technical(self):
        message = match_controller.handle_matching_error(
            MatchingCalculationException("traceback: division by zero"))
        self.assertNotIn("traceback", message.lower())


# ---------------------------------------------------------------------
# UT-2-13 — the full UC-006 flow (not a documented method)
# ---------------------------------------------------------------------

class TestFullMatchingFlow(FeatureTwoTestCase):

    def test_ut_2_13_001_every_active_listing_is_scored_and_ranked(self):
        for i in range(5):
            self.db.add_listing(f"L{i}", skills=["Python"] if i % 2 else ["Java"])
        write_cv_registry(self.registry, [cv_record(
            skills=[{"skill_name": "Python"}], education=[], work_experience=[])])
        ranked = match_controller.generate_job_matches("cv-test-001")
        self.assertEqual(len(ranked), 5)
        self.assertEqual([m.rank_position for m in ranked], [1, 2, 3, 4, 5])

    def test_ut_2_13_002_scores_are_descending(self):
        for i in range(4):
            self.db.add_listing(f"L{i}", skills=["Python"] if i < 2 else ["COBOL"])
        write_cv_registry(self.registry, [cv_record(
            skills=[{"skill_name": "Python"}], education=[], work_experience=[])])
        ranked = match_controller.generate_job_matches("cv-test-001")
        scores = [m.score for m in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ut_2_13_003_missing_categories_recorded_on_every_match(self):
        self.db.add_listing("L1", skills=["Python"])
        write_cv_registry(self.registry, [cv_record(
            skills=[{"skill_name": "Python"}], education=[], work_experience=[])])
        ranked = match_controller.generate_job_matches("cv-test-001")
        self.assertEqual(sorted(ranked[0].missing_categories),
                         ["education", "work_experience"])

    def test_ut_2_13_004_corrupted_cv_aborts_before_storing(self):
        self.db.add_listing("L1", skills=["Python"])
        write_cv_registry(self.registry, [cv_record(extracted=False)])
        with self.assertRaises(CVDataCorruptedException):
            match_controller.generate_job_matches("cv-test-001")
        self.assertEqual(len(self.db.matches), 0)

    def test_ut_2_13_005_results_are_readable_after_storing(self):
        self.db.add_listing("L1", skills=["Python"])
        write_cv_registry(self.registry, [cv_record(
            skills=[{"skill_name": "Python"}], education=[], work_experience=[])])
        match_controller.generate_job_matches("cv-test-001")
        self.assertEqual(len(match_controller.display_job_match_results("cv-test-001")), 1)

    def test_ut_2_13_006_outdated_listings_never_appear(self):
        self.db.add_listing("L1", skills=["Python"], days_old=10)
        self.db.add_listing("L2", skills=["Python"], days_old=400)
        self.db.add_listing("L3", skills=["Python"], outdated_manual=True)
        write_cv_registry(self.registry, [cv_record(
            skills=[{"skill_name": "Python"}], education=[], work_experience=[])])
        ranked = match_controller.generate_job_matches("cv-test-001")
        self.assertEqual([m.job_listing_id for m in ranked], ["L1"])


# ---------------------------------------------------------------------
# UT-2-14 — CV ownership (not a documented method; Feature 5 groundwork)
# ---------------------------------------------------------------------

class TestCVOwnership(FeatureTwoTestCase):

    def test_ut_2_14_001_ownership_is_recorded(self):
        write_cv_registry(self.registry, [cv_record()])
        self.assertTrue(cv_data_adapter.record_cv_ownership("John Doe", "cv-test-001", "cv.pdf"))
        self.assertEqual(len(cv_data_adapter.list_cv_ids_for("John Doe")), 1)

    def test_ut_2_14_002_unknown_jobseeker_has_none(self):
        self.assertEqual(cv_data_adapter.list_cv_ids_for("Someone Else"), [])

    def test_ut_2_14_003_missing_arguments_return_false(self):
        self.assertFalse(cv_data_adapter.record_cv_ownership("", "cv-1"))
        self.assertFalse(cv_data_adapter.record_cv_ownership("John Doe", ""))

    def test_ut_2_14_004_deleted_cv_disappears_from_the_picker(self):
        write_cv_registry(self.registry, [cv_record()])
        cv_data_adapter.record_cv_ownership("John Doe", "cv-test-001", "cv.pdf")
        write_cv_registry(self.registry, [])   # CV removed from Feature 3's store
        self.assertEqual(cv_data_adapter.list_cv_ids_for("John Doe"), [])

    def test_ut_2_14_005_database_failure_is_survivable(self):
        self.db.fail_on = "INSERT INTO jobseeker_cv"
        self.assertFalse(cv_data_adapter.record_cv_ownership("John Doe", "cv-1", "cv.pdf"))


if __name__ == "__main__":
    unittest.main()
