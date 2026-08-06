"""Tests for cv_upload.py — M-023 through M-031."""

import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cv_upload import (
    uploadCVFile, displayUploadFeedback, handleUploadError,
    validateCVFile, storeCVFile, extractTextFromCV,
    validateExtractionResult, storeExtractedCVInfo,
    InvalidFileFormatException, FileSizeExceededException,
    CorruptedFileException, StorageException, ExtractionPreparationException,
    NoExtractionResultException, MissingErrorMessageException, DatabaseException,
    AIExtractionResult, MAX_CV_BYTES,
)

from tests.helpers import (
    MockFile, make_valid_pdf, make_pdf_with_text, make_large_pdf, make_corrupted_pdf,
    make_docx_data, make_exe_data, TestEnvironment,
)


class TestUploadCVFile(unittest.TestCase):
    """UT-3-01: uploadCVFile(file, jobseekerId)"""

    @classmethod
    def setUpClass(cls):
        cls.valid_pdf = make_valid_pdf()
        cls.big_pdf = make_large_pdf(MAX_CV_BYTES + 1)
        cls.exact_pdf = make_large_pdf(MAX_CV_BYTES)

    def setUp(self):
        self.env = TestEnvironment()

    def tearDown(self):
        self.env.cleanup()

    def test_ut_3_01_001_successful_upload(self):
        file = MockFile(name="resume.pdf", data=self.valid_pdf, mime_type="application/pdf")
        result = uploadCVFile(file, "job-001")
        self.assertTrue(result["success"])
        self.assertIn("cvFileId", result)
        self.assertIn("fileName", result)

    def test_ut_3_01_002_invalid_file_format(self):
        file = MockFile(name="resume.docx", data=make_docx_data(), mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with self.assertRaises(InvalidFileFormatException):
            uploadCVFile(file, "job-001")

    def test_ut_3_01_003_file_size_exceeded(self):
        file = MockFile(name="resume.pdf", data=self.big_pdf, mime_type="application/pdf")
        with self.assertRaises(FileSizeExceededException):
            uploadCVFile(file, "job-001")

    def test_ut_3_01_004_corrupted_file(self):
        file = MockFile(name="resume.pdf", data=make_corrupted_pdf(), mime_type="application/pdf")
        with self.assertRaises(CorruptedFileException):
            uploadCVFile(file, "job-001")

    def test_ut_3_01_005_storage_failure(self):
        file = MockFile(name="resume.pdf", data=self.valid_pdf, mime_type="application/pdf")
        with patch("cv_upload.storeCVFile", side_effect=StorageException("Storage error")):
            with self.assertRaises(StorageException):
                uploadCVFile(file, "job-001")

    def test_ut_3_01_006_boundary_exactly_20mb(self):
        file = MockFile(name="resume.pdf", data=self.exact_pdf, mime_type="application/pdf")
        result = uploadCVFile(file, "job-001")
        self.assertTrue(result["success"])

    def test_ut_3_01_007_boundary_20mb_plus_1(self):
        file = MockFile(name="resume.pdf", data=self.big_pdf, mime_type="application/pdf")
        with self.assertRaises(FileSizeExceededException):
            uploadCVFile(file, "job-001")

    def test_ut_3_01_008_invalid_jobseeker_id(self):
        file = MockFile(name="resume.pdf", data=self.valid_pdf, mime_type="application/pdf")
        result = uploadCVFile(file, "")
        self.assertTrue(result["success"])


class TestDisplayUploadFeedback(unittest.TestCase):
    """UT-3-02: displayUploadFeedback(fileName, success, errorMessage)"""

    def setUp(self):
        self.env = TestEnvironment()

    def tearDown(self):
        self.env.cleanup()

    def _run(self, *args, **kwargs):
        with patch("sys.stdout", new_callable=io.StringIO):
            try:
                displayUploadFeedback(*args, **kwargs)
            except Exception:
                raise

    def test_ut_3_02_001_success_no_error_message(self):
        try:
            self._run("resume.pdf", True)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_02_002_success_error_message_ignored(self):
        try:
            self._run("resume.pdf", True, errorMessage="File is corrupted or unreadable")
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_02_003_failure_with_valid_error_message(self):
        try:
            self._run("resume.pdf", False, errorMessage="Unsupported file format")
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_02_004_failure_missing_error_message(self):
        with self.assertRaises(MissingErrorMessageException):
            self._run("resume.pdf", False)

    def test_ut_3_02_005_failure_empty_string_error_message(self):
        with self.assertRaises(MissingErrorMessageException):
            self._run("resume.pdf", False, errorMessage="")

    def test_ut_3_02_006_failure_whitespace_error_message(self):
        try:
            self._run("resume.pdf", False, errorMessage="   ")
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")


class TestHandleUploadError(unittest.TestCase):
    """UT-3-03: handleUploadError(exception)"""

    def test_ut_3_03_001_invalid_file_format_exception(self):
        msg = handleUploadError(InvalidFileFormatException("test"))
        self.assertIn("Unsupported file format", msg)

    def test_ut_3_03_002_file_size_exceeded_exception(self):
        msg = handleUploadError(FileSizeExceededException("test"))
        self.assertIn("File size limit exceeded", msg)

    def test_ut_3_03_003_corrupted_file_exception(self):
        msg = handleUploadError(CorruptedFileException("test"))
        self.assertIn("corrupted or unreadable", msg)

    def test_ut_3_03_004_unknown_exception(self):
        msg = handleUploadError(Exception("random error"))
        self.assertIn("An unexpected error occurred", msg)

    def test_ut_3_03_005_storage_exception(self):
        msg = handleUploadError(StorageException("test"))
        self.assertIn("Could not store", msg)


class TestValidateCVFile(unittest.TestCase):
    """UT-3-04: validateCVFile(file)"""

    @classmethod
    def setUpClass(cls):
        cls.valid_pdf = make_valid_pdf()
        cls.big_pdf = make_large_pdf(MAX_CV_BYTES + 1)
        cls.exact_pdf = make_large_pdf(MAX_CV_BYTES)
        cls.corrupted_pdf = make_corrupted_pdf()

    def test_ut_3_04_001_valid_file_passes(self):
        file = MockFile(name="resume.pdf", data=self.valid_pdf, mime_type="application/pdf")
        try:
            validateCVFile(file)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_04_002_invalid_file_format_docx(self):
        file = MockFile(name="resume.docx", data=make_docx_data(), mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with self.assertRaises(InvalidFileFormatException):
            validateCVFile(file)

    def test_ut_3_04_003_format_mismatch_renamed_exe(self):
        file = MockFile(name="program.exe.pdf", data=make_exe_data(), mime_type="application/octet-stream")
        with self.assertRaises((InvalidFileFormatException, CorruptedFileException)) as ctx:
            validateCVFile(file)

    def test_ut_3_04_004_file_exceeds_size_limit(self):
        file = MockFile(name="resume.pdf", data=self.big_pdf, mime_type="application/pdf")
        with self.assertRaises(FileSizeExceededException):
            validateCVFile(file)

    def test_ut_3_04_005_boundary_exactly_20mb(self):
        file = MockFile(name="resume.pdf", data=self.exact_pdf, mime_type="application/pdf")
        try:
            validateCVFile(file)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_04_006_boundary_20mb_plus_1(self):
        file = MockFile(name="resume.pdf", data=self.big_pdf, mime_type="application/pdf")
        with self.assertRaises(FileSizeExceededException):
            validateCVFile(file)

    def test_ut_3_04_007_corrupted_file(self):
        file = MockFile(name="resume.pdf", data=self.corrupted_pdf, mime_type="application/pdf")
        with self.assertRaises(CorruptedFileException):
            validateCVFile(file)

    def test_ut_3_04_008_order_format_before_size(self):
        file = MockFile(name="resume.docx", data=make_large_pdf(MAX_CV_BYTES + 1), mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with self.assertRaises(InvalidFileFormatException):
            validateCVFile(file)

    def test_ut_3_04_009_order_size_before_integrity(self):
        big_corrupted = b"%PDF-" + b"X" * (MAX_CV_BYTES + 100)
        file = MockFile(name="resume.pdf", data=big_corrupted, mime_type="application/pdf")
        with self.assertRaises(FileSizeExceededException):
            validateCVFile(file)


class TestStoreCVFile(unittest.TestCase):
    """UT-3-05: storeCVFile(file, jobseekerId)"""

    @classmethod
    def setUpClass(cls):
        cls.valid_pdf = make_valid_pdf()

    def setUp(self):
        self.env = TestEnvironment()

    def tearDown(self):
        self.env.cleanup()

    def test_ut_3_05_001_successful_storage_and_db_record(self):
        file = MockFile(name="resume.pdf", data=self.valid_pdf, mime_type="application/pdf")
        record = storeCVFile(file, "job-001")
        self.assertIn("id", record)
        self.assertEqual(record["jobseekerId"], "job-001")
        self.assertEqual(record["original_filename"], "resume.pdf")
        self.assertIn("uploaded_at", record)

    def test_ut_3_05_002_storage_save_fails(self):
        file = MockFile(name="resume.pdf", data=self.valid_pdf, mime_type="application/pdf")
        with patch("builtins.open", side_effect=OSError("Disk full")):
            with self.assertRaises(StorageException):
                storeCVFile(file, "job-001")

    def test_ut_3_05_003_db_insert_fails(self):
        file = MockFile(name="resume.pdf", data=self.valid_pdf, mime_type="application/pdf")
        with patch("cv_upload._save_cvs", side_effect=OSError("DB error")):
            with self.assertRaises(StorageException):
                storeCVFile(file, "job-001")

    def test_ut_3_05_004_unique_ids_across_uploads(self):
        file1 = MockFile(name="cv1.pdf", data=self.valid_pdf, mime_type="application/pdf")
        file2 = MockFile(name="cv2.pdf", data=make_valid_pdf(), mime_type="application/pdf")
        r1 = storeCVFile(file1, "job-001")
        r2 = storeCVFile(file2, "job-001")
        self.assertNotEqual(r1["id"], r2["id"])

    def test_ut_3_05_005_timestamp_recorded(self):
        file = MockFile(name="resume.pdf", data=self.valid_pdf, mime_type="application/pdf")
        record = storeCVFile(file, "job-001")
        self.assertIn("uploaded_at", record)
        self.assertIsNotNone(record["uploaded_at"])

    def test_ut_3_05_006_same_user_multiple_uploads(self):
        file1 = MockFile(name="cv1.pdf", data=self.valid_pdf, mime_type="application/pdf")
        file2 = MockFile(name="cv2.pdf", data=make_valid_pdf(), mime_type="application/pdf")
        r1 = storeCVFile(file1, "job-001")
        r2 = storeCVFile(file2, "job-001")
        self.assertNotEqual(r1["id"], r2["id"])
        self.assertEqual(r1["jobseekerId"], "job-001")
        self.assertEqual(r2["jobseekerId"], "job-001")


class TestExtractTextFromCV(unittest.TestCase):
    """UT-3-06: extractTextFromCV(cvFileId)"""

    def setUp(self):
        self.env = TestEnvironment()

    def tearDown(self):
        self.env.cleanup()

    def test_ut_3_06_001_successful_text_extraction(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk("John Doe Python Java SQL")
        text = extractTextFromCV(file_id)
        self.assertIsNotNone(text)
        self.assertIn("John", text)

    def test_ut_3_06_002_file_not_in_storage(self):
        with self.assertRaises(ExtractionPreparationException):
            extractTextFromCV("nonexistent-id")

    def test_ut_3_06_003_no_extractable_text(self):
        file_id, record = self.env.ensure_text_pdf_on_disk("")
        with self.assertRaises(ExtractionPreparationException):
            extractTextFromCV(file_id)

    def test_ut_3_06_004_exceeds_50000_characters(self):
        long_text = "A" * 60000
        file_id, _ = self.env.ensure_text_pdf_on_disk(long_text)
        text = extractTextFromCV(file_id)
        self.assertLessEqual(len(text), 50000)

    def test_ut_3_06_005_boundary_exactly_50000(self):
        text_50k = "A" * 50000
        file_id, _ = self.env.ensure_text_pdf_on_disk(text_50k)
        text = extractTextFromCV(file_id)
        self.assertLessEqual(len(text), 50000)
        self.assertTrue(len(text) == 50000 or len(text) > 0)

    def test_ut_3_06_006_boundary_50001(self):
        text_50k1 = "A" * 50001
        file_id, _ = self.env.ensure_text_pdf_on_disk(text_50k1)
        text = extractTextFromCV(file_id)
        self.assertLessEqual(len(text), 50000)

    def test_ut_3_06_007_malformed_cv_file_id(self):
        with self.assertRaises(ExtractionPreparationException):
            extractTextFromCV("")
        with self.assertRaises(ExtractionPreparationException):
            extractTextFromCV(None)


class TestValidateExtractionResult(unittest.TestCase):
    """UT-3-08: validateExtractionResult(result)"""

    def test_ut_3_08_001_all_categories_populated(self):
        result = AIExtractionResult(
            skills=[{"skillName": "Python"}],
            education=[{"institution": "MIT"}],
            workExperience=[{"company": "Google"}],
        )
        try:
            validateExtractionResult(result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_08_002_only_skills_populated(self):
        result = AIExtractionResult(skills=[{"skillName": "Python"}], education=[], workExperience=[])
        try:
            validateExtractionResult(result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_08_003_only_education_populated(self):
        result = AIExtractionResult(skills=[], education=[{"institution": "MIT"}], workExperience=[])
        try:
            validateExtractionResult(result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_08_004_only_work_experience_populated(self):
        result = AIExtractionResult(skills=[], education=[], workExperience=[{"company": "Google"}])
        try:
            validateExtractionResult(result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_08_005_two_categories_one_empty(self):
        result = AIExtractionResult(
            skills=[{"skillName": "Python"}],
            education=[{"institution": "MIT"}],
            workExperience=[],
        )
        try:
            validateExtractionResult(result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_08_006_all_categories_empty_arrays(self):
        result = AIExtractionResult(skills=[], education=[], workExperience=[])
        with self.assertRaises(NoExtractionResultException):
            validateExtractionResult(result)

    def test_ut_3_08_007_all_categories_null(self):
        result = AIExtractionResult(skills=[], education=[], workExperience=[])
        result.skills = None
        result.education = None
        result.workExperience = None
        with self.assertRaises(NoExtractionResultException):
            validateExtractionResult(result)

    def test_ut_3_08_008_mixed_null_and_empty(self):
        result = AIExtractionResult(skills=[], education=[], workExperience=[])
        result.skills = None
        result.workExperience = None
        with self.assertRaises(NoExtractionResultException):
            validateExtractionResult(result)


class TestStoreExtractedCVInfo(unittest.TestCase):
    """UT-3-09: storeExtractedCVInfo(cvFileId, result)"""

    def setUp(self):
        self.env = TestEnvironment()

    def tearDown(self):
        self.env.cleanup()

    def test_ut_3_09_001_all_categories_stored(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(
            skills=[{"skillName": "Python"}],
            education=[{"institution": "MIT"}],
            workExperience=[{"company": "Google"}],
        )
        try:
            storeExtractedCVInfo(file_id, result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_09_002_only_skills_category(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(skills=[{"skillName": "Python"}], education=[], workExperience=[])
        try:
            storeExtractedCVInfo(file_id, result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_09_003_only_education_category(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(skills=[], education=[{"institution": "MIT"}], workExperience=[])
        try:
            storeExtractedCVInfo(file_id, result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_09_004_only_work_experience_category(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(skills=[], education=[], workExperience=[{"company": "Google"}])
        try:
            storeExtractedCVInfo(file_id, result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_09_005_multiple_entries_single_category(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(
            skills=[{"skillName": "Python"}, {"skillName": "Java"}, {"skillName": "SQL"}],
        )
        try:
            storeExtractedCVInfo(file_id, result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_09_006_transaction_rollback(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(
            skills=[{"skillName": "Python"}],
            education=[{"institution": "MIT"}],
            workExperience=[{"company": "Google"}],
        )
        with patch("cv_upload._save_cvs", side_effect=OSError("DB failed")):
            with self.assertRaises(DatabaseException):
                storeExtractedCVInfo(file_id, result)

    def test_ut_3_09_007_database_unavailable(self):
        with self.assertRaises(DatabaseException):
            storeExtractedCVInfo("nonexistent", AIExtractionResult(skills=[{"skillName": "Python"}]))

    def test_ut_3_09_008_all_categories_empty(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(skills=[], education=[], workExperience=[])
        try:
            storeExtractedCVInfo(file_id, result)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")


if __name__ == "__main__":
    unittest.main()
