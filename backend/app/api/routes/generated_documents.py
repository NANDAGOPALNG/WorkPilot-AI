import logging

from fastapi import APIRouter, HTTPException, Query

from app.core.config import ConfigError
from app.schemas.generated_document import (
    GeneratedDocumentCreate,
    GeneratedDocumentList,
    GeneratedDocumentOut,
)
from app.services import documentation_service
from app.services.documentation_service import GeneratedDocumentError
from app.services.llm_service import LLMError

logger = logging.getLogger("workpilot.documentation")
router = APIRouter(prefix="/api/generated-documents", tags=["generated-documents"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except GeneratedDocumentError as exc:
        raise HTTPException(exc.status_code, detail={"message": str(exc)}) from None
    except LLMError as exc:
        raise HTTPException(502, detail={"message": str(exc)}) from None
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise HTTPException(503, detail={"message": "Server is not configured correctly (see server logs)."}) from None


@router.post("", response_model=GeneratedDocumentOut, status_code=201)
def generate_document(body: GeneratedDocumentCreate):
    return _call(documentation_service.generate_document, body.model_dump())


@router.get("", response_model=GeneratedDocumentList)
def list_generated_documents(limit: int = Query(50, ge=1, le=200)):
    return _call(documentation_service.list_generated_documents, limit=limit)


@router.get("/{document_id}", response_model=GeneratedDocumentOut)
def get_generated_document(document_id: str):
    return _call(documentation_service.get_generated_document, document_id)
