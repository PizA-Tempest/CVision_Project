"""Shared test helpers and mock utilities."""

import io
import os
import sys
import uuid
import json
import hashlib
import tempfile
from datetime import datetime, timezone
from typing import Any

import pikepdf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class MockFile:
    """Simulates a Streamlit UploadedFile for testing."""

    def __init__(self, name: str, data: bytes = b"", mime_type: str | None = None):
        self.name = name
        self._data = data
        self.type = mime_type

    def getvalue(self) -> bytes:
        return self._data

    def read(self) -> bytes:
        return self._data


def make_valid_pdf() -> bytes:
    buf = io.BytesIO()
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.save(buf)
    data = buf.getvalue()
    pdf.close()
    return data


def make_pdf_with_text(text: str) -> bytes:
    """Create a PDF with actual text content extractable by PyPDF2."""
    text_bytes = text.encode("latin-1", "replace")
    stream_data = (
        b"BT /F1 12 Tf 100 700 Td "
        b"(" + text_bytes + b") Tj ET"
    )
    stream_len = len(stream_data)
    objs = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj",
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj",
        b"4 0 obj<< /Length " + str(stream_len).encode() + b" >>"
        b"stream\n" + stream_data + b"\nendstreamendobj",
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj",
    ]
    body = b"\n".join(objs)
    xref_offset = b"%PDF-1.4\n".__len__()
    xref_entries = [b"0000000000 65535 f "]
    offset = 0
    for i, obj in enumerate(objs):
        if i == 0:
            offset = xref_offset
        xref_entries.append(f"{offset:010d} 00000 n ".encode())
        offset += len(obj) + 1
    trailer = (
        b"trailer<< /Size " + str(len(objs) + 1).encode() +
        b" /Root 1 0 R >>\nstartxref\n" +
        str(xref_offset + len(body) + 1).encode() +
        b"\n%%EOF"
    )
    return b"%PDF-1.4\n" + body + b"\nxref\n0 " + str(len(objs) + 1).encode() + b"\n" + b"".join(xref_entries) + trailer


def make_large_pdf(size_bytes: int) -> bytes:
    base = make_valid_pdf()
    if len(base) >= size_bytes:
        return base[:size_bytes]
    repeat = (size_bytes // len(base)) + 1
    data = (base * repeat)[:size_bytes]
    data = b"%PDF-" + data[5:]
    return data


def make_corrupted_pdf() -> bytes:
    return b"%PDF-\x00\x00\x00CORRUPTED\x00\x00\x00"


def make_docx_data() -> bytes:
    return b"PK\x03\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"


def make_exe_data() -> bytes:
    return b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"


class TestEnvironment:
    """Manages temp directory and file patching for tests."""

    def __init__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.uploads_dir = os.path.join(self.temp_dir.name, "uploads")
        self.registry_file = os.path.join(self.temp_dir.name, "cvs.json")
        os.makedirs(self.uploads_dir, exist_ok=True)

        self._patches = []
        self._setup_patches()

    def _setup_patches(self):
        import cv_upload as cv

        self._patch(cv, "UPLOADS_DIR", self.uploads_dir)
        self._patch(cv, "CVS_REGISTRY_FILE", self.registry_file)

    def _patch(self, module, name, value):
        original = getattr(module, name, None)
        setattr(module, name, value)
        self._patches.append((module, name, original))

    def cleanup(self):
        for module, name, original in self._patches:
            if original is not None:
                setattr(module, name, original)
            else:
                delattr(module, name)
        self.temp_dir.cleanup()

    def store_cv_record(self, record: dict | None = None):
        if record is None:
            record = {
                "id": uuid.uuid4().hex,
                "original_filename": "test.pdf",
                "stored_path": os.path.join(self.uploads_dir, "test.pdf"),
                "size_bytes": 1024,
                "sha256": hashlib.sha256(b"test").hexdigest(),
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "validation_status": "validated",
            }
        records = []
        if os.path.exists(self.registry_file):
            with open(self.registry_file, "r") as f:
                records = json.load(f)
        records.append(record)
        with open(self.registry_file, "w") as f:
            json.dump(records, f, indent=2)
        return record

    def ensure_text_pdf_on_disk(self, text: str = "Sample CV text", record_id: str | None = None) -> tuple[str, dict]:
        """Creates a PDF with extractable text on disk, returns (id, record)."""
        pdf_data = make_pdf_with_text(text)
        file_id = record_id or uuid.uuid4().hex
        safe_name = f"{file_id}_cv.pdf"
        stored_path = os.path.join(self.uploads_dir, safe_name)
        os.makedirs(os.path.dirname(stored_path), exist_ok=True)
        with open(stored_path, "wb") as f:
            f.write(pdf_data)
        record = {
            "id": file_id,
            "original_filename": "cv.pdf",
            "stored_path": stored_path,
            "size_bytes": len(pdf_data),
            "sha256": hashlib.sha256(pdf_data).hexdigest(),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "validation_status": "validated",
        }
        self.store_cv_record(record)
        return file_id, record
