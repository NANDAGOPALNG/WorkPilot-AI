"""Voice session endpoints (Agora Conversational AI).

MVP/DEMO ONLY: these routes are NOT authenticated. Anyone who can reach the API can start agents
(which incur Agora/LLM/TTS costs) and stop any agent whose id they know. Add authentication and
rate limiting, and restrict CORS, before any public deployment.
"""
import logging

from fastapi import APIRouter, HTTPException, Path

from app.core.config import ConfigError
from app.integrations.agora_client import AgoraError
from app.schemas.agora import SESSION_ID_PATTERN, StartSessionResponse, StopSessionResponse
from app.services import agora_session_service

logger = logging.getLogger("workpilot.agora")
router = APIRouter(prefix="/api/agora", tags=["agora"])


def _call(fn, *args, **kwargs):
    """Run a session-service function and translate its errors into clean HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except AgoraError as exc:
        raise HTTPException(exc.status_code, detail={"message": str(exc)}) from None
    except ConfigError as exc:
        logger.error("Agora configuration error: %s", exc)  # names the missing variables, never values
        raise HTTPException(503, detail={"message": "Voice sessions are not configured on the server (see server logs)."}) from None
    except ValueError as exc:
        raise HTTPException(422, detail={"message": str(exc)}) from None
    except Exception:
        logger.exception("Unexpected error in Agora session handling")
        raise HTTPException(500, detail={"message": "Unexpected server error."}) from None


# Plain `def` routes run in FastAPI's threadpool, so the blocking HTTP call to Agora is fine.
@router.post("/sessions", response_model=StartSessionResponse, status_code=201)
def start_session():
    """Start a voice agent in a new channel and return what the frontend needs to join it."""
    return _call(agora_session_service.start_session)


@router.post("/sessions/{session_id}/stop", response_model=StopSessionResponse)
def stop_session(session_id: str = Path(..., pattern=SESSION_ID_PATTERN)):
    """Stop a running agent. Reports "stopped" only after Agora confirms."""
    return _call(agora_session_service.stop_session, session_id)
