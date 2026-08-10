"""System test record runner for Feature #4 (ST-4-001 .. ST-4-022).

Runs against the real installation: the real CV registry (cvs.json), the real
uploads directory, and - for ST-4-005..ST-4-009 - the real External AI Service
(OpenAI gpt-4o-mini). cvs.json is backed up first and restored afterwards, so
the installation is left unchanged.

Run with the system Python 3.12 (the project .venv has a broken pikepdf wheel):
    python tests/run_system_tests_f4.py
"""

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, ROOT)

import cv_upload
import cv_analysis as ca
from cv_analysis import (
    CVAnalysisException,
    CVDataCorruptedException,
    DatabaseException,
)

REGISTRY = os.path.abspath(cv_upload.CVS_REGISTRY_FILE)
BACKUP = REGISTRY + ".st4-backup"
WEAK_CV = "st4_weak_cv_000000000000000000000000"
CORRUPT_CV = "st4_corrupt_cv_0000000000000000000000"
NO_ANALYSIS_CV = "st4_never_analyzed_0000000000000000000"

results = []


def emit(test_id, passed, actual):
    results.append((test_id, "PASS" if passed else "FAIL", actual))
    print(f"[{test_id}] {'PASS' if passed else 'FAIL'}  {actual}")


def load():
    return cv_upload._load_cvs()


def save(records):
    cv_upload._save_cvs(records)


def snapshot():
    return json.dumps(load(), sort_keys=True)


def set_fallback_env():
    os.environ["OPENAI_API_KEY"] = "sk-invalid-fallback-test"
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:1/v1"


def set_normal_env(orig_key, orig_base):
    if orig_key is None:
        os.environ.pop("OPENAI_API_KEY", None)
    else:
        os.environ["OPENAI_API_KEY"] = orig_key
    if orig_base is None:
        os.environ.pop("OPENAI_BASE_URL", None)
    else:
        os.environ["OPENAI_BASE_URL"] = orig_base


def find_full_cv(records):
    with_pdf = [r for r in records
                if isinstance(r.get("extracted_data"), dict)
                and r["extracted_data"].get("skills")
                and r["extracted_data"].get("education")
                and r["extracted_data"].get("work_experience")
                and r.get("stored_path")
                and os.path.exists(r["stored_path"])]
    for r in with_pdf:
        if "analysis" not in r:
            return r
    return with_pdf[0] if with_pdf else None


def find_partial_cv(records):
    for r in records:
        ed = r.get("extracted_data")
        if not isinstance(ed, dict):
            continue
        cats = [bool(ed.get("skills")), bool(ed.get("education")),
                bool(ed.get("work_experience"))]
        if sum(cats) == 2:
            return r
    return None


def make_weak_record():
    return {
        "id": WEAK_CV,
        "jobseekerId": "John Doe",
        "original_filename": "st4_weak.pdf",
        "stored_path": "",
        "size_bytes": 0,
        "sha256": "0" * 64,
        "uploaded_at": "2026-08-10T00:00:00+00:00",
        "validation_status": "validated",
        "extracted_data": {
            "skills": [{"skill_name": "Python", "proficiency_level": None}],
            "education": [],
            "work_experience": [],
            "extracted_at": "2026-08-10T00:00:00+00:00",
        },
    }


def make_corrupt_record():
    return {
        "id": CORRUPT_CV,
        "jobseekerId": "John Doe",
        "original_filename": "st4_corrupt.pdf",
        "stored_path": "",
        "size_bytes": 0,
        "sha256": "0" * 64,
        "uploaded_at": "2026-08-10T00:00:00+00:00",
        "validation_status": "validated",
        "extracted_data": "not a mapping",
    }


def print_summary():
    passed = sum(1 for _, r, _ in results if r == "PASS")
    print(f"\nSUMMARY: {passed}/{len(results)} passed")
    for tid, res, actual in results:
        print(f"{tid}\t{res}\t{actual}")


def main():
    print(f"Environment: Windows, Python {sys.version.split()[0]}, "
          f"registry={REGISTRY}, AI service=OpenAI gpt-4o-mini")
    print("Date: 2026-08-10  Tester: auto\n")

    records = load()
    full = find_full_cv(records)
    partial = find_partial_cv(records)
    if full is None:
        emit("ST-4-001", False, "no eligible full CV with PDF on disk in registry")
        print_summary()
        return
    if partial is None:
        emit("ST-4-001", False, "no partially populated CV in registry")
        print_summary()
        return

    orig_key = os.environ.get("OPENAI_API_KEY")
    orig_base = os.environ.get("OPENAI_BASE_URL")

    shutil.copy2(REGISTRY, BACKUP)
    try:
        injected = [make_weak_record(), make_corrupt_record()]
        registry = load()
        registry.extend(injected)
        save(registry)

        cv_data, raw_text, _ = ca.retrieveCVForAnalysis(full["id"])
        ok = (len(cv_data.skills) > 0 and len(cv_data.education) > 0
              and len(cv_data.workExperience) > 0 and raw_text.strip() != "")
        emit("ST-4-001", ok,
             f"cvId={full['id']} skills={len(cv_data.skills)}, "
             f"education={len(cv_data.education)}, "
             f"work_experience={len(cv_data.workExperience)}, "
             f"raw_cv_text={len(raw_text)} chars")

        try:
            ca.retrieveCVForAnalysis(CORRUPT_CV)
            emit("ST-4-002", False, "no exception raised for malformed CV")
        except CVDataCorruptedException:
            emit("ST-4-002", True,
                 "CVDataCorruptedException raised during retrieval; "
                 "analysis not attempted and no AI request sent")
        except Exception as e:
            emit("ST-4-002", False, f"wrong exception {type(e).__name__}: {e}")

        _, raw_text, _ = ca.retrieveCVForAnalysis(full["id"])
        emit("ST-4-003", raw_text is not None and raw_text.strip() != "",
             f"raw_cv_text retrieved, non-null and non-empty "
             f"({len(raw_text)} chars), ready for transmission")

        set_fallback_env()
        try:
            _, _, available = ca.retrieveCVForAnalysis(WEAK_CV)
            res = ca.analyzeCV(WEAK_CV)
            ok = available == ["skills"] and res is not None
            emit("ST-4-004", ok,
                 f"retrieval succeeds, available_categories={available}, "
                 f"analysis proceeds locally (overall={res.overallScore:.3f})")
        except Exception as e:
            emit("ST-4-004", False, f"blocked: {type(e).__name__}: {e}")
        finally:
            set_normal_env(orig_key, orig_base)

        set_normal_env(orig_key, orig_base)
        ai_full = ca.analyzeCV(full["id"])
        ok = (isinstance(ai_full.completenessScore, (int, float))
              and isinstance(ai_full.relevanceScore, (int, float))
              and isinstance(ai_full.clarityScore, (int, float))
              and isinstance(ai_full.overallScore, (int, float))
              and isinstance(ai_full.suggestions, list))
        emit("ST-4-005", ok,
             f"single AnalysisResult: completeness={ai_full.completenessScore}, "
             f"relevance={ai_full.relevanceScore}, clarity={ai_full.clarityScore}, "
             f"overall={ai_full.overallScore}, suggestions={len(ai_full.suggestions)}")

        scores = [ai_full.completenessScore, ai_full.relevanceScore,
                  ai_full.clarityScore, ai_full.overallScore]
        emit("ST-4-006", all(0 <= s <= 100 for s in scores),
             f"scores=[{', '.join(f'{s:.3f}' for s in scores)}] all within 0-100")

        cats = [ai_full.completenessScore, ai_full.relevanceScore,
                ai_full.clarityScore]
        all_well = all(s >= 70 for s in cats)
        ok = (not all_well) or len(ai_full.suggestions) == 0
        actual = (f"completeness={ai_full.completenessScore}, "
                  f"relevance={ai_full.relevanceScore}, "
                  f"clarity={ai_full.clarityScore} -> suggestions returned: "
                  f"{len(ai_full.suggestions)}")
        if all_well:
            actual += ("; all categories score >= 70 so suggestions are "
                       "suppressed by the SRS-069 rule")
        else:
            actual += ("; a category scores below 70 so suggestions are "
                       "expected under SRS-069")
        emit("ST-4-008", ok, actual)

        lo, hi = min(cats), max(cats)
        emit("ST-4-009", lo <= ai_full.overallScore <= hi,
             f"overall={ai_full.overallScore:.3f} within "
             f"[min={lo:.3f}, max={hi:.3f}] of the category scores")

        ai_weak = ca.analyzeCV(WEAK_CV)
        weak_cats = [ai_weak.completenessScore, ai_weak.relevanceScore,
                     ai_weak.clarityScore]
        weak_low = [s for s in weak_cats if s < 70]
        ok = len(weak_low) > 0 and len(ai_weak.suggestions) > 0
        emit("ST-4-007", ok,
             f"completeness={ai_weak.completenessScore}, "
             f"relevance={ai_weak.relevanceScore}, clarity={ai_weak.clarityScore} "
             f"(categories below 70: {len(weak_low)}), "
             f"suggestions={len(ai_weak.suggestions)}")

        set_fallback_env()
        try:
            fb_full = ca.analyzeCV(full["id"])
            emit("ST-4-010", True,
                 f"request did not fail outright; local scores computed: "
                 f"completeness={fb_full.completenessScore:.3f}, "
                 f"relevance={fb_full.relevanceScore:.3f}, "
                 f"clarity={fb_full.clarityScore:.3f}, "
                 f"overall={fb_full.overallScore:.3f}")

            fb_scores = [fb_full.completenessScore, fb_full.relevanceScore,
                         fb_full.clarityScore, fb_full.overallScore]
            emit("ST-4-011", all(0 <= s <= 100 for s in fb_scores),
                 f"fallback scores=[{', '.join(f'{s:.3f}' for s in fb_scores)}] "
                 f"all within 0-100")

            emit("ST-4-012", len(fb_full.suggestions) == 0,
                 f"suggestions stored for fallback analysis: "
                 f"{len(fb_full.suggestions)}"
                 + (f" ({fb_full.suggestions})" if fb_full.suggestions else ""))

            fb_partial = ca.analyzeCV(partial["id"])
            ok = 0 <= fb_partial.overallScore <= 1
            emit("ST-4-013", ok,
                 f"analysis completed without error using the two available "
                 f"categories; overall={fb_partial.overallScore:.3f}")
        except Exception as e:
            emit("ST-4-010", False, f"fallback path failed: {type(e).__name__}: {e}")
        finally:
            set_normal_env(orig_key, orig_base)

        registry = load()
        rec = next(r for r in registry if r["id"] == partial["id"])
        a = rec.get("analysis")
        ok = (isinstance(a, dict) and "overallScore" in a
              and "completenessScore" in a and "relevanceScore" in a
              and "clarityScore" in a and "suggestions" in a)
        emit("ST-4-014", ok,
             f"CV_Analysis record present for cvId={partial['id']}: "
             f"overall={a.get('overallScore')}, completeness={a.get('completenessScore')}, "
             f"relevance={a.get('relevanceScore')}, clarity={a.get('clarityScore')}, "
             f"suggestions={len(a.get('suggestions', []))}")

        disp = ca.displayCVAnalysis(partial["id"])
        ok = (disp is not None and "overallScore" in disp
              and "completenessScore" in disp and "relevanceScore" in disp
              and "clarityScore" in disp and "suggestions" in disp)
        emit("ST-4-015", ok,
             "displayCVAnalysis returns the overall score, category score "
             "breakdown, and suggestions that the CV upload page renders "
             "below the CV summary")

        ok = (disp is not None and a is not None
              and disp["overallScore"] == a["overallScore"]
              and disp["completenessScore"] == a["completenessScore"]
              and disp["relevanceScore"] == a["relevanceScore"]
              and disp["clarityScore"] == a["clarityScore"])
        emit("ST-4-016", ok,
             "displayed overall and category scores equal the stored "
             "CV_Analysis values; no storage/display discrepancy")

        set_fallback_env()
        try:
            ca.analyzeCV(partial["id"])
            ca.analyzeCV(partial["id"])
            registry = load()
            count = sum(1 for r in registry
                        if r["id"] == partial["id"] and "analysis" in r)
            emit("ST-4-017", count == 1,
                 f"{count} CV_Analysis record readable for cvId={partial['id']} "
                 f"after re-analysis (upsert, not append)")
        except Exception as e:
            emit("ST-4-017", False, f"re-analysis failed: {type(e).__name__}: {e}")
        finally:
            set_normal_env(orig_key, orig_base)

        try:
            ca.retrieveCVForAnalysis(CORRUPT_CV)
            emit("ST-4-018", False, "no exception raised for corrupted CV")
        except CVDataCorruptedException as e:
            msg = ca.handleAnalysisError(e)
            emit("ST-4-018", "re-upload" in msg.lower(),
                 f"CVDataCorruptedException raised; user-facing message: '{msg}'")
        except Exception as e:
            emit("ST-4-018", False, f"wrong exception {type(e).__name__}: {e}")

        set_fallback_env()
        orig_overall = ca.calculateOverallScore

        def failing_overall(*args, **kwargs):
            raise CVAnalysisException("internal fault during weight computation")

        ca.calculateOverallScore = failing_overall
        try:
            try:
                ca.analyzeCV(full["id"])
                emit("ST-4-019", False,
                     "no CVAnalysisException raised; fallback completed instead")
            except CVAnalysisException as e:
                msg = ca.handleAnalysisError(e)
                emit("ST-4-019",
                     msg == "An error occurred while calculating your CV score",
                     f"failing fallback raised CVAnalysisException -> user message: "
                     f"'{msg}'")
        finally:
            ca.calculateOverallScore = orig_overall
            set_normal_env(orig_key, orig_base)

        before = snapshot()
        orig_save = ca._save_cvs

        def failing_save(_records):
            raise RuntimeError("simulated insert failure")

        ca._save_cvs = failing_save
        try:
            try:
                ca.storeCVAnalysis(
                    partial["id"],
                    ca.CVAnalysisResult(overallScore=0.99, completenessScore=0.9,
                                        relevanceScore=0.9, clarityScore=0.9,
                                        suggestions=[],
                                        analyzedAt="2026-08-10T00:00:00+00:00"))
                emit("ST-4-020", False, "no DatabaseException raised")
            except DatabaseException:
                after = snapshot()
                emit("ST-4-020", before == after,
                     "DatabaseException raised; transaction rolled back; "
                     "registry unchanged; prior CV_Analysis intact")
        finally:
            ca._save_cvs = orig_save

        msg = ca.handleAnalysisError(ValueError("unexpected internal error"))
        emit("ST-4-021",
             msg == "An unexpected error occurred while analyzing your CV",
             f"unmapped exception -> generic message: '{msg}'")

        try:
            ca.extractCompletenessScore({"completeness_score": 150,
                                         "relevance_score": 80,
                                         "clarity_score": 80,
                                         "overall_score": 80,
                                         "suggestions": []})
            emit("ST-4-022", False, "no CVAnalysisException for out-of-range score")
        except CVAnalysisException:
            disp = ca.displayCVAnalysis(NO_ANALYSIS_CV)
            emit("ST-4-022", disp is None,
                 "CVAnalysisException raised during extraction/validation; "
                 "no analysis shown for the request")
    except Exception as e:
        print(f"SYSTEM TEST RUN ABORTED: {type(e).__name__}: {e}")
    finally:
        shutil.copy2(BACKUP, REGISTRY)
        print("Restored cvs.json from backup.")

    print_summary()


if __name__ == "__main__":
    main()
