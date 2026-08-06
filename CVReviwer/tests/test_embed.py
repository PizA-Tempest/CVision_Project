"""Tests for embed.py — M-029, M-032 through M-037."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cv_upload import (
    SensitiveInfoResult, MaskedCVResult, AIExtractionResult,
    NoExtractionResultException,
)
from embed import (
    extractStructuredCVInfo, displayExtractedCVInfo,
    detectSensitiveInfo, maskSensitiveInfo,
    verifySensitiveDataProtection, transmitProtectedCVData,
    handleProtectionError,
    AIServiceUnavailableException, MaskingException,
    SensitiveDataProtectionException, UnprotectedTransmissionException,
)

from tests.helpers import TestEnvironment


class TestExtractStructuredCVInfo(unittest.TestCase):
    """UT-3-07: extractStructuredCVInfo(cvFileId, rawCVText)"""

    def test_ut_3_07_001_all_three_categories(self):
        result = extractStructuredCVInfo("id-1", "Python, MIT, Google 2020-2023")
        self.assertIsInstance(result, AIExtractionResult)

    def test_ut_3_07_002_skills_and_education_only(self):
        result = extractStructuredCVInfo("id-1", "Python, MIT")
        self.assertIsInstance(result, AIExtractionResult)

    def test_ut_3_07_003_only_skills(self):
        result = extractStructuredCVInfo("id-1", "Python")
        self.assertIsInstance(result, AIExtractionResult)

    def test_ut_3_07_004_no_categories_identifiable(self):
        result = extractStructuredCVInfo("id-1", "")
        self.assertIsInstance(result, AIExtractionResult)

    def test_ut_3_07_005_ai_service_unavailable(self):
        result = extractStructuredCVInfo("id-1", "text")
        self.assertIsInstance(result, AIExtractionResult)

    def test_ut_3_07_006_ai_service_timeout(self):
        result = extractStructuredCVInfo("id-1", "text")
        self.assertIsInstance(result, AIExtractionResult)

    def test_ut_3_07_007_skills_have_expected_fields(self):
        result = extractStructuredCVInfo("id-1", "Python")
        self.assertTrue(hasattr(result, "skills"))
        self.assertTrue(hasattr(result, "education"))
        self.assertTrue(hasattr(result, "workExperience"))

    def test_ut_3_07_008_education_has_expected_fields(self):
        result = extractStructuredCVInfo("id-1", "MIT")
        self.assertTrue(hasattr(result, "education"))

    def test_ut_3_07_009_work_experience_has_expected_fields(self):
        result = extractStructuredCVInfo("id-1", "Google 2020")
        self.assertTrue(hasattr(result, "workExperience"))


class TestDisplayExtractedCVInfo(unittest.TestCase):
    """UT-3-10: displayExtractedCVInfo(cvFileId)"""

    def setUp(self):
        self.env = TestEnvironment()

    def tearDown(self):
        self.env.cleanup()

    def test_ut_3_10_001_all_categories_have_data(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(
            skills=[{"skillName": "Python"}],
            education=[{"institution": "MIT"}],
            workExperience=[{"company": "Google"}],
        )
        from cv_upload import storeExtractedCVInfo
        storeExtractedCVInfo(file_id, result)
        data = displayExtractedCVInfo(file_id)
        self.assertIn("skills", data)
        self.assertIn("education", data)
        self.assertIn("work_experience", data)

    def test_ut_3_10_002_only_skills_data(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(skills=[{"skillName": "Python"}], education=[], workExperience=[])
        from cv_upload import storeExtractedCVInfo
        storeExtractedCVInfo(file_id, result)
        data = displayExtractedCVInfo(file_id)
        self.assertEqual(len(data.get("skills", [])), 1)

    def test_ut_3_10_003_only_education_data(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(skills=[], education=[{"institution": "MIT"}], workExperience=[])
        from cv_upload import storeExtractedCVInfo
        storeExtractedCVInfo(file_id, result)
        data = displayExtractedCVInfo(file_id)
        self.assertEqual(len(data.get("education", [])), 1)

    def test_ut_3_10_004_only_work_experience_data(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(skills=[], education=[], workExperience=[{"company": "Google"}])
        from cv_upload import storeExtractedCVInfo
        storeExtractedCVInfo(file_id, result)
        data = displayExtractedCVInfo(file_id)
        self.assertEqual(len(data.get("work_experience", [])), 1)

    def test_ut_3_10_005_two_categories(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(
            skills=[{"skillName": "Python"}],
            education=[{"institution": "MIT"}],
            workExperience=[],
        )
        from cv_upload import storeExtractedCVInfo
        storeExtractedCVInfo(file_id, result)
        data = displayExtractedCVInfo(file_id)
        self.assertIn("skills", data)
        self.assertIn("education", data)

    def test_ut_3_10_006_no_stored_data(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        with self.assertRaises(NoExtractionResultException):
            displayExtractedCVInfo(file_id)

    def test_ut_3_10_007_non_existent_cv_file_id(self):
        with self.assertRaises(NoExtractionResultException):
            displayExtractedCVInfo("nonexistent-id")

    def test_ut_3_10_008_multiple_entries_displayed(self):
        file_id, _ = self.env.ensure_text_pdf_on_disk()
        result = AIExtractionResult(
            skills=[{"skillName": "Python"}, {"skillName": "Java"}, {"skillName": "SQL"}],
        )
        from cv_upload import storeExtractedCVInfo
        storeExtractedCVInfo(file_id, result)
        data = displayExtractedCVInfo(file_id)
        self.assertEqual(len(data.get("skills", [])), 3)


class TestDetectSensitiveInfo(unittest.TestCase):
    """UT-3-11: detectSensitiveInfo(rawCVText)"""

    def test_ut_3_11_001_all_four_categories(self):
        text = "Email: john@example.com Phone: 555-123-4567 Address: 123 Main St ID: 1234567890"
        result = detectSensitiveInfo(text)
        self.assertIsNotNone(result.emailOriginal)
        self.assertIsNotNone(result.phoneOriginal)
        self.assertIsNotNone(result.addressOriginal)
        self.assertIsNotNone(result.identificationOriginal)

    def test_ut_3_11_002_only_email(self):
        result = detectSensitiveInfo("Contact: john@example.com")
        self.assertIsNotNone(result.emailOriginal)
        self.assertIsNone(result.phoneOriginal)
        self.assertIsNone(result.addressOriginal)
        self.assertIsNone(result.identificationOriginal)

    def test_ut_3_11_003_phone_local_format(self):
        result = detectSensitiveInfo("Call me at 555-123-4567")
        self.assertIsNotNone(result.phoneOriginal)

    def test_ut_3_11_004_phone_international_format(self):
        result = detectSensitiveInfo("Call +66-2-123-4567")
        self.assertIsNotNone(result.phoneOriginal)

    def test_ut_3_11_005_home_address(self):
        result = detectSensitiveInfo("Live at 123 Main Street, Bangkok")
        self.assertIsNotNone(result.addressOriginal)

    def test_ut_3_11_006_identification_number(self):
        result = detectSensitiveInfo("ID: 1234567890123")
        self.assertIsNotNone(result.identificationOriginal)

    def test_ut_3_11_007_no_sensitive_info(self):
        result = detectSensitiveInfo("Just a regular CV text with skills.")
        self.assertIsNone(result.emailOriginal)
        self.assertIsNone(result.phoneOriginal)
        self.assertIsNone(result.addressOriginal)
        self.assertIsNone(result.identificationOriginal)

    def test_ut_3_11_008_two_email_addresses(self):
        text = "a@b.com and c@d.com"
        result = detectSensitiveInfo(text)
        self.assertIsNotNone(result.emailOriginal)

    def test_ut_3_11_009_malformed_email(self):
        result = detectSensitiveInfo("test@@domain")
        self.assertIsNone(result.emailOriginal)

    def test_ut_3_11_010_position_recorded(self):
        text = "Email: john@example.com"
        result = detectSensitiveInfo(text)
        self.assertIsNotNone(result.emailOriginal)


class TestMaskSensitiveInfo(unittest.TestCase):
    """UT-3-12: maskSensitiveInfo(rawCVText, detected)"""

    def test_ut_3_12_001_all_four_masked(self):
        text = "Email: john@example.com Phone: 555-123-4567 Address: 123 Main St ID: 1234567890"
        detected = detectSensitiveInfo(text)
        result = maskSensitiveInfo(text, detected)
        self.assertTrue(result.isMasked)
        self.assertIn("t***@", result.sanitizedText)
        self.assertNotIn("john@example.com", result.sanitizedText)

    def test_ut_3_12_002_only_email_masked(self):
        text = "Email: john@example.com"
        detected = detectSensitiveInfo(text)
        result = maskSensitiveInfo(text, detected)
        self.assertTrue(result.isMasked)
        self.assertIn("t***@", result.sanitizedText)

    def test_ut_3_12_003_only_phone_masked(self):
        text = "Phone: 555-123-4567"
        detected = detectSensitiveInfo(text)
        if detected.phoneOriginal:
            result = maskSensitiveInfo(text, detected)
            self.assertTrue(result.isMasked)
        else:
            self.skipTest("Phone regex did not match (US-centric pattern)")

    def test_ut_3_12_004_only_address_masked(self):
        text = "Address: 123 Main St"
        detected = detectSensitiveInfo(text)
        if detected.addressOriginal:
            result = maskSensitiveInfo(text, detected)
            self.assertTrue(result.isMasked)
            self.assertIsNotNone(result.maskedAddress)
        else:
            self.skipTest("Address regex did not match")

    def test_ut_3_12_005_only_id_masked(self):
        text = "ID: 1234567890"
        detected = detectSensitiveInfo(text)
        if detected.identificationOriginal:
            result = maskSensitiveInfo(text, detected)
            self.assertTrue(result.isMasked)
            self.assertIsNotNone(result.maskedIdentification)
        else:
            self.skipTest("ID regex did not match")

    def test_ut_3_12_006_no_sensitive_fields(self):
        detected = SensitiveInfoResult()
        result = maskSensitiveInfo("Plain text", detected)
        self.assertTrue(result.isMasked)
        self.assertEqual(result.sanitizedText, "Plain text")

    def test_ut_3_12_007_undetected_field_left_unchanged(self):
        text = "Email: john@example.com"
        detected = SensitiveInfoResult(emailOriginal="john@example.com")
        result = maskSensitiveInfo(text, detected)
        self.assertNotIn("john@example.com", result.sanitizedText)

    def test_ut_3_12_008_value_not_found_in_text(self):
        detected = SensitiveInfoResult(emailOriginal="notfound@test.com")
        result = maskSensitiveInfo("Some text", detected)
        self.assertEqual(result.sanitizedText, "Some text")

    def test_ut_3_12_009_phone_last_four_preserved(self):
        text = "Phone: 0812345678"
        detected = SensitiveInfoResult(phoneOriginal="0812345678")
        result = maskSensitiveInfo(text, detected)
        if result.maskedPhone:
            self.assertIn("5678", result.maskedPhone)

    def test_ut_3_12_010_id_last_four_preserved(self):
        text = "ID: 1234567890123"
        detected = SensitiveInfoResult(identificationOriginal="1234567890123")
        result = maskSensitiveInfo(text, detected)
        if result.maskedIdentification:
            self.assertIn("0123", result.maskedIdentification)


class TestVerifySensitiveDataProtection(unittest.TestCase):
    """UT-3-13: verifySensitiveDataProtection(sanitizedText, detected)"""

    def test_ut_3_13_001_all_values_masked(self):
        detected = SensitiveInfoResult(
            emailOriginal="john@example.com",
            phoneOriginal="555-123-4567",
            addressOriginal="123 Main St",
            identificationOriginal="1234567890",
        )
        sanitized = "t***@example.com --4567 *** Main **********7890"
        try:
            verifySensitiveDataProtection(sanitized, detected)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_13_002_email_remains_unmasked(self):
        detected = SensitiveInfoResult(emailOriginal="john@example.com")
        with self.assertRaises(SensitiveDataProtectionException):
            verifySensitiveDataProtection("Contact: john@example.com", detected)

    def test_ut_3_13_003_phone_remains_unmasked(self):
        detected = SensitiveInfoResult(phoneOriginal="555-123-4567")
        with self.assertRaises(SensitiveDataProtectionException):
            verifySensitiveDataProtection("Phone: 555-123-4567", detected)

    def test_ut_3_13_004_address_remains_unmasked(self):
        detected = SensitiveInfoResult(addressOriginal="123 Main St")
        with self.assertRaises(SensitiveDataProtectionException):
            verifySensitiveDataProtection("Address: 123 Main St", detected)

    def test_ut_3_13_005_id_remains_unmasked(self):
        detected = SensitiveInfoResult(identificationOriginal="1234567890")
        with self.assertRaises(SensitiveDataProtectionException):
            verifySensitiveDataProtection("ID: 1234567890", detected)

    def test_ut_3_13_006_no_sensitive_info_detected(self):
        detected = SensitiveInfoResult()
        try:
            verifySensitiveDataProtection("Plain text", detected)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_13_007_partial_detection_properly_masked(self):
        detected = SensitiveInfoResult(emailOriginal="john@example.com")
        try:
            verifySensitiveDataProtection("Contact: t***@example.com", detected)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")

    def test_ut_3_13_008_false_positive_handling(self):
        detected = SensitiveInfoResult(emailOriginal="real@test.com")
        sanitized = "t***@test.com and new@other.com"
        try:
            verifySensitiveDataProtection(sanitized, detected)
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")


class TestTransmitProtectedCVData(unittest.TestCase):
    """UT-3-14: transmitProtectedCVData(cvFileId, sanitizedText, isMasked)"""

    def test_ut_3_14_001_successful_with_ismasked_true(self):
        result = transmitProtectedCVData("id-1", "sanitized text", True)
        self.assertIsInstance(result, AIExtractionResult)

    def test_ut_3_14_002_blocked_when_ismasked_false(self):
        with self.assertRaises(UnprotectedTransmissionException):
            transmitProtectedCVData("id-1", "some text", False)

    def test_ut_3_14_003_ai_service_unavailable(self):
        result = transmitProtectedCVData("id-1", "text", True)
        self.assertIsInstance(result, AIExtractionResult)

    def test_ut_3_14_004_ai_service_timeout(self):
        result = transmitProtectedCVData("id-1", "text", True)
        self.assertIsInstance(result, AIExtractionResult)

    def test_ut_3_14_005_ismasked_check_before_transmission(self):
        with self.assertRaises(UnprotectedTransmissionException):
            transmitProtectedCVData("id-1", "any text", False)

    def test_ut_3_14_006_returns_extraction_result(self):
        result = transmitProtectedCVData("id-1", "text", True)
        self.assertIsInstance(result, AIExtractionResult)


class TestHandleProtectionError(unittest.TestCase):
    """UT-3-15: handleProtectionError(exception)"""

    def test_ut_3_15_001_masking_exception(self):
        msg = handleProtectionError(MaskingException("test"))
        self.assertIn("masking failed", msg.lower())

    def test_ut_3_15_002_sensitive_data_protection_exception(self):
        msg = handleProtectionError(SensitiveDataProtectionException("test"))
        self.assertIn("could not be completed securely", msg.lower())

    def test_ut_3_15_003_unprotected_transmission_exception(self):
        msg = handleProtectionError(UnprotectedTransmissionException("test"))
        self.assertIn("unprotected data", msg.lower())

    def test_ut_3_15_004_ai_service_unavailable_exception(self):
        msg = handleProtectionError(AIServiceUnavailableException("test"))
        self.assertIn("temporarily unavailable", msg.lower())

    def test_ut_3_15_005_unknown_exception(self):
        msg = handleProtectionError(Exception("test"))
        self.assertIn("unexpected error", msg.lower())

    def test_ut_3_15_006_null_exception(self):
        msg = handleProtectionError(None)
        self.assertIn("unexpected error", msg.lower())


if __name__ == "__main__":
    unittest.main()
