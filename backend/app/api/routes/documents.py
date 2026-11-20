import logging
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.core.config import ConfigError
from app.services import document_service
from app.services.document_service import DocumentError
from app.utils.file_validation import MAX_FILE_SIZE, FileValidationError

logger = logging.getLogger("workpilot.documents")
router = APIRouter(prefix="/api/documents", tags=["documents"])


def _error(status_code: int, message: str, document_id: str | None = None) -> HTTPException:
    return HTTPException(status_code, detail={"message": message, "document_id": document_id})


# Plain `def` routes: FastAPI runs them in a threadpool, so blocking Supabase/Gemini calls are fine.
@router.post("/upload", status_code=201)
def upload_document(file: UploadFile = File(...)):
    data = file.file.read(MAX_FILE_SIZE + 1)  # never read more than limit + 1 byte into memory
    try:
        return document_service.ingest_document(file.filename, file.content_type, data)
    except FileValidationError as exc:
        raise _error(exc.status_code, exc.message) from None
    except ConfigError as exc:
        logger.error("Configuration error during upload: %s", exc)
        raise _error(503, "Server is not configured correctly (see server logs).") from None
    except DocumentError as exc:
        raise _error(exc.status_code, str(exc), exc.document_id) from None


@router.get("")
def list_documents(limit: int = Query(100, ge=1, le=500)):
    try:
        documents = document_service.list_documents(limit=limit)
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise _error(503, "Server is not configured correctly (see server logs).") from None
    except DocumentError as exc:
        raise _error(exc.status_code, str(exc)) from None
    return {"documents": documents, "count": len(documents)}


@router.delete("/{document_id}")
def delete_document(document_id: UUID):
    try:
        document_service.delete_document(str(document_id))
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise _error(503, "Server is not configured correctly (see server logs).") from None
    except DocumentError as exc:
        raise _error(exc.status_code, str(exc), str(document_id)) from None
    return {"deleted": True, "id": str(document_id)}
