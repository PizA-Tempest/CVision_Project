"""Run all CVReviwer tests and generate results table."""

import os
import sys
import json
import unittest
import importlib
import re
from datetime import date
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


TEST_ID_MAP = {
    "test_ut_3_01_001_successful_upload": "UT-3-01-001",
    "test_ut_3_01_002_invalid_file_format": "UT-3-01-002",
    "test_ut_3_01_003_file_size_exceeded": "UT-3-01-003",
    "test_ut_3_01_004_corrupted_file": "UT-3-01-004",
    "test_ut_3_01_005_storage_failure": "UT-3-01-005",
    "test_ut_3_01_006_boundary_exactly_20mb": "UT-3-01-006",
    "test_ut_3_01_007_boundary_20mb_plus_1": "UT-3-01-007",
    "test_ut_3_01_008_invalid_jobseeker_id": "UT-3-01-008",
    "test_ut_3_02_001_success_no_error_message": "UT-3-02-001",
    "test_ut_3_02_002_success_error_message_ignored": "UT-3-02-002",
    "test_ut_3_02_003_failure_with_valid_error_message": "UT-3-02-003",
    "test_ut_3_02_004_failure_missing_error_message": "UT-3-02-004",
    "test_ut_3_02_005_failure_empty_string_error_message": "UT-3-02-005",
    "test_ut_3_02_006_failure_whitespace_error_message": "UT-3-02-006",
    "test_ut_3_03_001_invalid_file_format_exception": "UT-3-03-001",
    "test_ut_3_03_002_file_size_exceeded_exception": "UT-3-03-002",
    "test_ut_3_03_003_corrupted_file_exception": "UT-3-03-003",
    "test_ut_3_03_004_unknown_exception": "UT-3-03-004",
    "test_ut_3_03_005_storage_exception": "UT-3-03-005",
    "test_ut_3_04_001_valid_file_passes": "UT-3-04-001",
    "test_ut_3_04_002_invalid_file_format_docx": "UT-3-04-002",
    "test_ut_3_04_003_format_mismatch_renamed_exe": "UT-3-04-003",
    "test_ut_3_04_004_file_exceeds_size_limit": "UT-3-04-004",
    "test_ut_3_04_005_boundary_exactly_20mb": "UT-3-04-005",
    "test_ut_3_04_006_boundary_20mb_plus_1": "UT-3-04-006",
    "test_ut_3_04_007_corrupted_file": "UT-3-04-007",
    "test_ut_3_04_008_order_format_before_size": "UT-3-04-008",
    "test_ut_3_04_009_order_size_before_integrity": "UT-3-04-009",
    "test_ut_3_05_001_successful_storage_and_db_record": "UT-3-05-001",
    "test_ut_3_05_002_storage_save_fails": "UT-3-05-002",
    "test_ut_3_05_003_db_insert_fails": "UT-3-05-003",
    "test_ut_3_05_004_unique_ids_across_uploads": "UT-3-05-004",
    "test_ut_3_05_005_timestamp_recorded": "UT-3-05-005",
    "test_ut_3_05_006_same_user_multiple_uploads": "UT-3-05-006",
    "test_ut_3_06_001_successful_text_extraction": "UT-3-06-001",
    "test_ut_3_06_002_file_not_in_storage": "UT-3-06-002",
    "test_ut_3_06_003_no_extractable_text": "UT-3-06-003",
    "test_ut_3_06_004_exceeds_50000_characters": "UT-3-06-004",
    "test_ut_3_06_005_boundary_exactly_50000": "UT-3-06-005",
    "test_ut_3_06_006_boundary_50001": "UT-3-06-006",
    "test_ut_3_06_007_malformed_cv_file_id": "UT-3-06-007",
    "test_ut_3_07_001_all_three_categories": "UT-3-07-001",
    "test_ut_3_07_002_skills_and_education_only": "UT-3-07-002",
    "test_ut_3_07_003_only_skills": "UT-3-07-003",
    "test_ut_3_07_004_no_categories_identifiable": "UT-3-07-004",
    "test_ut_3_07_005_ai_service_unavailable": "UT-3-07-005",
    "test_ut_3_07_006_ai_service_timeout": "UT-3-07-006",
    "test_ut_3_07_007_skills_have_expected_fields": "UT-3-07-007",
    "test_ut_3_07_008_education_has_expected_fields": "UT-3-07-008",
    "test_ut_3_07_009_work_experience_has_expected_fields": "UT-3-07-009",
    "test_ut_3_08_001_all_categories_populated": "UT-3-08-001",
    "test_ut_3_08_002_only_skills_populated": "UT-3-08-002",
    "test_ut_3_08_003_only_education_populated": "UT-3-08-003",
    "test_ut_3_08_004_only_work_experience_populated": "UT-3-08-004",
    "test_ut_3_08_005_two_categories_one_empty": "UT-3-08-005",
    "test_ut_3_08_006_all_categories_empty_arrays": "UT-3-08-006",
    "test_ut_3_08_007_all_categories_null": "UT-3-08-007",
    "test_ut_3_08_008_mixed_null_and_empty": "UT-3-08-008",
    "test_ut_3_09_001_all_categories_stored": "UT-3-09-001",
    "test_ut_3_09_002_only_skills_category": "UT-3-09-002",
    "test_ut_3_09_003_only_education_category": "UT-3-09-003",
    "test_ut_3_09_004_only_work_experience_category": "UT-3-09-004",
    "test_ut_3_09_005_multiple_entries_single_category": "UT-3-09-005",
    "test_ut_3_09_006_transaction_rollback": "UT-3-09-006",
    "test_ut_3_09_007_database_unavailable": "UT-3-09-007",
    "test_ut_3_09_008_all_categories_empty": "UT-3-09-008",
    "test_ut_3_10_001_all_categories_have_data": "UT-3-10-001",
    "test_ut_3_10_002_only_skills_data": "UT-3-10-002",
    "test_ut_3_10_003_only_education_data": "UT-3-10-003",
    "test_ut_3_10_004_only_work_experience_data": "UT-3-10-004",
    "test_ut_3_10_005_two_categories": "UT-3-10-005",
    "test_ut_3_10_006_no_stored_data": "UT-3-10-006",
    "test_ut_3_10_007_non_existent_cv_file_id": "UT-3-10-007",
    "test_ut_3_10_008_multiple_entries_displayed": "UT-3-10-008",
    "test_ut_3_11_001_all_four_categories": "UT-3-11-001",
    "test_ut_3_11_002_only_email": "UT-3-11-002",
    "test_ut_3_11_003_phone_local_format": "UT-3-11-003",
    "test_ut_3_11_004_phone_international_format": "UT-3-11-004",
    "test_ut_3_11_005_home_address": "UT-3-11-005",
    "test_ut_3_11_006_identification_number": "UT-3-11-006",
    "test_ut_3_11_007_no_sensitive_info": "UT-3-11-007",
    "test_ut_3_11_008_two_email_addresses": "UT-3-11-008",
    "test_ut_3_11_009_malformed_email": "UT-3-11-009",
    "test_ut_3_11_010_position_recorded": "UT-3-11-010",
    "test_ut_3_12_001_all_four_masked": "UT-3-12-001",
    "test_ut_3_12_002_only_email_masked": "UT-3-12-002",
    "test_ut_3_12_003_only_phone_masked": "UT-3-12-003",
    "test_ut_3_12_004_only_address_masked": "UT-3-12-004",
    "test_ut_3_12_005_only_id_masked": "UT-3-12-005",
    "test_ut_3_12_006_no_sensitive_fields": "UT-3-12-006",
    "test_ut_3_12_007_undetected_field_left_unchanged": "UT-3-12-007",
    "test_ut_3_12_008_value_not_found_in_text": "UT-3-12-008",
    "test_ut_3_12_009_phone_last_four_preserved": "UT-3-12-009",
    "test_ut_3_12_010_id_last_four_preserved": "UT-3-12-010",
    "test_ut_3_13_001_all_values_masked": "UT-3-13-001",
    "test_ut_3_13_002_email_remains_unmasked": "UT-3-13-002",
    "test_ut_3_13_003_phone_remains_unmasked": "UT-3-13-003",
    "test_ut_3_13_004_address_remains_unmasked": "UT-3-13-004",
    "test_ut_3_13_005_id_remains_unmasked": "UT-3-13-005",
    "test_ut_3_13_006_no_sensitive_info_detected": "UT-3-13-006",
    "test_ut_3_13_007_partial_detection_properly_masked": "UT-3-13-007",
    "test_ut_3_13_008_false_positive_handling": "UT-3-13-008",
    "test_ut_3_14_001_successful_with_ismasked_true": "UT-3-14-001",
    "test_ut_3_14_002_blocked_when_ismasked_false": "UT-3-14-002",
    "test_ut_3_14_003_ai_service_unavailable": "UT-3-14-003",
    "test_ut_3_14_004_ai_service_timeout": "UT-3-14-004",
    "test_ut_3_14_005_ismasked_check_before_transmission": "UT-3-14-005",
    "test_ut_3_14_006_returns_extraction_result": "UT-3-14-006",
    "test_ut_3_15_001_masking_exception": "UT-3-15-001",
    "test_ut_3_15_002_sensitive_data_protection_exception": "UT-3-15-002",
    "test_ut_3_15_003_unprotected_transmission_exception": "UT-3-15-003",
    "test_ut_3_15_004_ai_service_unavailable_exception": "UT-3-15-004",
    "test_ut_3_15_005_unknown_exception": "UT-3-15-005",
    "test_ut_3_15_006_null_exception": "UT-3-15-006",
}

EXPECTED_MAP_FILE = os.path.join(os.path.dirname(__file__), "expected.json")
expected_map: dict[str, str] = {}


def make_scenario_label(method_name: str) -> str:
    s = method_name.replace("test_ut_3_", "")
    s = s.replace("_", " ").strip()
    return s[0].upper() + s[1:] if s else method_name


class ResultCapture:
    def __init__(self):
        self.results: list[dict[str, Any]] = []

    def add(self, test_id: str, method_name: str, expected: str,
            actual: str, passed: bool, skipped: bool = False):
        self.results.append({
            "test_id": test_id,
            "method": method_name,
            "expected": expected,
            "actual": actual,
            "result": "SKIP" if skipped else ("PASS" if passed else "FAIL"),
        })

    def to_markdown(self) -> str:
        today = date.today().isoformat()
        lines = []
        lines.append(f"# CVReviwer Test Results — {today}")
        lines.append("")
        lines.append("| Test Record ID | Expected Output | Actual Output | Result | Tester | Date |")
        lines.append("|---|---|---|---|---|---|")
        for r in self.results:
            e = r["expected"] or "-"
            a = r["actual"] or "-"
            lines.append(
                f"| {r['test_id']} | {e} | {a} | "
                f"{r['result']} | auto | {today} |"
            )
        return "\n".join(lines)

    def to_json(self) -> list[dict]:
        today = date.today().isoformat()
        return [
            {
                "test_id": r["test_id"],
                "expected": r["expected"] or "-",
                "actual": r["actual"] or "-",
                "result": r["result"],
                "tester": "auto",
                "date": today,
            }
            for r in self.results
        ]


capture = ResultCapture()


class TestResultHandler(unittest.TestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "PASS", "As expected")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "FAIL", self._exc_to_str(err))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "FAIL", self._exc_to_str(err))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "SKIP", reason, skipped=True)

    def _exc_to_str(self, err):
        if err and len(err) > 1:
            return str(err[1])
        return str(err)

    def _record(self, test, status, msg, skipped=False):
        method_name = getattr(test, '_testMethodName', str(test))
        test_id = TEST_ID_MAP.get(method_name, method_name)
        expected = expected_map.get(test_id, "-")
        capture.add(test_id, method_name, expected, msg, status == "PASS", skipped)


def main():
    today = date.today().isoformat()
    out_md = os.path.join(os.path.dirname(__file__), f"test_results_{today}.md")
    out_json = os.path.join(os.path.dirname(__file__), f"test_results_{today}.json")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_cv_upload = importlib.import_module("tests.test_cv_upload")
    test_embed = importlib.import_module("tests.test_embed")

    for module in [test_cv_upload, test_embed]:
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and obj != unittest.TestCase:
                suite.addTests(loader.loadTestsFromTestCase(obj))

    runner = unittest.TextTestRunner(resultclass=TestResultHandler, verbosity=0)
    runner.run(suite)

    md = capture.to_markdown()
    js = capture.to_json()

    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(js, f, indent=2, ensure_ascii=False)

    print(f"\nResults written to:")
    print(f"  {out_md}")
    print(f"  {out_json}")

    total = len(capture.results)
    passed = sum(1 for r in capture.results if r["result"] == "PASS")
    failed = sum(1 for r in capture.results if r["result"] == "FAIL")
    skipped = sum(1 for r in capture.results if r["result"] == "SKIP")
    print(f"\nTotal: {total} | PASS: {passed} | FAIL: {failed} | SKIP: {skipped}")


if __name__ == "__main__":
    main()
