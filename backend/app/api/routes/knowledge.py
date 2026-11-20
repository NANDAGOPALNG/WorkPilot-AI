import logging

from fastapi import APIRouter, HTTPException

from app.core.config import ConfigError
from app.schemas.knowledge import AskRequest, AskResponse
from app.services import rag_service
from app.services.llm_service import LLMError
from app.services.retrieval_service import RetrievalError

logger = logging.getLogger("workpilot.knowledge")
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _error(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code, detail={"message": message})


# Plain `def`: FastAPI runs it in a threadpool, so the blocking Supabase/Gemini calls are fine.
@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest):
    try:
        return rag_service.answer_question(body.question)
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise _error(503, "Server is not configured correctly (see server logs).") from None
    except RetrievalError as exc:
        raise _error(exc.status_code, str(exc)) from None
    except LLMError as exc:
        raise _error(502, str(exc)) from None
