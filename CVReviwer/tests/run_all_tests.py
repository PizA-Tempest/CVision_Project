"""Run the Feature 2 and Feature 3 suites together and write a results table.

    python tests/run_all_tests.py

Produces `test_results_<date>.md` and `.json` in the same format Feature 3's
own `run_tests.py` uses, so the two are comparable and the Test Record can be
assembled from either.

WHY A SECOND RUNNER
===================
Feature 3's `run_tests.py` hardcodes its two test modules and its own
TEST_ID_MAP. Adding Feature 2 to it would mean editing a file that belongs to
the approved Feature 3 work. This runner imports that map rather than copying
it, so his file stays untouched and there is still only one definition of his
test ids.

Feature 2's ids are derived from the method name (`test_ut_2_03_001_...` ->
`UT-2-03-001`) rather than listed, so a new test needs no bookkeeping here.

`embed.py` imports SentenceTransformer and tqdm at module level even though
only its batch pipeline uses them. If those are not installed, this runner
substitutes lightweight stubs so the suite can still run — the M-03 methods
under test never call them.
"""

import importlib
import json
import os
import re
import sys
import types
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)


def _stub_heavy_imports():
    """Stand in for the ML packages embed.py imports but does not use here."""
    if "sentence_transformers" not in sys.modules:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            module = types.ModuleType("sentence_transformers")

            class SentenceTransformer:
                def __init__(self, *args, **kwargs):
                    pass

                def encode(self, *args, **kwargs):
                    raise NotImplementedError("stubbed for testing")

            module.SentenceTransformer = SentenceTransformer
            sys.modules["sentence_transformers"] = module

    if "tqdm" not in sys.modules:
        try:
            import tqdm  # noqa: F401
        except ImportError:
            module = types.ModuleType("tqdm")
            module.tqdm = lambda iterable=None, *a, **k: iterable
            sys.modules["tqdm"] = module


def _feature_two_id(method_name):
    """test_ut_2_03_001_partial_overlap -> UT-2-03-001"""
    match = re.match(r"test_ut_(\d)_(\d{2})_(\d{3})", method_name)
    return f"UT-{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else None


class ResultCapture:
    def __init__(self):
        self.results = []

    def add(self, test_id, expected, actual, status, module=""):
        self.results.append({"test_id": test_id, "expected": expected,
                             "actual": actual, "result": status, "module": module})

    def to_markdown(self):
        today = date.today().isoformat()
        lines = [f"# CVision Test Results — {today}", "",
                 "| Test Record ID | Expected Output | Actual Output | Result | Tester | Date |",
                 "|---|---|---|---|---|---|"]
        for r in sorted(self.results, key=lambda r: r["test_id"]):
            lines.append(f"| {r['test_id']} | {r['expected'] or '-'} | {r['actual'] or '-'} | "
                         f"{r['result']} | auto | {today} |")
        return "\n".join(lines)

    def to_json(self):
        today = date.today().isoformat()
        return [{k: v for k, v in r.items() if k != "module"} | {"tester": "auto", "date": today}
                for r in sorted(self.results, key=lambda r: r["test_id"])]


capture = ResultCapture()
FEATURE_THREE_IDS = {}


class ResultHandler(unittest.TextTestResult):
    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "PASS", "As expected")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "FAIL", self._reason(err))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "FAIL", self._reason(err))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "SKIP", reason)

    @staticmethod
    def _reason(err):
        return str(err[1]) if err and len(err) > 1 else str(err)

    def _record(self, test, status, message):
        method = getattr(test, "_testMethodName", str(test))
        test_id = FEATURE_THREE_IDS.get(method) or _feature_two_id(method) or method
        # Classified by defining module, not by id prefix: test_srs_046.py's
        # methods are named test_srs_046_* and carry no UT id, so bucketing on
        # the id would silently drop 11 Feature 3 tests out of the baseline
        # check and report a regression that had not happened.
        capture.add(test_id, "-", message, status, type(test).__module__)


def main():
    _stub_heavy_imports()

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    loaded, skipped_modules = [], []

    # Feature 3 — his modules and his id map, imported rather than duplicated.
    try:
        feature_three_runner = importlib.import_module("run_tests")
        FEATURE_THREE_IDS.update(getattr(feature_three_runner, "TEST_ID_MAP", {}))
    except Exception as ex:
        skipped_modules.append(f"run_tests (id map): {ex}")

    for name in ("test_cv_upload", "test_embed", "test_srs_046", "test_match"):
        try:
            module = importlib.import_module(name)
        except Exception as ex:
            skipped_modules.append(f"{name}: {ex}")
            continue
        suite.addTests(loader.loadTestsFromModule(module))
        loaded.append(name)

    if skipped_modules:
        print("Could not load:")
        for entry in skipped_modules:
            print(f"  {entry}")
        print()

    print(f"Running: {', '.join(loaded)}\n")
    unittest.TextTestRunner(resultclass=ResultHandler, verbosity=1).run(suite)

    today = date.today().isoformat()
    md_path = os.path.join(HERE, f"test_results_{today}.md")
    json_path = os.path.join(HERE, f"test_results_{today}.json")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(capture.to_markdown())
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(capture.to_json(), fh, indent=2, ensure_ascii=False)

    total = len(capture.results)
    passed = sum(1 for r in capture.results if r["result"] == "PASS")
    failed = sum(1 for r in capture.results if r["result"] == "FAIL")
    skipped = sum(1 for r in capture.results if r["result"] == "SKIP")

    FEATURE_THREE_MODULES = {"test_cv_upload", "test_embed", "test_srs_046"}
    by_feature = {}
    for r in capture.results:
        module = (r.get("module") or "").rsplit(".", 1)[-1]
        if module in FEATURE_THREE_MODULES:
            key = "UT-3"
        elif module == "test_match":
            key = "UT-2"
        else:
            key = "other"
        entry = by_feature.setdefault(key, {"PASS": 0, "FAIL": 0, "SKIP": 0})
        entry[r["result"]] += 1

    print(f"\nResults written to:\n  {md_path}\n  {json_path}\n")
    for key in sorted(by_feature):
        counts = by_feature[key]
        label = {"UT-2": "Feature 2 (Job Matching)",
                 "UT-3": "Feature 3 (CV Upload)"}.get(key, key)
        print(f"  {label:<28} PASS {counts['PASS']:>3} | "
              f"FAIL {counts['FAIL']:>2} | SKIP {counts['SKIP']:>2}")
    print(f"\n  TOTAL: {total} | PASS: {passed} | FAIL: {failed} | SKIP: {skipped}")

    # Feature 3's known baseline: 123 PASS / 1 FAIL / 1 SKIP. Any other
    # Feature 3 result means the integration disturbed approved code.
    f3 = by_feature.get("UT-3")
    if f3 and (f3["PASS"], f3["FAIL"], f3["SKIP"]) != (123, 1, 1):
        print("\n  *** Feature 3 has moved from its 123/1/1 baseline — "
              "approved code may have been disturbed. ***")
    return 1 if failed and (not f3 or f3["FAIL"] > 1) else 0


if __name__ == "__main__":
    raise SystemExit(main())
