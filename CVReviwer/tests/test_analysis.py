"""Tests for Feature #4 (AI-Based CV Analysis and Scoring) — M-04-01 through M-04-14.

Test IDs follow the project convention: UT-4-<method>-<case>, matching the
UT-2-/UT-3- scheme the Feature 2 and Feature 3 suites use, and the cases
mirror TPF4-update.md.

No network and no API key are needed: cv_upload's registry is redirected to a
temp file, and OpenAI is replaced with a stub for M-04-02.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from helpers import make_pdf_with_text

import cv_upload
import cv_analysis as ca
from cv_upload import AIExtractionResult
from cv_analysis import (
    AIServiceUnavailableException,
    CVAnalysisException,
    CVDataCorruptedException,
    DatabaseException,
)


class FeatureFourTestCase(unittest.TestCase):
    """Fresh CV registry (and uploads dir for PDF-backed records) per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = os.path.join(self.tmp.name, "cvs.json")
        self.uploads = os.path.join(self.tmp.name, "uploads")
        os.makedirs(self.uploads, exist_ok=True)
        self._registry_orig = cv_upload.CVS_REGISTRY_FILE
        self._uploads_orig = cv_upload.UPLOADS_DIR
        cv_upload.CVS_REGISTRY_FILE = self.registry
        cv_upload.UPLOADS_DIR = self.uploads
        self._write([])

    def tearDown(self):
        cv_upload.CVS_REGISTRY_FILE = self._registry_orig
        cv_upload.UPLOADS_DIR = self._uploads_orig
        self.tmp.cleanup()

    def _write(self, records):
        with open(self.registry, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)

    def record(self, cv_id="cv_7f8a9b2c", *, skills=None, education=None,
               work_experience=None, raw_text=None, extracted=True,
               malformed_extracted=False):
        """One registry record in the shape M-03-09 storeExtractedCVInfo adds.

        raw_text given -> a real PDF is written on disk under UPLOADS_DIR and
        stored_path points at it, so retrieveCVForAnalysis re-extracts text.
        """
        stored_path = ""
        if raw_text is not None:
            stored_path = os.path.join(self.uploads, f"{cv_id}.pdf")
            with open(stored_path, "wb") as fh:
                fh.write(make_pdf_with_text(raw_text))
        record = {
            "id": cv_id,
            "jobseekerId": "John Doe",
            "original_filename": "cv.pdf",
            "stored_path": stored_path,
            "size_bytes": 1024,
            "sha256": "0" * 64,
            "uploaded_at": "2026-01-01T00:00:00+00:00",
            "validation_status": "validated",
        }
        if extracted:
            if malformed_extracted:
                record["extracted_data"] = "not a mapping"
            else:
                record["extracted_data"] = {
                    "skills": skills if skills is not None else [{"skill_name": "Python"}],
                    "education": education if education is not None else [{"degree": "BSc"}],
                    "work_experience": work_experience if work_experience is not None
                        else [{"company": "ABC"}],
                    "extracted_at": "2026-01-01T00:00:00+00:00",
                }
        return record

    def store(self, record):
        self._write([record])
        return record


# ---------------------------------------------------------------------
# UT-4-01 — retrieveCVForAnalysis (M-04-01)
# ---------------------------------------------------------------------

class TestRetrieveCVForAnalysis(FeatureFourTestCase):

    def test_ut_4_01_001_complete_data(self):
        self.store(self.record(raw_text="Tim Hammer\nEducation: BSc Software Engineering"))
        cv_data, raw_text, available = ca.retrieveCVForAnalysis("cv_7f8a9b2c")
        self.assertEqual(len(cv_data.skills), 1)
        self.assertEqual(len(cv_data.education), 1)
        self.assertEqual(len(cv_data.workExperience), 1)
        self.assertIn("Tim Hammer", raw_text)
        self.assertEqual(sorted(available),
                         ["education", "skills", "work_experience"])

    def test_ut_4_01_002_empty_skills(self):
        self.store(self.record(skills=[]))
        cv_data, _, available = ca.retrieveCVForAnalysis("cv_7f8a9b2c")
        self.assertEqual(cv_data.skills, [])
        self.assertEqual(len(cv_data.education), 1)
        self.assertEqual(len(cv_data.workExperience), 1)
        self.assertNotIn("skills", available)

    def test_ut_4_01_003_empty_education(self):
        self.store(self.record(education=[]))
        cv_data, _, _ = ca.retrieveCVForAnalysis("cv_7f8a9b2c")
        self.assertEqual(cv_data.education, [])

    def test_ut_4_01_004_empty_work_experience(self):
        self.store(self.record(work_experience=[]))
        cv_data, _, _ = ca.retrieveCVForAnalysis("cv_7f8a9b2c")
        self.assertEqual(cv_data.workExperience, [])

    def test_ut_4_01_005_all_arrays_empty_raw_text_present(self):
        self.store(self.record(skills=[], education=[], work_experience=[],
                               raw_text="Tim Hammer\nEducation: none"))
        cv_data, raw_text, _ = ca.retrieveCVForAnalysis("cv_7f8a9b2c")
        self.assertEqual(cv_data.skills, [])
        self.assertEqual(cv_data.education, [])
        self.assertEqual(cv_data.workExperience, [])
        self.assertTrue(raw_text)

    def test_ut_4_01_006_corrupted_cv_data(self):
        self.store(self.record(malformed_extracted=True))
        with self.assertRaises(CVDataCorruptedException):
            ca.retrieveCVForAnalysis("cv_7f8a9b2c")

    def test_ut_4_01_007_unknown_cv_raises(self):
        self.store(self.record())
        with self.assertRaises(CVDataCorruptedException):
            ca.retrieveCVForAnalysis("cv_nonexistent99")

    def test_ut_4_01_008_empty_cv_id(self):
        self.store(self.record())
        with self.assertRaises(CVDataCorruptedException):
            ca.retrieveCVForAnalysis("")

    def test_ut_4_01_009_maximum_realistic_size(self):
        skills = [{"skill_name": f"skill{i}", "proficiency_level": "Advanced"}
                  for i in range(60)]
        education = [{"institution": f"U{i}", "degree": "BSc"} for i in range(20)]
        work_experience = [{"company": f"C{i}", "description": "x" * 200}
                           for i in range(30)]
        self.store(self.record(skills=skills, education=education,
                               work_experience=work_experience,
                               raw_text="x" * 50000))
        cv_data, raw_text, available = ca.retrieveCVForAnalysis("cv_7f8a9b2c")
        self.assertEqual(len(cv_data.skills), 60)
        self.assertEqual(len(cv_data.education), 20)
        self.assertEqual(len(cv_data.workExperience), 30)
        self.assertEqual(len(raw_text), 50000)
        self.assertEqual(sorted(available),
                         ["education", "skills", "work_experience"])

    def test_ut_4_01_010_raw_text_null_raises(self):
        self.store(self.record(raw_text=None))
        with self.assertRaises(CVDataCorruptedException):
            ca.retrieveCVForAnalysis("cv_7f8a9b2c")


# ---------------------------------------------------------------------
# UT-4-02 — requestCVAnalysis (M-04-02)
# ---------------------------------------------------------------------

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def create(self, **kwargs):
        if self.error is not None:
            raise self.error
        return _FakeResponse(self.payload)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, completions):
        self.chat = _FakeChat(completions)


class _FakeOpenAI:
    def __init__(self, completions):
        self.completions = completions

    def __call__(self, api_key=None):
        return _FakeClient(self.completions)


_OK_PAYLOAD = json.dumps({
    "completeness_score": 0.85,
    "relevance_score": 0.78,
    "clarity_score": 0.92,
    "overall_score": 0.85,
    "suggestions": [],
})


class TestRequestCVAnalysis(FeatureFourTestCase):

    def _patch(self, payload=None, error=None):
        self._orig = ca.OpenAI
        ca.OpenAI = _FakeOpenAI(_FakeCompletions(payload=payload, error=error))

    def tearDown(self):
        if hasattr(self, "_orig"):
            ca.OpenAI = self._orig
        super().tearDown()

    def test_ut_4_02_001_successful_analysis_request(self):
        self._patch(payload=_OK_PAYLOAD)
        cv_data = AIExtractionResult(
            skills=[{"skill_name": "Python", "proficiency_level": "Advanced"}],
            education=[{"institution": "CMU", "degree": "B.Sc.",
                        "graduation_year": "2026"}],
            workExperience=[{"company": "ABC", "position": "Developer"}],
        )
        result = ca.requestCVAnalysis(
            cv_data, "Tim Hammer\nEducation: ...",
            ["skills", "education", "work_experience"])
        self.assertIsInstance(result, ca.CVAnalysisResult)
        self.assertEqual(result.completenessScore, 0.85)
        self.assertEqual(result.relevanceScore, 0.78)
        self.assertEqual(result.clarityScore, 0.92)
        self.assertEqual(result.overallScore, 0.85)

    def test_ut_4_02_002_minimal_cv_data(self):
        self._patch(payload=_OK_PAYLOAD)
        result = ca.requestCVAnalysis(AIExtractionResult(), "", [])
        self.assertIsInstance(result, ca.CVAnalysisResult)

    def test_ut_4_02_003_raw_text_maximum_length(self):
        self._patch(payload=_OK_PAYLOAD)
        result = ca.requestCVAnalysis(
            AIExtractionResult(skills=[{"skill_name": "Python"}]),
            "x" * 50000, ["skills"])
        self.assertIsInstance(result, ca.CVAnalysisResult)

    def test_ut_4_02_004_service_timeout(self):
        self._patch(error=TimeoutError("timed out"))
        with self.assertRaises(AIServiceUnavailableException):
            ca.requestCVAnalysis(AIExtractionResult(), "text",
                                 ["skills"])

    def test_ut_4_02_005_service_error(self):
        self._patch(error=RuntimeError("500 Internal Server Error"))
        with self.assertRaises(AIServiceUnavailableException):
            ca.requestCVAnalysis(AIExtractionResult(), "text",
                                 ["skills"])

    def test_ut_4_02_006_only_one_category(self):
        self._patch(payload=_OK_PAYLOAD)
        cv_data = AIExtractionResult(skills=[{"skill_name": "SQL"}])
        result = ca.requestCVAnalysis(cv_data, "text", ["skills"])
        self.assertIsInstance(result, ca.CVAnalysisResult)

    def test_ut_4_02_007_unicode_content(self):
        self._patch(payload=_OK_PAYLOAD)
        cv_data = AIExtractionResult(skills=[{"skill_name": "ภาษาไทย"}])
        result = ca.requestCVAnalysis(
            cv_data, "ชื: ทดสอบ ระบบ\nEducation: Ph.D.", ["skills"])
        self.assertIsInstance(result, ca.CVAnalysisResult)

    def test_ut_4_02_008_connection_failure(self):
        self._patch(error=ConnectionError("connection refused"))
        with self.assertRaises(AIServiceUnavailableException):
            ca.requestCVAnalysis(AIExtractionResult(), "text",
                                 ["skills"])

    def test_ut_4_02_009_rate_limit(self):
        self._patch(error=RuntimeError("429 Too Many Requests"))
        with self.assertRaises(AIServiceUnavailableException):
            ca.requestCVAnalysis(AIExtractionResult(), "text",
                                 ["skills"])


# ---------------------------------------------------------------------
# UT-4-03 — extractCompletenessScore (M-04-03)
# ---------------------------------------------------------------------

class TestExtractCompletenessScore(FeatureFourTestCase):

    def _result(self, completeness="__present__", **overrides):
        data = {"completeness_score": 85, "relevance_score": 78,
                "clarity_score": 92, "overall_score": 85, "suggestions": []}
        data.update(overrides)
        if completeness == "MISSING":
            data.pop("completeness_score", None)
        elif completeness != "__present__":
            data["completeness_score"] = completeness
        return data

    def test_ut_4_03_001_valid_score_within_range(self):
        self.assertEqual(ca.extractCompletenessScore(self._result()), 85)

    def test_ut_4_03_002_lower_boundary(self):
        self.assertEqual(ca.extractCompletenessScore(self._result(0)), 0)

    def test_ut_4_03_003_upper_boundary(self):
        self.assertEqual(ca.extractCompletenessScore(self._result(100)), 100)

    def test_ut_4_03_004_missing_field(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractCompletenessScore(self._result("MISSING"))

    def test_ut_4_03_005_malformed_non_numeric(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractCompletenessScore(self._result("high"))

    def test_ut_4_03_006_below_valid_range(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractCompletenessScore(self._result(-5))

    def test_ut_4_03_007_above_valid_range(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractCompletenessScore(self._result(105))

    def test_ut_4_03_008_decimal_value(self):
        self.assertEqual(ca.extractCompletenessScore(self._result(85.5)), 85.5)

    def test_ut_4_03_009_null_result(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractCompletenessScore(None)

    def test_ut_4_03_010_wrong_type_boolean(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractCompletenessScore(self._result(True))


# ---------------------------------------------------------------------
# UT-4-04 — calculateCompletenessScore (M-04-04)
# ---------------------------------------------------------------------

class TestCalculateCompletenessScore(FeatureFourTestCase):

    def test_ut_4_04_001_full_data_all_categories(self):
        cv_data = AIExtractionResult(
            skills=[{"skill_name": s} for s in ["Python", "SQL", "Java", "C++",
                                                "Go", "Rust", "JS", "HTML",
                                                "CSS", "Bash"]],
            education=[{"degree": "BSc", "start_year": 2019, "end_year": 2023},
                       {"degree": "MSc", "start_year": 2023, "end_year": 2025}],
            workExperience=[{"company": "A", "start_date": "2021", "description": "x" * 100},
                            {"company": "B", "start_date": "2023", "description": "x" * 100}],
        )
        score = ca.calculateCompletenessScore(
            cv_data, ["skills", "education", "work_experience"])
        self.assertGreaterEqual(score, 0.5)

    def test_ut_4_04_002_all_categories_empty(self):
        score = ca.calculateCompletenessScore(AIExtractionResult(), [])
        self.assertLessEqual(score, 0.05)

    def test_ut_4_04_003_only_skills_available(self):
        cv_data = AIExtractionResult(skills=[{"skill_name": "Python"},
                                             {"skill_name": "SQL"}])
        score = ca.calculateCompletenessScore(cv_data, ["skills"])
        self.assertGreater(score, 0.0)

    def test_ut_4_04_004_only_education_available(self):
        cv_data = AIExtractionResult(education=[{"degree": "BSc"}])
        score = ca.calculateCompletenessScore(cv_data, ["education"])
        self.assertGreater(score, 0.0)

    def test_ut_4_04_005_only_work_experience_available(self):
        cv_data = AIExtractionResult(workExperience=[{"company": "A"}])
        score = ca.calculateCompletenessScore(cv_data, ["work_experience"])
        self.assertGreater(score, 0.0)

    def test_ut_4_04_006_two_of_three_categories(self):
        cv_data = AIExtractionResult(
            skills=[{"skill_name": "Python"}],
            education=[{"degree": "BSc"}],
        )
        score = ca.calculateCompletenessScore(cv_data, ["skills", "education"])
        self.assertGreaterEqual(score, 0.0)

    def test_ut_4_04_007_available_contains_category_without_data(self):
        cv_data = AIExtractionResult(
            education=[{"degree": "BSc"}],
            workExperience=[{"company": "A"}],
        )
        score = ca.calculateCompletenessScore(
            cv_data, ["skills", "education", "work_experience"])
        self.assertGreaterEqual(score, 0.0)

    def test_ut_4_04_008_lower_boundary(self):
        cv_data = AIExtractionResult(skills=[{"skill_name": "x"}])
        score = ca.calculateCompletenessScore(cv_data, ["skills"])
        self.assertLessEqual(score, 0.3)

    def test_ut_4_04_009_upper_boundary(self):
        cv_data = AIExtractionResult(
            skills=[{"skill_name": f"s{i}", "proficiency_level": "Advanced"}
                    for i in range(30)],
            education=[{"degree": "BSc", "start_year": 2019, "end_year": 2023},
                       {"degree": "MSc", "start_year": 2023, "end_year": 2025},
                       {"degree": "PhD", "start_year": 2025, "end_year": 2028}],
            workExperience=[{"company": f"C{i}", "start_date": "2015",
                             "description": "x" * 200} for i in range(10)],
        )
        score = ca.calculateCompletenessScore(
            cv_data, ["skills", "education", "work_experience"])
        self.assertGreaterEqual(score, 0.8)

    def test_ut_4_04_010_null_cv_data(self):
        with self.assertRaises(Exception):
            ca.calculateCompletenessScore(None, ["skills"])


# ---------------------------------------------------------------------
# UT-4-05 — extractRelevanceScore (M-04-05)
# ---------------------------------------------------------------------

class TestExtractRelevanceScore(FeatureFourTestCase):

    def _result(self, relevance="__present__"):
        data = {"completeness_score": 85, "relevance_score": 78,
                "clarity_score": 92, "overall_score": 85, "suggestions": []}
        if relevance == "MISSING":
            data.pop("relevance_score", None)
        elif relevance != "__present__":
            data["relevance_score"] = relevance
        return data

    def test_ut_4_05_001_valid_score_within_range(self):
        self.assertEqual(ca.extractRelevanceScore(self._result()), 78)

    def test_ut_4_05_002_lower_boundary(self):
        self.assertEqual(ca.extractRelevanceScore(self._result(0)), 0)

    def test_ut_4_05_003_upper_boundary(self):
        self.assertEqual(ca.extractRelevanceScore(self._result(100)), 100)

    def test_ut_4_05_004_missing_field(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractRelevanceScore(self._result("MISSING"))

    def test_ut_4_05_005_malformed_non_numeric(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractRelevanceScore(self._result("n/a"))

    def test_ut_4_05_006_below_valid_range(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractRelevanceScore(self._result(-10))

    def test_ut_4_05_007_above_valid_range(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractRelevanceScore(self._result(150))

    def test_ut_4_05_008_decimal_value(self):
        self.assertEqual(ca.extractRelevanceScore(self._result(78.25)), 78.25)

    def test_ut_4_05_009_null_result(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractRelevanceScore(None)

    def test_ut_4_05_010_wrong_type_boolean(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractRelevanceScore(self._result(False))


# ---------------------------------------------------------------------
# UT-4-06 — calculateRelevanceScore (M-04-06)
# ---------------------------------------------------------------------

class TestCalculateRelevanceScore(FeatureFourTestCase):

    def test_ut_4_06_001_strong_alignment(self):
        cv_data = AIExtractionResult(
            skills=[{"skill_name": "Python", "proficiency_level": "Advanced"},
                    {"skill_name": "SQL", "proficiency_level": "Expert"},
                    {"skill_name": "AWS", "proficiency_level": "Advanced"},
                    {"skill_name": "Docker", "proficiency_level": "Intermediate"},
                    {"skill_name": "Kubernetes", "proficiency_level": "Advanced"}],
            workExperience=[{"company": "A", "description": "Built distributed systems " * 8}],
        )
        score = ca.calculateRelevanceScore(
            cv_data, ["skills", "education", "work_experience"])
        self.assertGreaterEqual(score, 0.5)

    def test_ut_4_06_002_weak_alignment(self):
        cv_data = AIExtractionResult(
            skills=[{"skill_name": "hardworking"}, {"skill_name": "teamwork"}],
            workExperience=[{"company": "A", "description": "worked"}],
        )
        score = ca.calculateRelevanceScore(
            cv_data, ["skills", "education", "work_experience"])
        self.assertLessEqual(score, 0.5)

    def test_ut_4_06_003_only_skills_available(self):
        cv_data = AIExtractionResult(
            skills=[{"skill_name": "Python", "proficiency_level": "Advanced"}])
        score = ca.calculateRelevanceScore(cv_data, ["skills"])
        self.assertGreater(score, 0.0)

    def test_ut_4_06_004_only_education_available(self):
        cv_data = AIExtractionResult(education=[{"degree": "BSc"}])
        score = ca.calculateRelevanceScore(cv_data, ["education"])
        self.assertGreaterEqual(score, 0.0)

    def test_ut_4_06_005_only_work_experience_available(self):
        cv_data = AIExtractionResult(workExperience=[{"company": "A"}])
        score = ca.calculateRelevanceScore(cv_data, ["work_experience"])
        self.assertGreaterEqual(score, 0.0)

    def test_ut_4_06_006_two_of_three_categories(self):
        cv_data = AIExtractionResult(
            skills=[{"skill_name": "Python", "proficiency_level": "Advanced"}],
            workExperience=[{"company": "A", "description": "x" * 100}],
        )
        score = ca.calculateRelevanceScore(cv_data, ["skills", "work_experience"])
        self.assertGreaterEqual(score, 0.0)

    def test_ut_4_06_007_lower_boundary(self):
        cv_data = AIExtractionResult(skills=[{"skill_name": "hardworking"}])
        score = ca.calculateRelevanceScore(cv_data, ["skills"])
        self.assertLessEqual(score, 0.5)

    def test_ut_4_06_008_upper_boundary(self):
        cv_data = AIExtractionResult(
            skills=[{"skill_name": f"s{i}", "proficiency_level": "Expert"}
                    for i in range(15)],
            workExperience=[{"company": f"C{i}", "description": "x" * 200}
                            for i in range(8)],
        )
        score = ca.calculateRelevanceScore(
            cv_data, ["skills", "education", "work_experience"])
        self.assertGreaterEqual(score, 0.7)

    def test_ut_4_06_009_null_cv_data(self):
        with self.assertRaises(Exception):
            ca.calculateRelevanceScore(None, ["skills"])

    def test_ut_4_06_010_empty_available_categories(self):
        cv_data = AIExtractionResult(skills=[{"skill_name": "Python"}])
        score = ca.calculateRelevanceScore(cv_data, [])
        self.assertEqual(score, 0.0)


# ---------------------------------------------------------------------
# UT-4-07 — extractClarityScore (M-04-07)
# ---------------------------------------------------------------------

class TestExtractClarityScore(FeatureFourTestCase):

    def _result(self, clarity="__present__"):
        data = {"completeness_score": 85, "relevance_score": 78,
                "clarity_score": 92, "overall_score": 85, "suggestions": []}
        if clarity == "MISSING":
            data.pop("clarity_score", None)
        elif clarity != "__present__":
            data["clarity_score"] = clarity
        return data

    def test_ut_4_07_001_valid_score_within_range(self):
        self.assertEqual(ca.extractClarityScore(self._result()), 92)

    def test_ut_4_07_002_lower_boundary(self):
        self.assertEqual(ca.extractClarityScore(self._result(0)), 0)

    def test_ut_4_07_003_upper_boundary(self):
        self.assertEqual(ca.extractClarityScore(self._result(100)), 100)

    def test_ut_4_07_004_missing_field(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractClarityScore(self._result("MISSING"))

    def test_ut_4_07_005_malformed_null_value(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractClarityScore(self._result(None))

    def test_ut_4_07_006_below_valid_range(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractClarityScore(self._result(-1))

    def test_ut_4_07_007_above_valid_range(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractClarityScore(self._result(101))

    def test_ut_4_07_008_decimal_value(self):
        self.assertEqual(ca.extractClarityScore(self._result(91.75)), 91.75)

    def test_ut_4_07_009_null_result(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractClarityScore(None)

    def test_ut_4_07_010_wrong_type_array(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractClarityScore(self._result([90]))


# ---------------------------------------------------------------------
# UT-4-08 — calculateClarityScore (M-04-08)
# ---------------------------------------------------------------------

class TestCalculateClarityScore(FeatureFourTestCase):

    def test_ut_4_08_001_well_formatted(self):
        raw = ("I developed and maintained the core platform. I implemented "
               "the search engine and improved performance. I managed a team "
               "and created dashboards. I designed the API and delivered on "
               "time. I built automated tests and optimized the pipeline.\n"
               "- bullet one\n- bullet two\n- bullet three\n- bullet four\n"
               "- bullet five\nBudget 5,000,000")
        score = ca.calculateClarityScore(raw, [])
        self.assertGreaterEqual(score, 0.5)

    def test_ut_4_08_002_poorly_formatted(self):
        raw = ("worked on stuff did some things and then more stuff happened "
               "over a long period of time with no structure whatsoever")
        score = ca.calculateClarityScore(raw, [])
        self.assertLessEqual(score, 0.5)

    def test_ut_4_08_003_empty_raw_text(self):
        score = ca.calculateClarityScore("", [])
        self.assertLessEqual(score, 0.4)

    def test_ut_4_08_004_empty_work_experience(self):
        raw = ("I developed the platform. I implemented the search. I managed "
               "the team. I designed the API. I built the pipeline. I optimized "
               "the database. I delivered on time. I created dashboards.\n"
               "- a\n- b\n- c\n- d\n- e\nYear 2024")
        score = ca.calculateClarityScore(raw, [])
        self.assertGreater(score, 0.0)

    def test_ut_4_08_005_raw_text_maximum_length(self):
        raw = "I developed the platform. I implemented the search. " * 4000
        work = [{"company": "A", "description": "x" * 100}]
        score = ca.calculateClarityScore(raw, work)
        self.assertGreaterEqual(score, 0.0)

    def test_ut_4_08_006_unicode_content(self):
        raw = "ทดสอบ ระบบ CV. ประสบการณ์ทำงาน. การศึกษา."
        score = ca.calculateClarityScore(raw, [])
        self.assertGreaterEqual(score, 0.0)

    def test_ut_4_08_007_rich_work_experience_detail(self):
        raw = "worked"
        work = [{"company": "A", "description": "x" * 100},
                {"company": "B", "description": "y" * 100}]
        score = ca.calculateClarityScore(raw, work)
        self.assertGreater(score, 0.0)

    def test_ut_4_08_008_lower_boundary(self):
        score = ca.calculateClarityScore("x", [])
        self.assertLessEqual(score, 0.4)

    def test_ut_4_08_009_upper_boundary(self):
        raw = ("I developed and implemented the platform. I managed and "
               "designed the core system. I created and optimized the pipeline. "
               "I built and delivered the solution. I led and improved the team. "
               "I analyzed and coordinated the release. I established and "
               "generated the reports. I achieved and delivered the goals.\n"
               "- one\n- two\n- three\n- four\n- five\nBudget 5,000,000")
        work = [{"company": "A", "description": "x" * 200},
                {"company": "B", "description": "y" * 200}]
        score = ca.calculateClarityScore(raw, work)
        self.assertGreaterEqual(score, 0.6)

    def test_ut_4_08_010_null_raw_text(self):
        with self.assertRaises(Exception):
            ca.calculateClarityScore(None, [])


# ---------------------------------------------------------------------
# UT-4-09 — extractOverallScore (M-04-09)
# ---------------------------------------------------------------------

class TestExtractOverallScore(FeatureFourTestCase):

    def _result(self, overall="__present__"):
        data = {"completeness_score": 85, "relevance_score": 78,
                "clarity_score": 92, "overall_score": 88, "suggestions": []}
        if overall == "MISSING":
            data.pop("overall_score", None)
        elif overall != "__present__":
            data["overall_score"] = overall
        return data

    def test_ut_4_09_001_valid_score_within_range(self):
        self.assertEqual(ca.extractOverallScore(self._result()), 88)

    def test_ut_4_09_002_lower_boundary(self):
        self.assertEqual(ca.extractOverallScore(self._result(0)), 0)

    def test_ut_4_09_003_upper_boundary(self):
        self.assertEqual(ca.extractOverallScore(self._result(100)), 100)

    def test_ut_4_09_004_missing_field(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractOverallScore(self._result("MISSING"))

    def test_ut_4_09_005_malformed_non_numeric(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractOverallScore(self._result("eighty"))

    def test_ut_4_09_006_below_valid_range(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractOverallScore(self._result(-20))

    def test_ut_4_09_007_above_valid_range(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractOverallScore(self._result(120))

    def test_ut_4_09_008_decimal_value(self):
        self.assertEqual(ca.extractOverallScore(self._result(87.4)), 87.4)

    def test_ut_4_09_009_null_result(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractOverallScore(None)

    def test_ut_4_09_010_wrong_type_string_with_units(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractOverallScore(self._result("88pts"))


# ---------------------------------------------------------------------
# UT-4-10 — calculateOverallScore (M-04-10)
# ---------------------------------------------------------------------

class TestCalculateOverallScore(FeatureFourTestCase):

    def test_ut_4_10_001_all_three_present(self):
        score = ca.calculateOverallScore(
            0.8, 0.75, 0.85, ["skills", "education", "work_experience"])
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_ut_4_10_002_one_category_unavailable(self):
        score = ca.calculateOverallScore(0.8, 0.75, 0.85, ["skills", "education"])
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_ut_4_10_003_two_categories_unavailable(self):
        score = ca.calculateOverallScore(0.8, 0.0, 0.0, ["skills"])
        self.assertGreaterEqual(score, 0.0)

    def test_ut_4_10_004_empty_available_categories(self):
        with self.assertRaises(CVAnalysisException):
            ca.calculateOverallScore(0.0, 0.0, 0.0, [])

    def test_ut_4_10_005_all_scores_minimum(self):
        score = ca.calculateOverallScore(
            0.0, 0.0, 0.0, ["skills", "education", "work_experience"])
        self.assertEqual(score, 0.0)

    def test_ut_4_10_006_all_scores_maximum(self):
        score = ca.calculateOverallScore(
            1.0, 1.0, 1.0, ["skills", "education", "work_experience"])
        self.assertEqual(score, 1.0)

    def test_ut_4_10_007_mixed_extreme_values(self):
        score = ca.calculateOverallScore(
            1.0, 0.0, 1.0, ["skills", "education", "work_experience"])
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_ut_4_10_008_category_score_outside_range(self):
        score = ca.calculateOverallScore(
            120, 0.75, 0.85, ["skills", "education", "work_experience"])
        self.assertGreaterEqual(score, 0.0)

    def test_ut_4_10_009_boundary_above_minimum(self):
        score = ca.calculateOverallScore(
            0.01, 0.01, 0.01, ["skills", "education", "work_experience"])
        self.assertGreater(score, 0.0)

    def test_ut_4_10_010_internal_calculation_error(self):
        with self.assertRaises(CVAnalysisException):
            ca.calculateOverallScore(
                "not-a-number", 0.75, 0.85, ["skills", "education", "work_experience"])


# ---------------------------------------------------------------------
# UT-4-11 — extractImprovementSuggestions (M-04-11)
# ---------------------------------------------------------------------

class TestExtractImprovementSuggestions(FeatureFourTestCase):

    def _result(self, suggestions="MISSING", **overrides):
        data = {"completeness_score": 85, "relevance_score": 65,
                "clarity_score": 92, "overall_score": 85,
                "suggestions": ["Add more industry-relevant keywords"]}
        data.update(overrides)
        if suggestions == "MISSING":
            data.pop("suggestions", None)
        else:
            data["suggestions"] = suggestions
        return data

    def test_ut_4_11_001_valid_list(self):
        suggestions = ca.extractImprovementSuggestions(
            self._result(["Add more industry-relevant keywords to your skills section"]))
        self.assertEqual(len(suggestions), 1)

    def test_ut_4_11_002_all_categories_ge_70(self):
        suggestions = ca.extractImprovementSuggestions(self._result([]))
        self.assertEqual(suggestions, [])

    def test_ut_4_11_003_suggestions_not_a_list(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractImprovementSuggestions(self._result("Add more detail"))

    def test_ut_4_11_004_non_string_entries(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractImprovementSuggestions(self._result([123, True]))

    def test_ut_4_11_005_suggestions_missing(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractImprovementSuggestions(self._result())

    def test_ut_4_11_006_duplicate_entries(self):
        suggestions = ca.extractImprovementSuggestions(
            self._result(["Add more keywords", "Add more keywords"]))
        self.assertEqual(suggestions, ["Add more keywords", "Add more keywords"])

    def test_ut_4_11_007_empty_string_entry(self):
        suggestions = ca.extractImprovementSuggestions(self._result([""]))
        self.assertEqual(suggestions, [""])

    def test_ut_4_11_008_null_result(self):
        with self.assertRaises(CVAnalysisException):
            ca.extractImprovementSuggestions(None)


# ---------------------------------------------------------------------
# UT-4-12 — storeCVAnalysis (M-04-12)
# ---------------------------------------------------------------------

class TestStoreCVAnalysis(FeatureFourTestCase):

    def _analysis(self, overall=72, completeness=80, relevance=65, clarity=70,
                  suggestions=None):
        return ca.CVAnalysisResult(
            overallScore=overall, completenessScore=completeness,
            relevanceScore=relevance, clarityScore=clarity,
            suggestions=suggestions if suggestions is not None else [],
            analyzedAt="2026-01-01T00:00:00+00:00")

    def test_ut_4_12_001_successful_insert(self):
        self.store(self.record())
        ca.storeCVAnalysis(
            "cv_7f8a9b2c",
            self._analysis(suggestions=["Add more detail to work experience descriptions"]))
        with open(self.registry, encoding="utf-8") as fh:
            record = json.load(fh)[0]
        self.assertEqual(record["analysis"]["overallScore"], 72)
        self.assertEqual(len(record["analysis"]["suggestions"]), 1)

    def test_ut_4_12_002_empty_suggestions(self):
        self.store(self.record())
        ca.storeCVAnalysis("cv_7f8a9b2c", self._analysis(overall=90))
        with open(self.registry, encoding="utf-8") as fh:
            record = json.load(fh)[0]
        self.assertEqual(record["analysis"]["suggestions"], [])

    def test_ut_4_12_003_database_insert_failure(self):
        self.store(self.record())
        with self.assertRaises(DatabaseException):
            ca.storeCVAnalysis("cv_nonexistent", self._analysis())

    def test_ut_4_12_004_nonexistent_cv_id(self):
        with self.assertRaises(DatabaseException):
            ca.storeCVAnalysis("cv_does_not_exist", self._analysis())

    def test_ut_4_12_005_scores_at_minimum(self):
        self.store(self.record())
        ca.storeCVAnalysis(
            "cv_7f8a9b2c", self._analysis(0, 0, 0, 0, ["...", "...", "..."]))
        with open(self.registry, encoding="utf-8") as fh:
            record = json.load(fh)[0]
        self.assertEqual(record["analysis"]["overallScore"], 0)

    def test_ut_4_12_006_scores_at_maximum(self):
        self.store(self.record())
        ca.storeCVAnalysis("cv_7f8a9b2c", self._analysis(100, 100, 100, 100, []))
        with open(self.registry, encoding="utf-8") as fh:
            record = json.load(fh)[0]
        self.assertEqual(record["analysis"]["overallScore"], 100)

    def test_ut_4_12_007_suggestions_for_all_categories(self):
        self.store(self.record())
        ca.storeCVAnalysis(
            "cv_7f8a9b2c", self._analysis(60, 65, 68, 62, ["...", "...", "..."]))
        with open(self.registry, encoding="utf-8") as fh:
            record = json.load(fh)[0]
        self.assertEqual(len(record["analysis"]["suggestions"]), 3)

    def test_ut_4_12_008_re_analysis_overwrites_prior(self):
        self.store(self.record())
        ca.storeCVAnalysis("cv_7f8a9b2c", self._analysis(overall=50))
        ca.storeCVAnalysis("cv_7f8a9b2c", self._analysis(overall=72))
        with open(self.registry, encoding="utf-8") as fh:
            record = json.load(fh)[0]
        self.assertEqual(record["analysis"]["overallScore"], 72)

    def test_ut_4_12_009_empty_string_suggestion(self):
        self.store(self.record())
        ca.storeCVAnalysis("cv_7f8a9b2c", self._analysis(suggestions=[""]))
        with open(self.registry, encoding="utf-8") as fh:
            record = json.load(fh)[0]
        self.assertEqual(record["analysis"]["suggestions"], [""])


# ---------------------------------------------------------------------
# UT-4-13 — displayCVAnalysis (M-04-13)
# ---------------------------------------------------------------------

class TestDisplayCVAnalysis(FeatureFourTestCase):

    def test_ut_4_13_001_display_with_suggestions(self):
        record = self.record()
        record["analysis"] = {
            "overallScore": 72, "completenessScore": 80, "relevanceScore": 65,
            "clarityScore": 70, "suggestions": ["Improve work experience"],
            "analyzedAt": "2026-01-01T00:00:00+00:00",
        }
        self.store(record)
        analysis = ca.displayCVAnalysis("cv_7f8a9b2c")
        self.assertEqual(analysis["overallScore"], 72)
        self.assertEqual(len(analysis["suggestions"]), 1)

    def test_ut_4_13_002_display_without_suggestions(self):
        record = self.record()
        record["analysis"] = {
            "overallScore": 90, "completenessScore": 95, "relevanceScore": 88,
            "clarityScore": 92, "suggestions": [],
            "analyzedAt": "2026-01-01T00:00:00+00:00",
        }
        self.store(record)
        analysis = ca.displayCVAnalysis("cv_7f8a9b2c")
        self.assertEqual(analysis["suggestions"], [])

    def test_ut_4_13_003_no_stored_analysis(self):
        self.store(self.record())
        analysis = ca.displayCVAnalysis("cv_7f8a9b2c")
        self.assertIsNone(analysis)

    def test_ut_4_13_004_empty_cv_id(self):
        self.store(self.record())
        analysis = ca.displayCVAnalysis("")
        self.assertIsNone(analysis)

    def test_ut_4_13_005_multiple_analysis_records(self):
        record = self.record()
        record["analysis"] = {
            "overallScore": 50, "suggestions": [], "analyzedAt": "2026-01-01T00:00:00+00:00",
        }
        self.store(record)
        analysis = ca.displayCVAnalysis("cv_7f8a9b2c")
        self.assertEqual(analysis["overallScore"], 50)


# ---------------------------------------------------------------------
# UT-4-14 — handleAnalysisError (M-04-14)
# ---------------------------------------------------------------------

class TestHandleAnalysisError(FeatureFourTestCase):

    def test_ut_4_14_001_ai_service_unavailable(self):
        self.assertEqual(
            ca.handleAnalysisError(AIServiceUnavailableException()),
            "The CV score could not be generated at this time")

    def test_ut_4_14_002_cv_data_corrupted(self):
        self.assertEqual(
            ca.handleAnalysisError(CVDataCorruptedException()),
            "Your CV data could not be read — please re-upload your CV")

    def test_ut_4_14_003_cv_analysis_exception(self):
        self.assertEqual(
            ca.handleAnalysisError(CVAnalysisException()),
            "An error occurred while calculating your CV score")

    def test_ut_4_14_004_unmapped_exception_type(self):
        message = ca.handleAnalysisError(DatabaseException())
        self.assertNotEqual(
            message, "The CV score could not be generated at this time")

    def test_ut_4_14_005_unrecognized_custom_exception(self):
        message = ca.handleAnalysisError(ValueError("boom"))
        self.assertNotEqual(
            message, "An error occurred while calculating your CV score")

    def test_ut_4_14_006_null_exception(self):
        message = ca.handleAnalysisError(None)
        self.assertIsInstance(message, str)

    def test_ut_4_14_007_subclass_of_mapped_type(self):
        class SubClass(CVAnalysisException):
            pass
        self.assertEqual(
            ca.handleAnalysisError(SubClass()),
            "An error occurred while calculating your CV score")


if __name__ == "__main__":
    unittest.main()
