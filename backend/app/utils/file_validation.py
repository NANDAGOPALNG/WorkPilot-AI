import io
import os
import re
import zipfile

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_DOCX_UNCOMPRESSED = 100 * 1024 * 1024  # zip-bomb guard

# extension -> canonical MIME type (also what we store in Supabase Storage)
CANONICAL_MIME = {
    "pdf": "application/pdf",
    "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
# Browsers/tools often send a generic type, so these are accepted for any extension.
GENERIC_MIME = {"", "application/octet-stream", "binary/octet-stream"}


class FileValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def clean_filename(filename: str | None) -> str:
    """Display-safe filename: no directories, no control characters, max 255 chars."""
    name = os.path.basename((filename or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:255]


def validate_upload(filename: str | None, content_type: str | None, data: bytes) -> str:
    """Validate an uploaded file and return its type ('pdf' | 'txt' | 'docx').

    Checks extension, declared MIME type (if specific), size, and the actual content
    (magic bytes), so a renamed file is rejected.
    """
    name = clean_filename(filename)
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if ext not in CANONICAL_MIME:
        raise FileValidationError("Unsupported file type. Allowed: PDF, TXT, DOCX.", 415)

    if not data:
        raise FileValidationError("The file is empty.", 400)
    if len(data) > MAX_FILE_SIZE:
        raise FileValidationError(
            f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.", 413
        )

    mime = (content_type or "").split(";")[0].strip().lower()
    if mime not in GENERIC_MIME and mime != CANONICAL_MIME[ext]:
        raise FileValidationError(f"Content type '{mime}' does not match a .{ext} file.", 415)

    if ext == "pdf":
        if b"%PDF-" not in data[:1024]:
            raise FileValidationError("File content is not a valid PDF.", 415)
    elif ext == "docx":
        _check_docx(data)
    else:  # txt
        if b"\x00" in data:
            raise FileValidationError("File looks binary, not plain text (UTF-8 expected).", 415)
    return ext


def _check_docx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if "word/document.xml" not in zf.namelist():
                raise FileValidationError("File content is not a valid DOCX.", 415)
            if sum(i.file_size for i in zf.infolist()) > MAX_DOCX_UNCOMPRESSED:
                raise FileValidationError("DOCX expands to an unreasonable size.", 413)
    except zipfile.BadZipFile:
        raise FileValidationError("File content is not a valid DOCX.", 415) from None
