import io
import logging
import re

logger = logging.getLogger("workpilot.extraction")


class TextExtractionError(RuntimeError):
    pass


def clean_text(text: str) -> str:
    """Normalise whitespace; drop NUL bytes (Postgres text columns can't store them)."""
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(data: bytes, file_type: str) -> str:
    """Return cleaned text from a validated file. May return '' (e.g. scanned PDF)."""
    try:
        if file_type == "pdf":
            return clean_text(_pdf(data))
        if file_type == "docx":
            return clean_text(_docx(data))
        if file_type == "txt":
            return clean_text(_txt(data))
    except TextExtractionError:
        raise
    except Exception as exc:
        logger.warning("Extraction failed for %s: %s", file_type, type(exc).__name__)
        raise TextExtractionError(f"Could not read the {file_type.upper()} file.") from exc
    raise TextExtractionError(f"Unsupported file type: {file_type}")


def _txt(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")  # common for Windows Notepad files


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise TextExtractionError("The PDF is password-protected.")
        except TextExtractionError:
            raise
        except Exception as exc:
            raise TextExtractionError("The PDF is encrypted and cannot be read.") from exc

    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            logger.warning("Skipping unreadable PDF page %d", number)
    return "\n\n".join(pages)


def _docx(data: bytes) -> str:
    from docx import Document
    from docx.table import Table

    doc = Document(io.BytesIO(data))
    parts = []
    for block in doc.iter_inner_content():  # paragraphs and tables, in document order
        if isinstance(block, Table):
            for row in block.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        else:
            parts.append(block.text)
    return "\n".join(parts)
