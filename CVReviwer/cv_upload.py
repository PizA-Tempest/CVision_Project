"""CV upload validation and persistent storage (URS-004, SRS-034–038)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pikepdf
import PyPDF2

MAX_CV_BYTES = 20 * 1024 * 1024
MAX_TEXT_LENGTH = 50000
ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
}
UPLOADS_DIR = "uploads"
CVS_REGISTRY_FILE = "cvs.json"
PDF_MAGIC = b"%PDF-"


# Custom Exceptions
class CVUploadException(Exception):
    """Base exception for CV upload errors."""
    pass


class InvalidFileFormatException(CVUploadException):
    """Raised when file format is not supported."""
    pass


class FileSizeExceededException(CVUploadException):
    """Raised when file size exceeds maximum limit."""
    pass


class CorruptedFileException(CVUploadException):
    """Raised when file is corrupted or unreadable."""
    pass


class StorageException(CVUploadException):
    """Raised when file storage fails."""
    pass


class ExtractionPreparationException(CVUploadException):
    """Raised when text extraction fails."""
    pass


class NoExtractionResultException(CVUploadException):
    """Raised when no information could be extracted."""
    pass


class MissingErrorMessageException(CVUploadException):
    """Raised when error message is missing for failed upload."""
    pass


class DatabaseException(CVUploadException):
    """Raised when database operation fails."""
    pass


# Data Classes
@dataclass(frozen=True)
class CVValidationResult:
    ok: bool
    message: str
    code: str = ""
    text: str = ""
    stored_record: dict[str, Any] | None = None


@dataclass
class SensitiveInfoResult:
    """Result of sensitive information detection."""
    emailOriginal: str | None = None
    phoneOriginal: str | None = None
    addressOriginal: str | None = None
    identificationOriginal: str | None = None


@dataclass
class MaskedCVResult:
    """Result of masking sensitive information."""
    sanitizedText: str
    isMasked: bool
    emailOriginal: str | None = None
    maskedEmail: str | None = None
    phoneOriginal: str | None = None
    maskedPhone: str | None = None
    addressOriginal: str | None = None
    maskedAddress: str | None = None
    identificationOriginal: str | None = None
    maskedIdentification: str | None = None


@dataclass
class AIExtractionResult:
    """Result returned by External AI Service."""
    skills: list[dict[str, Any]] = field(default_factory=list)
    education: list[dict[str, Any]] = field(default_factory=list)
    workExperience: list[dict[str, Any]] = field(default_factory=list)


def _load_cvs() -> list[dict[str, Any]]:
    try:
        with open(CVS_REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_cvs(records: list[dict[str, Any]]) -> None:
    with open(CVS_REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name)
    base = re.sub(r"[^\w.\- ]", "_", base)
    return base or "cv.pdf"


def _check_file_type(name: str, mime_type: str | None) -> CVValidationResult | None:
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return CVValidationResult(
            ok=False,
            code="UNSUPPORTED_TYPE",
            message=(
                "The selected file is not supported. "
                "Please upload your CV as a PDF file (.pdf)."
            ),
        )

    if mime_type and mime_type not in ALLOWED_MIME_TYPES:
        non_pdf_prefixes = ("image/", "video/", "audio/", "text/")
        if mime_type.startswith(non_pdf_prefixes):
            return CVValidationResult(
                ok=False,
                code="UNSUPPORTED_TYPE",
                message=(
                    "The selected file is not supported. "
                    "Please upload your CV as a PDF file (.pdf)."
                ),
            )

    return None


def _check_file_size(size: int) -> CVValidationResult | None:
    if size <= 0:
        return CVValidationResult(
            ok=False,
            code="CORRUPTED",
            message=(
                "The uploaded file appears to be corrupted or unreadable. "
                "Please upload a valid PDF CV."
            ),
        )
    if size > MAX_CV_BYTES:
        return CVValidationResult(
            ok=False,
            code="FILE_TOO_LARGE",
            message="The file exceeds the maximum allowed size of 20 MB.",
        )
    return None


def _check_pdf_magic(data: bytes) -> CVValidationResult | None:
    if not data.startswith(PDF_MAGIC):
        return CVValidationResult(
            ok=False,
            code="CORRUPTED",
            message=(
                "The uploaded file appears to be corrupted or unreadable. "
                "Please upload a valid PDF CV."
            ),
        )
    return None


def _verify_pdf_integrity(data: bytes) -> CVValidationResult | None:
    corrupted = CVValidationResult(
        ok=False,
        code="CORRUPTED",
        message=(
            "The uploaded file appears to be corrupted or unreadable. "
            "Please upload a valid PDF CV."
        ),
    )

    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            if pdf.is_encrypted:
                return corrupted
            if len(pdf.pages) == 0:
                return corrupted
        return None
    except pikepdf.PdfError:
        pass
    except Exception:
        pass

    try:
        reader = PyPDF2.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return corrupted
        if len(reader.pages) == 0:
            return corrupted
        return None
    except Exception:
        return corrupted


def _extract_pdf_text(data: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    return "".join(page.extract_text() or "" for page in reader.pages)


def _store_cv(data: bytes, original_name: str) -> dict[str, Any]:
    os.makedirs(UPLOADS_DIR, exist_ok=True)

    file_id = uuid.uuid4().hex
    safe_name = _sanitize_filename(original_name)
    stored_name = f"{file_id}_{safe_name}"
    stored_path = os.path.join(UPLOADS_DIR, stored_name)

    sha256 = hashlib.sha256(data).hexdigest()
    with open(stored_path, "wb") as f:
        f.write(data)

    record = {
        "id": file_id,
        "original_filename": original_name,
        "stored_path": stored_path,
        "size_bytes": len(data),
        "sha256": sha256,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "validation_status": "validated",
    }

    records = _load_cvs()
    records.append(record)
    _save_cvs(records)

    return record


def validate_and_store_cv(uploaded_file) -> CVValidationResult:
    """Validate an uploaded CV and persist it when all checks pass."""
    name = uploaded_file.name or "cv.pdf"
    mime_type = getattr(uploaded_file, "type", None)

    type_error = _check_file_type(name, mime_type)
    if type_error:
        return type_error

    data = uploaded_file.getvalue()

    size_error = _check_file_size(len(data))
    if size_error:
        return size_error

    magic_error = _check_pdf_magic(data)
    if magic_error:
        return magic_error

    integrity_error = _verify_pdf_integrity(data)
    if integrity_error:
        return integrity_error

    try:
        text = _extract_pdf_text(data)
    except Exception:
        return CVValidationResult(
            ok=False,
            code="CORRUPTED",
            message=(
                "The uploaded file appears to be corrupted or unreadable. "
                "Please upload a valid PDF CV."
            ),
        )

    sha256 = hashlib.sha256(data).hexdigest()
    for record in _load_cvs():
        if record.get("sha256") == sha256:
            return CVValidationResult(
                ok=True,
                code="SUCCESS",
                message=f"Upload successful: {name}",
                text=text,
                stored_record=record,
            )

    stored_record = _store_cv(data, name)

    return CVValidationResult(
        ok=True,
        code="SUCCESS",
        message=f"Upload successful: {name}",
        text=text,
        stored_record=stored_record,
    )


# ============================================================================
# METHOD IMPLEMENTATIONS (M-023 through M-031)
# ============================================================================

# M-023: uploadCVFile
def uploadCVFile(file: Any, jobseekerId: str) -> dict[str, Any]:
    """
    Handles the CV file upload request from the upload interface.
    
    Params:
        file: The CV file submitted through the upload interface
        jobseekerId: The unique identifier of the authenticated Jobseeker
        
    Returns:
        dict with success message and file metadata
        
    Throws:
        InvalidFileFormatException, FileSizeExceededException, CorruptedFileException, StorageException
    """
    try:
        # Validate file
        validation_result = validateCVFile(file)
        
        # Store file
        stored_record = storeCVFile(file, jobseekerId)
        
        return {
            "success": True,
            "cvFileId": stored_record["id"],
            "fileName": stored_record["original_filename"],
            "message": f"Upload successful: {stored_record['original_filename']}"
        }
    except (InvalidFileFormatException, FileSizeExceededException, 
            CorruptedFileException, StorageException) as e:
        raise
    except Exception as e:
        raise StorageException(f"Unexpected error during upload: {str(e)}")


# M-024: displayUploadFeedback
def displayUploadFeedback(fileName: str, success: bool, errorMessage: str | None = None) -> None:
    """
    Displays upload result feedback to the Jobseeker on the upload interface.
    
    Params:
        fileName: The name of the selected or uploaded CV file
        success: Indicates whether upload was successful
        errorMessage: Error message when success is False (required if success=False)
        
    Throws:
        MissingErrorMessageException: if success=False and errorMessage not provided
    """
    if not success and not errorMessage:
        raise MissingErrorMessageException(
            "errorMessage is required when upload is unsuccessful"
        )
    
    if success:
        print(f"✓ Upload successful: {fileName}")
    else:
        print(f"✗ Upload failed for {fileName}: {errorMessage}")


# M-025: handleUploadError
def handleUploadError(exception: Exception) -> str:
    """
    Maps upload-related exceptions to user-facing error messages.
    
    Params:
        exception: The exception thrown during upload or validation
        
    Returns:
        User-facing error message string
    """
    error_messages = {
        "InvalidFileFormatException": "Unsupported file format. Please upload a PDF/A file.",
        "FileSizeExceededException": "File size limit exceeded. Maximum size is 20 MB.",
        "CorruptedFileException": "File is corrupted or unreadable. Please upload a valid CV file.",
        "StorageException": "Could not store the CV file. Please try again.",
    }
    
    exception_type = type(exception).__name__
    return error_messages.get(exception_type, "An unexpected error occurred. Please try again")


# M-026: validateCVFile
def validateCVFile(file: Any) -> None:
    """
    Server-side validation of uploaded CV file before processing.
    
    Params:
        file: The uploaded CV file
        
    Throws:
        InvalidFileFormatException: if not PDF/A format
        FileSizeExceededException: if exceeds 20 MB
        CorruptedFileException: if corrupted or unreadable
    """
    name = file.name or "cv.pdf"
    mime_type = getattr(file, "type", None)
    
    # Check file type
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidFileFormatException("Unsupported file format")
    
    if mime_type and mime_type not in ALLOWED_MIME_TYPES:
        raise InvalidFileFormatException("Unsupported file format")
    
    # Check file size
    data = file.getvalue() if hasattr(file, 'getvalue') else file.read()
    if len(data) > MAX_CV_BYTES:
        raise FileSizeExceededException("File size limit exceeded")
    
    # Check file magic
    if not data.startswith(PDF_MAGIC):
        raise CorruptedFileException("File is corrupted or unreadable")
    
    # Verify PDF integrity
    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            if pdf.is_encrypted or len(pdf.pages) == 0:
                raise CorruptedFileException("File is corrupted or unreadable")
    except pikepdf.PdfError:
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(data))
            if reader.is_encrypted or len(reader.pages) == 0:
                raise CorruptedFileException("File is corrupted or unreadable")
        except Exception:
            raise CorruptedFileException("File is corrupted or unreadable")


# M-027: storeCVFile
def storeCVFile(file: Any, jobseekerId: str) -> dict[str, Any]:
    """
    Persists the validated CV file to storage and records metadata in database.
    
    Params:
        file: The validated CV file
        jobseekerId: The unique identifier of the Jobseeker
        
    Returns:
        dict with generated CV file ID and metadata
        
    Throws:
        StorageException: if file cannot be saved or database insert fails
    """
    try:
        name = file.name or "cv.pdf"
        data = file.getvalue() if hasattr(file, 'getvalue') else file.read()
        
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        
        file_id = uuid.uuid4().hex
        safe_name = _sanitize_filename(name)
        stored_name = f"{file_id}_{safe_name}"
        stored_path = os.path.join(UPLOADS_DIR, stored_name)
        
        sha256 = hashlib.sha256(data).hexdigest()
        
        with open(stored_path, "wb") as f:
            f.write(data)
        
        record = {
            "id": file_id,
            "jobseekerId": jobseekerId,
            "original_filename": name,
            "stored_path": stored_path,
            "size_bytes": len(data),
            "sha256": sha256,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "validation_status": "validated",
        }
        
        records = _load_cvs()
        records.append(record)
        _save_cvs(records)
        
        return record
    except Exception as e:
        raise StorageException(f"Failed to store CV file: {str(e)}")


# M-028: extractTextFromCV
def extractTextFromCV(cvFileId: str) -> str:
    """
    Retrieves stored CV file and extracts all readable textual content.
    
    Params:
        cvFileId: The unique identifier of the stored CV file
        
    Returns:
        Raw extracted text content
        
    Throws:
        ExtractionPreparationException: if file cannot be retrieved or no text found
    """
    try:
        records = _load_cvs()
        record = next((r for r in records if r["id"] == cvFileId), None)
        
        if not record:
            raise ExtractionPreparationException(f"CV file {cvFileId} not found")
        
        stored_path = record["stored_path"]
        
        if not os.path.exists(stored_path):
            raise ExtractionPreparationException(f"CV file not found at {stored_path}")
        
        with open(stored_path, "rb") as f:
            data = f.read()
        
        text = _extract_pdf_text(data)
        
        if not text or len(text.strip()) == 0:
            raise ExtractionPreparationException("No extractable text content found in CV")
        
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH]
        
        return text
    except ExtractionPreparationException:
        raise
    except Exception as e:
        raise ExtractionPreparationException(f"Failed to extract text from CV: {str(e)}")


# M-030: validateExtractionResult
def validateExtractionResult(result: AIExtractionResult) -> None:
    """
    Validates that at least one information category was extracted.
    
    Params:
        result: The extraction result from External AI Service
        
    Throws:
        NoExtractionResultException: if all categories are empty
    """
    has_skills = result.skills and len(result.skills) > 0
    has_education = result.education and len(result.education) > 0
    has_experience = result.workExperience and len(result.workExperience) > 0
    
    if not (has_skills or has_education or has_experience):
        raise NoExtractionResultException(
            "CV could not be processed — please upload a clearer or properly formatted CV"
        )


# M-031: storeExtractedCVInfo
def storeExtractedCVInfo(cvFileId: str, result: AIExtractionResult) -> None:
    """
    Organizes and persists validated extraction result to database.
    
    Params:
        cvFileId: The unique identifier of the CV file
        result: The validated extraction result
        
    Throws:
        DatabaseException: if database insert fails
    """
    try:
        # Load existing data
        cvs = _load_cvs()
        record = next((r for r in cvs if r["id"] == cvFileId), None)
        
        if not record:
            raise DatabaseException(f"CV record {cvFileId} not found")
        
        # Store extracted information
        record["extracted_data"] = {
            "skills": result.skills,
            "education": result.education,
            "work_experience": result.workExperience,
            "extracted_at": datetime.now(timezone.utc).isoformat()
        }
        
        _save_cvs(cvs)
    except DatabaseException:
        raise
    except Exception as e:
        raise DatabaseException(f"Failed to store extracted CV information: {str(e)}")



