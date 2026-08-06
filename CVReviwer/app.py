"""
app.py — CVision Jobseeker interface

Upload a CV, have it parsed, and see ranked job matches.

WHAT CHANGED IN PHASE 3
=======================
Previously this file did almost everything itself: it called one helper from
cv_upload.py (`validate_and_store_cv`, which is not one of the documented
methods), extracted CV information with its own inline OpenAI call, and ranked
jobs with its own cosine-similarity loop over a JSON file. Thirteen of Feature
3's fifteen approved methods were never reached, extracted CV data was never
persisted, and raw CV text — emails, phone numbers, addresses, ID numbers —
went straight to OpenAI unmasked.

It now runs the documented chain:

    M-03-01 uploadCVFile          validate + store
      M-03-04 validateCVFile
      M-03-05 storeCVFile
    M-03-02 displayUploadFeedback
    M-03-06 extractTextFromCV     read the stored PDF
    M-03-11 detectSensitiveInfo   find email / phone / address / ID
    M-03-12 maskSensitiveInfo     replace them
    M-03-13 verifySensitiveDataProtection
    [ AI extraction -- see below ]
    M-03-08 validateExtractionResult
    M-03-09 storeExtractedCVInfo  persist to cvs.json
    M-03-10 displayExtractedCVInfo

then Feature 2:

    M-02-01 retrieveCVData        (via match_controller)
    M-02-02 .. M-02-09            compare, score, rank, store
    M-02-10 displayJobMatchResults
    M-02-11 openJobPosting

THE TWO BYPASSED METHODS
========================
M-03-07 extractStructuredCVInfo and M-03-14 transmitProtectedCVData are
placeholders in the approved code — both return an empty AIExtractionResult
with a comment saying a real implementation would call the AI service. Routing
extraction through them would produce three empty categories, which M-03-08
would then correctly reject, and the app would stop working.

So the real OpenAI call stays here, in `_extract_structured_info` below, and
its result feeds M-03-08 and M-03-09 exactly as the chain expects. Everything
either side of the AI call runs for real. When those two methods are
implemented, this function is what they replace — nothing else changes. See
TBD_and_Conflicts.md Part 4.

Note the text handed to the AI is the **masked** text, so the masking chain is
not merely executed and discarded. One caveat carried over from Feature 3's
own test results: its phone regex is US-centric (UT-3-11-004 fails,
UT-3-12-003 is skipped), so Thai mobile numbers are not detected and therefore
not masked.
"""

import json
import os
import re

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

from admin import show_admin_page

# Feature 3 (approved — imported and called, never modified)
import cv_upload
import embed
from cv_upload import AIExtractionResult, CVUploadException

# Feature 2
import cv_data_adapter
import match_controller
from cv_analysis import CVAnalysisResult, analyzeCV, handleAnalysisError

st.set_page_config(page_title="CVision", page_icon="📄", layout="wide")

# Stand-in until Feature 5 (Authentication) supplies a real identity. Every
# upload is attributed to this id, and it is what the "My CVs" picker filters
# on — so today that picker shows every guest's uploads. Feature 5 replaces
# this with the signed-in Jobseeker.
JOBSEEKER_ID = "John Doe"

st.markdown("""
<style>
[data-testid="stSidebar"] { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

# Routing
if st.query_params.get("page") == "admin":
    show_admin_page()
    st.stop()

st.markdown("""
<style>
.main { background: linear-gradient(135deg, #eef2ff, #fef9ff); }
.title { font-size: 42px; font-weight: bold; color: #4f46e5; }
.subtitle { font-size: 18px; color: #6b7280; }
.card {
    background: white;
    padding: 20px;
    border-radius: 16px;
    box-shadow: 0px 4px 12px rgba(0,0,0,0.05);
    margin-bottom: 15px;
}
.score-high { color: #16a34a; font-weight: bold; }
.score-mid  { color: #eab308; font-weight: bold; }
.score-low  { color: #ef4444; font-weight: bold; }
.skill-tag {
    display: inline-block;
    background: #eef2ff;
    color: #4f46e5;
    border-radius: 999px;
    padding: 3px 12px;
    margin: 3px;
    font-size: 13px;
}
.masked-note {
    background: #eff6ff;
    border-left: 4px solid #3b82f6;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 13px;
    color: #1e40af;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# AI extraction — stands in for M-03-07 / M-03-14
# ---------------------------------------------------------------------

def _clean_json(content: str) -> str:
    content = (content or "").strip()
    content = re.sub(r"^```[a-zA-Z]*", "", content)
    content = re.sub(r"```$", "", content)
    return content.strip()


def _extract_structured_info(cv_file_id: str, sanitized_text: str) -> AIExtractionResult:
    """
    Sends the masked CV text to OpenAI and returns an AIExtractionResult.

    This is what M-03-14 transmitProtectedCVData and M-03-07
    extractStructuredCVInfo would do if they were implemented; the signature
    deliberately mirrors theirs so swapping this out later is a one-line
    change. It returns Feature 3's own AIExtractionResult type, so everything
    downstream (M-03-08, M-03-09) is unchanged.

    Skills are requested as objects rather than plain strings — the shape
    AIExtractionResult already declares (list[dict]) and the shape M-02-03
    expects (Skill.skill_name). The previous prompt returned bare strings,
    which matched neither. This touches no approved document: the schema here
    is what the approved dataclass and the Feature 2 method description
    already specify.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    prompt = f"""
Extract professional skills, education, and work experience from this CV/resume.

Return ONLY valid JSON — no explanation, no markdown — with this schema:
{{
  "skills": [
    {{"skill_name": "...", "proficiency_level": null}}
  ],
  "education": [
    {{"institution": "...", "degree": "...", "start_year": ..., "end_year": ...}}
  ],
  "work_experience": [
    {{"company": "...", "position": "...", "start_date": "...", "end_date": "..."}}
  ]
}}

Rules:
- Include hard skills: programming languages, frameworks, tools, platforms
- Include soft skills only if clearly stated
- skill_name must be the skill on its own, e.g. "Python", not "Python programming"
- proficiency_level: one of beginner, intermediate, advanced, expert — or null if not stated
- degree should include the field of study, e.g. "Bachelor of Science in Computer Science"
- Do NOT translate technical terms (Python, React, SQL, AWS, etc.)
- Translate non-English names to English
- Return empty lists if nothing found
- Use null for missing years/dates
- Some values may appear masked (t***@domain.com, --1234). Ignore them; they are
  redacted personal details, not content to extract.

CV text:
\"\"\"{sanitized_text[:3000]}\"\"\"
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a strict JSON generator. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=1000,
    )

    data = json.loads(_clean_json(response.choices[0].message.content or ""))
    return AIExtractionResult(
        skills=data.get("skills") or [],
        education=data.get("education") or [],
        workExperience=data.get("work_experience") or [],
    )


# ---------------------------------------------------------------------
# The Feature 3 chain
# ---------------------------------------------------------------------

def process_cv(uploaded_file):
    """
    Runs the documented CV chain and returns (cv_file_id, masked_summary).

    Raises whatever the approved methods raise; the caller maps it to a
    message with M-03-03 handleUploadError or M-03-15 handleProtectionError.
    """
    # M-03-01 -> M-03-04 validateCVFile, M-03-05 storeCVFile
    upload = cv_upload.uploadCVFile(uploaded_file, JOBSEEKER_ID)
    cv_file_id = upload["cvFileId"]

    # M-03-02 — prints to the console; the visible feedback is rendered by the
    # caller, since Streamlit does not surface stdout.
    cv_upload.displayUploadFeedback(upload["fileName"], True)

    # Feature 2/5 ownership index. Best-effort: never blocks the upload.
    cv_data_adapter.record_cv_ownership(
        JOBSEEKER_ID, cv_file_id, upload.get("fileName")
    )

    # M-03-06
    raw_text = cv_upload.extractTextFromCV(cv_file_id)

    # M-03-11 -> M-03-12 -> M-03-13
    detected = embed.detectSensitiveInfo(raw_text)
    masked = embed.maskSensitiveInfo(raw_text, detected)
    embed.verifySensitiveDataProtection(masked.sanitizedText, detected)

    # Stands in for M-03-14 + M-03-07 (both stubs). Masked text only.
    result = _extract_structured_info(cv_file_id, masked.sanitizedText)

    # M-03-08 — raises NoExtractionResultException when all three are empty
    cv_upload.validateExtractionResult(result)

    # M-03-09
    cv_upload.storeExtractedCVInfo(cv_file_id, result)

    found = [
        label for label, value in (
            ("email", detected.emailOriginal),
            ("phone", detected.phoneOriginal),
            ("address", detected.addressOriginal),
            ("ID number", detected.identificationOriginal),
        ) if value
    ]
    return cv_file_id, found


# ---------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------

def render_extracted_info(cv_file_id):
    """Draws what M-03-10 displayExtractedCVInfo returns."""
    info = embed.displayExtractedCVInfo(cv_file_id)
    skills = info.get("skills") or []
    education = info.get("education") or []
    experience = info.get("work_experience") or info.get("workExperience") or []

    if skills:
        st.markdown("## 🛠️ Extracted Skills")
        st.markdown(
            "".join(
                f'<span class="skill-tag">{_skill_label(s)}</span>' for s in skills
            ),
            unsafe_allow_html=True,
        )

    if education:
        st.markdown("## 🎓 Extracted Education")
        for edu in education:
            inst = edu.get("institution", "") if isinstance(edu, dict) else str(edu)
            degree = edu.get("degree", "") if isinstance(edu, dict) else ""
            sy = edu.get("start_year") if isinstance(edu, dict) else None
            ey = edu.get("end_year") if isinstance(edu, dict) else None
            years = f"{sy}" + (f" - {ey}" if sy and ey else "") if sy else ""
            st.markdown(
                f'<div class="card"><strong>{inst}</strong> {degree} {years}</div>',
                unsafe_allow_html=True,
            )

    if experience:
        st.markdown("## 💼 Extracted Work Experience")
        for exp in experience:
            if not isinstance(exp, dict):
                continue
            dates = f"{exp.get('start_date','')}" + (
                f" - {exp.get('end_date')}" if exp.get("end_date") else ""
            )
            st.markdown(
                f'<div class="card"><strong>{exp.get("company","")}</strong> '
                f'{exp.get("position","")} {dates}</div>',
                unsafe_allow_html=True,
            )

    return skills


def render_cv_analysis(cv_file_id):
    """Draws the CV analysis & scoring panel from cv_analysis."""
    st.markdown('<hr class="analysis-section-sep">', unsafe_allow_html=True)
    st.markdown("## 📊 CV Analysis & Scoring")
    with st.spinner("🤖 Analyzing your CV..."):
        try:
            analysis_result: CVAnalysisResult = analyzeCV(cv_file_id)
            st.success("✅ Analysis complete")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                overall_pct = analysis_result.overallScore * 100
                st.metric("Overall", f"{overall_pct:.0f}/100")
            with col2:
                comp_pct = analysis_result.completenessScore * 100
                st.metric("Completeness", f"{comp_pct:.0f}/100")
            with col3:
                rel_pct = analysis_result.relevanceScore * 100
                st.metric("Relevance", f"{rel_pct:.0f}/100")
            with col4:
                cla_pct = analysis_result.clarityScore * 100
                st.metric("Clarity", f"{cla_pct:.0f}/100")

            if analysis_result.suggestions:
                st.markdown("### 💡 Improvement Suggestions")
                for s in analysis_result.suggestions:
                    st.markdown(f"- {s}")

        except Exception as e:
            err_msg = handleAnalysisError(e)
            st.warning(f"⚠️ {err_msg}")

    st.markdown('<hr class="analysis-section-sep">', unsafe_allow_html=True)


def _skill_label(skill):
    """Skills are now objects; strings are still accepted for older records."""
    if isinstance(skill, dict):
        return skill.get("skill_name") or skill.get("name") or ""
    return str(skill)


def _show_matching_error(exception):
    """
    Shows M-02-12's user-facing message, with the underlying cause tucked
    into an expander.

    The message alone is deliberately non-technical, which is right for a
    Jobseeker and useless for whoever has to fix it — "An unexpected error
    occurred" gave no way to tell a missing database column from a bug in the
    scoring. The detail is collapsed so it does not intrude, but it is there.
    """
    st.error(f"❌ {match_controller.handle_matching_error(exception)}")
    with st.expander("Details (for whoever is running this)"):
        st.code(f"{type(exception).__name__}: {exception}", language="text")
        detail = getattr(exception, "detail", None)
        if detail:
            st.code(detail, language="text")
        cause = getattr(exception, "__cause__", None)
        if cause is not None:
            st.code(f"caused by {type(cause).__name__}: {cause}", language="text")
        st.caption(
            "Run `python verify_integration.py --no-ai` for a fuller check of "
            "the database, schema and pipeline."
        )


def render_matches(cv_file_id):
    """
    Draws the ranked matches M-02-10 returns.

    One list in rank order, per SRS-054/055 — not the previous "Top 5" and
    "Other Matches" split, which no requirement describes.
    """
    matches = match_controller.display_job_match_results(cv_file_id)

    if not matches:
        # SRS-057
        st.info("No job listings are currently available to match against.")
        return

    st.markdown("## 🎯 Job Matches")
    st.caption(f"{len(matches)} listings ranked by how well they match your CV")

    for position, match in enumerate(matches, start=1):
        score = float(match.get("match_score") or 0.0)
        score_class = (
            "score-high" if score > 0.6 else
            "score-mid" if score > 0.4 else
            "score-low"
        )
        matched = match.get("matched_skills") or []
        job_skills = match.get("skills") or []
        matched_lower = {str(s).lower() for s in matched}
        unmatched = [s for s in job_skills if str(s).lower() not in matched_lower]

        tags = "".join(
            f'<span class="skill-tag" style="background:#dcfce7;color:#16a34a">{s}</span>'
            for s in matched
        ) + "".join(f'<span class="skill-tag">{s}</span>' for s in unmatched)

        st.markdown(f"""
        <div class="card">
            <h3>#{match.get('rank_position', position)} &nbsp; {match.get('job_title', 'Unknown Title')}</h3>
            <p>🏢 {match.get('company_name') or '—'} | 📍 {match.get('job_location') or '—'}</p>
            <p class="{score_class}">⭐ Match Score: {score:.3f}</p>
            <p><strong>Skills:</strong> {tags}</p>
        </div>
        """, unsafe_allow_html=True)

        st.progress(min(max(score, 0.0), 1.0))

        # M-02-11 — validates the URL; SRS-062 disables just this card's link
        # when it is unusable, leaving the rest of the list alone.
        try:
            url = match_controller.open_job_posting(match.get("url"))
            st.link_button("🔗 View Job Posting", url)
        except match_controller.JobPostingUnavailableException as ex:
            st.caption(f"🚫 {match_controller.handle_matching_error(ex)}")

        st.markdown("")


# ---------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------

st.markdown('<div class="title">📄 CVision</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Upload your CV and discover your best job matches 🚀</div>',
            unsafe_allow_html=True)
st.markdown("")

if "cv_file_id" not in st.session_state:
    st.session_state["cv_file_id"] = None

# "My CVs" — reads the jobseeker_cv index. Until Feature 5 exists every upload
# carries the same stand-in id, so this lists all guest uploads rather than
# one person's. The table and the query are in place for Feature 5 to inherit.
previous = cv_data_adapter.list_cv_ids_for(JOBSEEKER_ID)
if previous:
    with st.expander(f"📁 My CVs ({len(previous)})"):
        st.caption(
            "Uploaded previously. Until sign-in exists (Feature 5) these are "
            "attributed to a shared guest identity."
        )
        for row in previous[:20]:
            col_name, col_use = st.columns([5, 1])
            col_name.write(f"{row.get('original_filename') or row['cv_id']}")
            if col_use.button("Use", key=f"use_{row['cv_id']}"):
                st.session_state["cv_file_id"] = row["cv_id"]
                st.rerun()

uploaded_file = st.file_uploader(
    "📤 Upload your CV (PDF)",
    type=["pdf"],
    help="Drag and drop your CV here, or click Browse files. PDF format, max 20 MB.",
)

if uploaded_file:
    st.markdown(
        f'<div class="card">📎 Selected file: <strong>{uploaded_file.name}</strong></div>',
        unsafe_allow_html=True,
    )
    with st.spinner("🔍 Validating, protecting and parsing your CV..."):
        try:
            cv_file_id, masked_fields = process_cv(uploaded_file)
            st.session_state["cv_file_id"] = cv_file_id
            st.session_state["masked_fields"] = masked_fields
            st.success(f"✅ Upload successful: {uploaded_file.name}")
        except CVUploadException as ex:
            # M-03-03 for upload failures, M-03-15 for protection/AI failures.
            upload_errors = (
                cv_upload.InvalidFileFormatException,
                cv_upload.FileSizeExceededException,
                cv_upload.CorruptedFileException,
                cv_upload.StorageException,
            )
            if isinstance(ex, upload_errors):
                message = cv_upload.handleUploadError(ex)
            else:
                message = embed.handleProtectionError(ex)
            st.error(f"❌ {message}")
            st.stop()
        except Exception as ex:
            st.error(f"❌ {embed.handleProtectionError(ex)}")
            st.stop()

cv_file_id = st.session_state.get("cv_file_id")

if cv_file_id:
    masked_fields = st.session_state.get("masked_fields") or []
    if masked_fields:
        st.markdown(
            f'<div class="masked-note">🔒 Your {", ".join(masked_fields)} '
            f'{"was" if len(masked_fields) == 1 else "were"} masked before your CV '
            f'was sent for analysis.</div>',
            unsafe_allow_html=True,
        )

    cv_skills = render_extracted_info(cv_file_id)

    render_cv_analysis(cv_file_id)

    # M-02-01 — UC-006 Step 1. The matching side reads the CV through Feature
    # 2's own entry point rather than reusing what M-03-10 returned for
    # display: the two happen to agree today, but M-02-01 is where SRS-061's
    # "please re-upload your CV" is raised if the stored data is unusable, and
    # that check belongs before matching starts rather than after.
    try:
        match_controller.retrieve_cv_data(cv_file_id)
    except Exception as ex:
        _show_matching_error(ex)
        st.stop()

    with st.spinner("🎯 Matching you against available jobs..."):
        try:
            match_controller.generate_job_matches(cv_file_id)
        except Exception as ex:
            _show_matching_error(ex)
            st.stop()

    render_matches(cv_file_id)