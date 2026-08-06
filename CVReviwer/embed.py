from __future__ import annotations
import json
import os
import re
import asyncio
from typing import Any
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
from dotenv import load_dotenv
from openai import AsyncOpenAI
from cv_upload import (
    CVUploadException,
    NoExtractionResultException,
    SensitiveInfoResult,
    MaskedCVResult,
    AIExtractionResult,
    _load_cvs,
    _save_cvs,
)


class AIServiceUnavailableException(CVUploadException):
    """Raised when AI service is unavailable."""
    pass


class MaskingException(CVUploadException):
    """Raised when masking sensitive data fails."""
    pass


class SensitiveDataProtectionException(CVUploadException):
    """Raised when sensitive data protection verification fails."""
    pass


class UnprotectedTransmissionException(CVUploadException):
    """Raised when attempting to transmit unprotected data."""
    pass


# Regex patterns for sensitive information detection
SENSITIVE_PATTERNS = {
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone": r"(\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})",
    "address": r"\d+\s+[a-zA-Z\s]+(?:street|st|avenue|ave|road|rd|drive|dr|boulevard|blvd|lane|ln)",
    "identification": r"\b\d{10,13}\b",
}


# M-029: extractStructuredCVInfo
def extractStructuredCVInfo(cvFileId: str, rawCVText: str) -> AIExtractionResult:
    """
    Transmits raw CV text to External AI Service to extract structured information.

    Params:
        cvFileId: The unique identifier of the CV
        rawCVText: The raw text content extracted from the CV

    Returns:
        AIExtractionResult with extracted categories

    Throws:
        AIServiceUnavailableException: if AI service unavailable or unresponsive
    """
    try:
        # In a real implementation, this would call the external AI service
        # For now, return a placeholder
        result = AIExtractionResult(
            skills=[],
            education=[],
            workExperience=[]
        )
        return result
    except Exception as e:
        raise AIServiceUnavailableException(f"AI Service unavailable: {str(e)}")


# M-032: displayExtractedCVInfo
def displayExtractedCVInfo(cvFileId: str) -> dict[str, Any]:
    """
    Retrieves and displays extracted CV information for Jobseeker review.

    Params:
        cvFileId: The unique identifier of the CV file

    Returns:
        dict with extracted information

    Throws:
        NoExtractionResultException: if no extracted data found
    """
    try:
        records = _load_cvs()
        record = next((r for r in records if r["id"] == cvFileId), None)

        if not record or "extracted_data" not in record:
            raise NoExtractionResultException(f"No extracted information found for CV {cvFileId}")

        return record["extracted_data"]
    except NoExtractionResultException:
        raise
    except Exception as e:
        raise NoExtractionResultException(f"Failed to retrieve extracted CV information: {str(e)}")


# M-033: detectSensitiveInfo
def detectSensitiveInfo(rawCVText: str) -> SensitiveInfoResult:
    """
    Scans CV text to detect sensitive personal information.

    Params:
        rawCVText: The raw CV text to scan

    Returns:
        SensitiveInfoResult with detected sensitive fields
    """
    result = SensitiveInfoResult()

    # Detect emails
    emails = re.findall(SENSITIVE_PATTERNS["email"], rawCVText)
    if emails:
        result.emailOriginal = emails[0]

    # Detect phone numbers
    phones = re.findall(SENSITIVE_PATTERNS["phone"], rawCVText)
    if phones:
        result.phoneOriginal = phones[0][0] if phones[0] else None

    # Detect addresses
    addresses = re.findall(SENSITIVE_PATTERNS["address"], rawCVText, re.IGNORECASE)
    if addresses:
        result.addressOriginal = addresses[0]

    # Detect identification numbers
    ids = re.findall(SENSITIVE_PATTERNS["identification"], rawCVText)
    if ids:
        result.identificationOriginal = ids[0]

    return result


# M-034: maskSensitiveInfo
def maskSensitiveInfo(rawCVText: str, detected: SensitiveInfoResult) -> MaskedCVResult:
    """
    Replaces detected sensitive information with masked equivalents.

    Params:
        rawCVText: The raw CV text with sensitive info
        detected: The detected sensitive fields

    Returns:
        MaskedCVResult with sanitized text

    Throws:
        MaskingException: if masking fails
    """
    try:
        sanitized_text = rawCVText

        # Mask email
        if detected.emailOriginal:
            parts = detected.emailOriginal.split("@")
            masked_email = f"t***@{parts[1]}" if len(parts) > 1 else "t***@domain.com"
            sanitized_text = sanitized_text.replace(detected.emailOriginal, masked_email)
        else:
            masked_email = None

        # Mask phone
        if detected.phoneOriginal:
            # Extract last 4 digits
            digits = re.sub(r"\D", "", detected.phoneOriginal)
            masked_phone = f"--{digits[-4:]}" if len(digits) >= 4 else "--XXXX"
            sanitized_text = sanitized_text.replace(detected.phoneOriginal, masked_phone)
        else:
            masked_phone = None

        # Mask address
        if detected.addressOriginal:
            # Extract city and region if possible
            masked_address = "*** " + detected.addressOriginal.split()[-2:][0] if len(detected.addressOriginal.split()) > 1 else "*** City, Region"
            sanitized_text = sanitized_text.replace(detected.addressOriginal, masked_address)
        else:
            masked_address = None

        # Mask identification
        if detected.identificationOriginal:
            digits = detected.identificationOriginal
            masked_id = f"{'*' * (len(digits) - 4)}{digits[-4:]}" if len(digits) > 4 else "*" * len(digits)
            sanitized_text = sanitized_text.replace(detected.identificationOriginal, masked_id)
        else:
            masked_id = None

        return MaskedCVResult(
            sanitizedText=sanitized_text,
            isMasked=True,
            emailOriginal=detected.emailOriginal,
            maskedEmail=masked_email,
            phoneOriginal=detected.phoneOriginal,
            maskedPhone=masked_phone,
            addressOriginal=detected.addressOriginal,
            maskedAddress=masked_address,
            identificationOriginal=detected.identificationOriginal,
            maskedIdentification=masked_id
        )
    except Exception as e:
        raise MaskingException(f"Failed to mask sensitive information: {str(e)}")


# M-035: verifySensitiveDataProtection
def verifySensitiveDataProtection(sanitizedText: str, detected: SensitiveInfoResult) -> None:
    """
    Verifies that no unprotected sensitive information remains in sanitized text.

    Params:
        sanitizedText: The CV text after masking
        detected: The original detected sensitive fields

    Throws:
        SensitiveDataProtectionException: if unprotected data found
    """
    # Re-check for unmasked sensitive data
    if detected.emailOriginal and detected.emailOriginal in sanitizedText:
        raise SensitiveDataProtectionException(
            "CV processing could not be completed securely"
        )

    if detected.phoneOriginal and detected.phoneOriginal in sanitizedText:
        raise SensitiveDataProtectionException(
            "CV processing could not be completed securely"
        )

    if detected.addressOriginal and detected.addressOriginal in sanitizedText:
        raise SensitiveDataProtectionException(
            "CV processing could not be completed securely"
        )

    if detected.identificationOriginal and detected.identificationOriginal in sanitizedText:
        raise SensitiveDataProtectionException(
            "CV processing could not be completed securely"
        )


# M-036: transmitProtectedCVData
def transmitProtectedCVData(cvFileId: str, sanitizedText: str, isMasked: bool) -> AIExtractionResult:
    """
    Transmits protected CV data to External AI Service.

    Params:
        cvFileId: The unique identifier of the CV
        sanitizedText: The masked CV text
        isMasked: Flag confirming sensitive data masking

    Returns:
        AIExtractionResult from the service

    Throws:
        UnprotectedTransmissionException: if isMasked is False
        AIServiceUnavailableException: if service unavailable
    """
    if not isMasked:
        raise UnprotectedTransmissionException(
            "Cannot transmit unprotected data"
        )

    try:
        # In a real implementation, transmit to external AI service
        result = AIExtractionResult(
            skills=[],
            education=[],
            workExperience=[]
        )
        return result
    except Exception as e:
        raise AIServiceUnavailableException(f"AI Service unavailable: {str(e)}")


# M-037: handleProtectionError
def handleProtectionError(exception: Exception) -> str:
    """
    Maps sensitive data protection exceptions to user-facing error messages.

    Params:
        exception: The exception thrown during protection or transmission

    Returns:
        User-facing error message string
    """
    error_messages = {
        "MaskingException": "CV processing could not be completed securely — masking failed",
        "SensitiveDataProtectionException": "CV processing could not be completed securely",
        "UnprotectedTransmissionException": "CV processing could not be completed securely — unprotected data detected",
        "AIServiceUnavailableException": "The analysis service is temporarily unavailable — please try again later",
    }

    exception_type = type(exception).__name__
    return error_messages.get(exception_type, "An unexpected error occurred. Please try again")


if __name__ == "__main__":
    def clean_json(content):
        content = content.strip()
        content = re.sub(r"^```[a-zA-Z]*", "", content)
        content = re.sub(r"```$", "", content)
        return content.strip()

    load_dotenv()
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    INPUT_FILE = "jobs.json"
    OUTPUT_FILE = "jobs_with_embeddings.json"
    MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
    BATCH_SIZE = 16

    async def extract_with_llm(text, model="gpt-4o-mini"):
        prompt = f"""
    Extract structured job data in English.

    Return ONLY valid JSON (no explanation, no markdown) with this schema:
    {{{{"location": null, "skills": [], "salary": null, "job_type": null, "work_mode": null, "benefits": [], "experience_years": null, "education": null, "translated_description": ""}}}}

    Rules:
    - Detect the language automatically
    - Location: Translate to English if not English; keep structure: District, City; Do NOT invent new formats
    - Skills, benefits, education: Translate to English; Do NOT translate technical terms (Python, React, SQL, etc.)
    - translated_description: Translate and summarize in 2-3 sentences
    - job_type: fulltime | parttime | contract | freelance | null
    - work_mode: remote | hybrid | onsite | null
    - experience_years: number only
    - If missing -> null

    Job description:
    \"\"\"{text}\"\"\"
    """

        try:
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a strict JSON generator. Return valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
            }

            if model != "gpt-5":
                kwargs["temperature"] = 0
                kwargs["max_tokens"] = 600
            else:
                kwargs["max_completion_tokens"] = 800

            response = await asyncio.wait_for(
                client.chat.completions.create(**kwargs),
                timeout=30
            )

            content = response.choices[0].message.content

            if not content:
                print("Empty response from model")
                return None

            content = content.strip()
            content = clean_json(content)

            try:
                return json.loads(content)
            except Exception as e:
                print("JSON parse error:", e)
                print("RAW RESPONSE:", content[:300])
                return None

        except asyncio.TimeoutError:
            print("Request timed out")
            return None
        except Exception as e:
            print("LLM error:", e)
            return None

    def normalize_output(job, extracted):
        def get_or_null(key, default=None):
            return extracted.get(key) if extracted and key in extracted else default

        job["skills"] = get_or_null("skills", job.get("skills", [])) or []
        job["salary"] = get_or_null("salary", None)
        job["job_type"] = get_or_null("job_type", None)
        job["work_mode"] = get_or_null("work_mode", None)
        job["benefits"] = get_or_null("benefits", []) or []
        job["experience_years"] = get_or_null("experience_years", None)
        job["education"] = get_or_null("education", None)
        job["company"] = job.get("company")
        job["title"] = job.get("title")
        job["location"] = get_or_null("location", job.get("location"))
        job["description"] = job.get("description", None)
        job["translated_description"] = get_or_null(
            "translated_description",
            job.get("description", "")
        )

    def is_bad_result(data):
        if not data:
            return True
        if not isinstance(data.get("skills"), list):
            return True
        if len(data.get("skills", [])) == 0:
            return True
        if data.get("translated_description") is None:
            return True
        return False

    async def process_job_with_fallback(text, title=None):
        text = text[:1500]
        await asyncio.sleep(0.3)
        data = await extract_with_llm(text, model="gpt-4o-mini")
        if not is_bad_result(data):
            return data
        print(f"Retry GPT-4o-mini... ({title})")
        await asyncio.sleep(0.5)
        data = await extract_with_llm(text, model="gpt-4o-mini")
        if not is_bad_result(data):
            return data
        print(f"Switching to GPT-5... ({title})")
        await asyncio.sleep(0.5)
        data = await extract_with_llm(text, model="gpt-5")
        if not is_bad_result(data):
            return data
        print(f"Final retry GPT-5... ({title})")
        await asyncio.sleep(0.8)
        data = await extract_with_llm(text, model="gpt-5")
        if not is_bad_result(data):
            return data
        print(f"All attempts failed ({title})")
        return {}

    print("Loading model...")
    model = SentenceTransformer(MODEL_NAME)

    if os.path.exists(OUTPUT_FILE):
        print("Loading existing embeddings (cache)...")
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            jobs = json.load(f)
    else:
        print("Loading fresh jobs...")
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            jobs = json.load(f)

    semaphore = asyncio.Semaphore(2)

    async def process_single_job(i, job):
        async with semaphore:
            if "embedding" in job:
                return None
            raw_text = job.get("description", "")
            if not raw_text.strip():
                normalize_output(job, {})
                return i, "general"
            if not job.get("skills") or not job.get("translated_description"):
                result = await process_job_with_fallback(
                    raw_text,
                    title=job.get("title")
                )
                normalize_output(job, result or {})
            title = job.get("title", "")
            skills = " ".join(job.get("skills", []))
            if not title and not skills:
                embed_text = "general"
            else:
                embed_text = f"Title: {title} | Skills: {skills}"
            return i, embed_text[:500]

    async def process_all_jobs(jobs):
        texts = []
        indices = []
        batch_size = 50
        for i in range(0, len(jobs), batch_size):
            batch = jobs[i:i+batch_size]
            tasks = [process_single_job(i + j, job) for j, job in enumerate(batch)]
            results = await asyncio.gather(*tasks)
            for result in results:
                if result is None:
                    continue
                idx, text = result
                texts.append(text)
                indices.append(idx)
        return texts, indices

    print("Processing jobs with async...")
    texts, indices = asyncio.run(process_all_jobs(jobs))
    print(f"Need to embed {len(texts)} jobs")

    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        batch_indices = indices[i:i + BATCH_SIZE]
        embeddings = model.encode(batch_texts, show_progress_bar=False)
        for idx, emb in zip(batch_indices, embeddings):
            jobs[idx]["embedding"] = emb.tolist()
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)

    print("All embeddings saved to", OUTPUT_FILE)