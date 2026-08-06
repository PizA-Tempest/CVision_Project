"""Tests for SRS-046: Error messages when sensitive data cannot be protected or AI service is unavailable."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from embed import (
    handleProtectionError,
    AIServiceUnavailableException,
    MaskingException,
    SensitiveDataProtectionException,
    UnprotectedTransmissionException,
)


class TestSRS046_ProtectionErrorMessages(unittest.TestCase):
    """SRS-046: Display error messages when sensitive personal information cannot be protected."""

    def test_srs_046_001_masking_exception_message(self):
        msg = handleProtectionError(MaskingException("masking failed"))
        self.assertIn("masking failed", msg.lower())

    def test_srs_046_002_sensitive_data_protection_exception_message(self):
        msg = handleProtectionError(SensitiveDataProtectionException("protection failed"))
        self.assertIn("could not be completed securely", msg.lower())

    def test_srs_046_003_unprotected_transmission_exception_message(self):
        msg = handleProtectionError(UnprotectedTransmissionException("not masked"))
        self.assertIn("unprotected data", msg.lower())

    def test_srs_046_004_ai_service_unavailable_exception_message(self):
        msg = handleProtectionError(AIServiceUnavailableException("AI down"))
        self.assertIn("temporarily unavailable", msg.lower())

    def test_srs_046_005_unknown_exception_fallback_message(self):
        msg = handleProtectionError(Exception("random"))
        self.assertIn("unexpected error", msg.lower())

    def test_srs_046_006_none_exception_fallback(self):
        msg = handleProtectionError(None)
        self.assertIn("unexpected error", msg.lower())

    def test_srs_046_007_all_exception_types_return_string(self):
        exceptions = [
            MaskingException("e1"),
            SensitiveDataProtectionException("e2"),
            UnprotectedTransmissionException("e3"),
            AIServiceUnavailableException("e4"),
            Exception("e5"),
        ]
        for exc in exceptions:
            msg = handleProtectionError(exc)
            self.assertIsInstance(msg, str)
            self.assertTrue(len(msg) > 0)

    def test_srs_046_008_masking_exception_mentions_secure_processing(self):
        msg = handleProtectionError(MaskingException("test"))
        self.assertIn("could not be completed securely", msg.lower())

    def test_srs_046_009_unprotected_transmission_mentions_unprotected_data(self):
        msg = handleProtectionError(UnprotectedTransmissionException("test"))
        self.assertIn("unprotected data", msg.lower())

    def test_srs_046_010_ai_unavailable_tells_user_to_try_again(self):
        msg = handleProtectionError(AIServiceUnavailableException("test"))
        self.assertIn("try again", msg.lower())

    def test_srs_046_011_message_is_user_facing_not_technical(self):
        exceptions = [
            (MaskingException("traceback error"), "masking failed"),
            (SensitiveDataProtectionException("internal error"), "could not be completed securely"),
            (UnprotectedTransmissionException("assertion error"), "unprotected data"),
            (AIServiceUnavailableException("timeout"), "temporarily unavailable"),
        ]
        for exc, keyword in exceptions:
            msg = handleProtectionError(exc)
            self.assertIn(keyword, msg.lower())
            self.assertNotIn("traceback", msg.lower())
            self.assertNotIn("internal error", msg.lower())


if __name__ == "__main__":
    unittest.main()