from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from cv_upload import (
    CVUploadException,
    DatabaseException,
    AIExtractionResult,
    _load_cvs,
    _save_cvs,
)

load_dotenv()


class CVDataCorruptedException(CVUploadException):
    pass


class AIServiceUnavailableException(CVUploadException):
    pass


class CVAnalysisException(CVUploadException):
    pass


@dataclass
class CVAnalysisResult:
    overallScore: float = 0.0
    completenessScore: float = 0.0
    relevanceScore: float = 0.0
    clarityScore: float = 0.0
    suggestions: list[str] = field(default_factory=list)
    analyzedAt: str = ""


def _build_analysis_prompt(
    cv_data: AIExtractionResult,
    raw_text: str,
    available_categories: list[str],
) -> str:
    skills_str = json.dumps(cv_data.skills, ensure_ascii=False, indent=2)
    edu_str = json.dumps(cv_data.education, ensure_ascii=False, indent=2)
    exp_str = json.dumps(cv_data.workExperience, ensure_ascii=False, indent=2)

    return f"""
You are a CV quality analyst. Evaluate this CV and return ONLY valid JSON — no explanation, no markdown.

Available categories for evaluation: {json.dumps(available_categories)}

If a category is not in the available_categories list, assign it a score of 0.0 and mention it as missing in suggestions.

Return this exact schema:
{{
  "completeness_score": <float 0.000-1.000>,
  "relevance_score": <float 0.000-1.000>,
  "clarity_score": <float 0.000-1.000>,
  "overall_score": <float 0.000-1.000>,
  "suggestions": ["suggestion1", "suggestion2", ...]
}}

Scoring guidelines:
- completeness_score: Evaluate presence and depth of available sections. 1.0 = all sections complete and detailed.
- relevance_score: Evaluate alignment of skills and experience with current industry standards and market keywords. 1.0 = highly relevant.
- clarity_score: Evaluate readability, formatting consistency, action-verb usage, and descriptive quality of experience entries. 1.0 = excellent clarity.
- overall_score: Weighted combination with completeness=0.35, relevance=0.35, clarity=0.30.

Generate 2-4 actionable improvement suggestions for categories scoring below 0.700.

CV Data:
Skills: {skills_str}
Education: {edu_str}
Work Experience: {exp_str}

Raw CV Text (first 2000 chars):
{raw_text[:2000]}
"""


def retrieveCVForAnalysis(cvId: str) -> tuple[AIExtractionResult, str, list[str]]:
    records = _load_cvs()
    record = next((r for r in records if r["id"] == cvId), None)

    if not record:
        raise CVDataCorruptedException(f"CV record {cvId} not found")

    extracted = record.get("extracted_data")
    if not extracted:
        raise CVDataCorruptedException(f"No extracted data for CV {cvId}")

    skills = extracted.get("skills", [])
    education = extracted.get("education", [])
    work_experience = extracted.get("work_experience", [])

    cv_data = AIExtractionResult(
        skills=skills,
        education=education,
        workExperience=work_experience,
    )

    stored_path = record.get("stored_path", "")
    raw_text = ""
    if stored_path and os.path.exists(stored_path):
        try:
            from cv_upload import _extract_pdf_text
            with open(stored_path, "rb") as f:
                raw_text = _extract_pdf_text(f.read())
        except Exception:
            raw_text = ""

    available = []
    if skills:
        available.append("skills")
    if education:
        available.append("education")
    if work_experience:
        available.append("work_experience")

    if not available:
        raise CVDataCorruptedException("CV has no extractable categories for analysis")

    return cv_data, raw_text, available


def requestCVAnalysis(
    cvData: AIExtractionResult,
    rawText: str,
    availableCategories: list[str],
) -> CVAnalysisResult:
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        prompt = _build_analysis_prompt(cvData, rawText, availableCategories)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a strict JSON generator. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=1000,
        )

        content = response.choices[0].message.content or ""
        content = content.strip()
        content = re.sub(r"^```[a-zA-Z]*", "", content)
        content = re.sub(r"```$", "", content)
        content = content.strip()

        data = json.loads(content)

        scores = {}
        for key in ("completeness_score", "relevance_score", "clarity_score", "overall_score"):
            val = data.get(key, 0.0)
            if val is None:
                val = 0.0
            scores[key] = max(0.0, min(1.0, float(val)))

        suggestions = data.get("suggestions", [])
        if not isinstance(suggestions, list):
            suggestions = []

        return CVAnalysisResult(
            overallScore=scores["overall_score"],
            completenessScore=scores["completeness_score"],
            relevanceScore=scores["relevance_score"],
            clarityScore=scores["clarity_score"],
            suggestions=suggestions,
            analyzedAt=datetime.now(timezone.utc).isoformat(),
        )

    except CVAnalysisException:
        raise
    except Exception as e:
        raise AIServiceUnavailableException(f"AI Service unavailable: {str(e)}")


def calculateCompletenessScore(
    cvData: AIExtractionResult,
    availableCategories: list[str],
) -> float:
    score = 0.0
    weights = {"skills": 0.4, "education": 0.3, "work_experience": 0.3}
    total_weight = 0.0

    if "skills" in availableCategories:
        skills = cvData.skills or []
        if skills:
            depth = min(len(skills) / 10.0, 1.0)
            has_proficiency = sum(1 for s in skills if isinstance(s, dict) and s.get("proficiency_level"))
            depth = max(depth, has_proficiency / max(len(skills), 1))
            score += weights["skills"] * depth
        total_weight += weights["skills"]

    if "education" in availableCategories:
        edu = cvData.education or []
        if edu:
            depth = min(len(edu) / 3.0, 1.0)
            has_dates = sum(1 for e in edu if e.get("start_year") or e.get("end_year"))
            depth = max(depth, has_dates / max(len(edu), 1) * 0.5 + 0.5)
            score += weights["education"] * depth
        total_weight += weights["education"]

    if "work_experience" in availableCategories:
        exp = cvData.workExperience or []
        if exp:
            depth = min(len(exp) / 5.0, 1.0)
            has_dates = sum(1 for e in exp if e.get("start_date"))
            depth = max(depth, has_dates / max(len(exp), 1) * 0.5 + 0.5)
            score += weights["work_experience"] * depth
        total_weight += weights["work_experience"]

    if total_weight == 0.0:
        return 0.0

    normalized = score / total_weight
    return max(0.0, min(1.0, normalized))


_GENERIC_SKILLS = {
    "communication", "teamwork", "leadership", "hardworking", "motivated",
    "creative", "organized", "fast learner", "problem solving", "dedicated",
    "flexible", "reliable", "punctual", "detail oriented", "positive attitude",
}


def calculateRelevanceScore(
    cvData: AIExtractionResult,
    availableCategories: list[str],
) -> float:
    weights = {"skills": 0.6, "work_experience": 0.4}
    total_weight = 0.0
    score = 0.0

    if "skills" in availableCategories:
        skills = cvData.skills or []
        if skills:
            count_depth = min(len(skills) / 10.0, 1.0)
            specific = sum(
                1 for s in skills
                if (s.get("skill_name") if isinstance(s, dict) else s)
                and str(s.get("skill_name") if isinstance(s, dict) else s).lower() not in _GENERIC_SKILLS
            )
            specific_depth = specific / max(len(skills), 1)
            proficiency = sum(
                1 for s in skills if isinstance(s, dict) and s.get("proficiency_level")
            )
            proficiency_depth = proficiency / max(len(skills), 1)
            score += weights["skills"] * max(count_depth, specific_depth, proficiency_depth)
        total_weight += weights["skills"]

    if "work_experience" in availableCategories:
        exp = cvData.workExperience or []
        if exp:
            count_depth = min(len(exp) / 5.0, 1.0)
            detailed = sum(
                1 for e in exp
                if isinstance(e, dict) and len(e.get("description", "")) > 50
            )
            detail_depth = detailed / max(len(exp), 1)
            score += weights["work_experience"] * max(count_depth, detail_depth)
        total_weight += weights["work_experience"]

    if total_weight == 0.0:
        return 0.0

    return max(0.0, min(1.0, score / total_weight))


def calculateClarityScore(
    rawText: str,
    workExperience: list[dict[str, Any]],
) -> float:
    score = 0.0

    total_sentences = len(re.findall(r"[.!?]+", rawText))
    total_words = len(rawText.split())
    if total_sentences > 0 and total_words > 0:
        avg_words_per_sentence = total_words / total_sentences
        if 10 <= avg_words_per_sentence <= 25:
            score += 0.3
        elif 5 <= avg_words_per_sentence <= 35:
            score += 0.15
    else:
        score += 0.1

    action_verbs = {
        "developed", "implemented", "managed", "created", "designed",
        "led", "achieved", "improved", "built", "delivered",
        "analyzed", "coordinated", "established", "generated", "optimized",
    }
    action_count = sum(1 for w in rawText.lower().split() if w.strip(".,!?;:") in action_verbs)
    if action_count >= 5:
        score += 0.3
    elif action_count >= 2:
        score += 0.2
    elif action_count >= 1:
        score += 0.1

    bullet_chars = ["•", "-", "*", "–"]
    bullet_count = sum(rawText.count(c) for c in bullet_chars)
    if bullet_count >= 5:
        score += 0.2
    elif bullet_count >= 2:
        score += 0.1

    has_numbers = bool(re.search(r"\d+", rawText))
    if has_numbers:
        score += 0.1

    if workExperience:
        exp_with_desc = sum(1 for e in workExperience if isinstance(e, dict) and len(e.get("description", "")) > 50)
        if exp_with_desc >= 2:
            score += 0.1

    return max(0.0, min(1.0, score))


def calculateOverallScore(
    completeness: float,
    relevance: float,
    clarity: float,
    availableCategories: list[str],
) -> float:
    weights = {"completeness": 0.35, "relevance": 0.35, "clarity": 0.30}
    total = 0.0
    weight_sum = 0.0

    if "skills" in availableCategories or "education" in availableCategories or "work_experience" in availableCategories:
        total += weights["completeness"] * completeness
        weight_sum += weights["completeness"]

    total += weights["relevance"] * relevance
    weight_sum += weights["relevance"]

    total += weights["clarity"] * clarity
    weight_sum += weights["clarity"]

    if weight_sum == 0.0:
        return 0.0

    return max(0.0, min(1.0, total / weight_sum))


def storeCVAnalysis(cvId: str, analysis: CVAnalysisResult) -> None:
    try:
        records = _load_cvs()
        record = next((r for r in records if r["id"] == cvId), None)

        if not record:
            raise DatabaseException(f"CV record {cvId} not found")

        record["analysis"] = {
            "overallScore": analysis.overallScore,
            "completenessScore": analysis.completenessScore,
            "relevanceScore": analysis.relevanceScore,
            "clarityScore": analysis.clarityScore,
            "suggestions": analysis.suggestions,
            "analyzedAt": analysis.analyzedAt,
        }

        _save_cvs(records)
    except DatabaseException:
        raise
    except Exception as e:
        raise DatabaseException(f"Failed to store CV analysis: {str(e)}")


def displayCVAnalysis(cvId: str) -> dict[str, Any] | None:
    records = _load_cvs()
    record = next((r for r in records if r["id"] == cvId), None)

    if not record:
        return None

    return record.get("analysis")


def handleAnalysisError(exception: Exception) -> str:
    error_messages = {
        "AIServiceUnavailableException": "The CV score could not be generated at this time",
        "CVDataCorruptedException": "Your CV data could not be read — please re-upload your CV",
        "CVAnalysisException": "An error occurred while calculating your CV score",
    }
    exception_type = type(exception).__name__
    return error_messages.get(exception_type, "An unexpected error occurred while analyzing your CV")


def analyzeCV(cvId: str) -> CVAnalysisResult:
    cv_data, raw_text, available = retrieveCVForAnalysis(cvId)

    try:
        result = requestCVAnalysis(cv_data, raw_text, available)
    except (AIServiceUnavailableException, CVAnalysisException):
        completeness = calculateCompletenessScore(cv_data, available)
        relevance = calculateRelevanceScore(cv_data, available)
        clarity = calculateClarityScore(raw_text, cv_data.workExperience)
        overall = calculateOverallScore(completeness, relevance, clarity, available)

        suggestions = []
        if "skills" in available and completeness < 0.7:
            suggestions.append("Add more skills to strengthen your CV completeness")
        if relevance < 0.7:
            suggestions.append("Add more specific, concrete skills and detail your experience to strengthen relevance")
        if clarity < 0.7:
            suggestions.append("Improve readability with bullet points and action verbs")

        result = CVAnalysisResult(
            overallScore=overall,
            completenessScore=completeness,
            relevanceScore=relevance,
            clarityScore=clarity,
            suggestions=suggestions,
            analyzedAt=datetime.now(timezone.utc).isoformat(),
        )

    storeCVAnalysis(cvId, result)
    return result
