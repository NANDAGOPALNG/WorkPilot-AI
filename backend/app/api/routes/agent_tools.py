"""Unified agent tool layer: backend capabilities exposed as callable tools for a voice agent.

Every tool endpoint answers with one envelope:
    success: {"success": true,  "tool": "<name>", "data": {...}}
    failure: {"success": false, "tool": "<name>", "error": {"code": "...", "message": "..."}}

The tools only call the existing services (rag_service, ticket_service, documentation_service);
no embedding, retrieval, LLM or database logic is duplicated here.

SECURITY: the four POST tool routes require the X-WorkPilot-Tool-Secret header whenever
AGORA_TOOLS_SHARED_SECRET is set (see app/api/dependencies.py). With the secret unset they stay open for plain
local development, so ALWAYS set it before exposing the backend through a public URL. `GET /tools` (the
catalogue of definitions) is intentionally open. This is not user authentication: restrict CORS/network access
and add real auth before a production deployment.
"""
import logging
from typing import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.dependencies import require_agora_tool_auth
from app.core.config import ConfigError
from app.schemas.agent import (
    TOOL_DEFINITIONS,
    CreateTicketInput,
    GenerateDocumentInput,
    GetTicketStatusInput,
    SearchKnowledgeInput,
    ToolFailure,
    ToolSuccess,
)
from app.services import documentation_service, rag_service, ticket_service
from app.services.documentation_service import GeneratedDocumentError
from app.services.llm_service import LLMError
from app.services.retrieval_service import RetrievalError
from app.services.ticket_service import TicketError

logger = logging.getLogger("workpilot.agent_tools")

EXCERPT_CHARS = 300  # keep tool output short enough for a voice agent's context


def _success(tool: str, data: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(ToolSuccess(tool=tool, data=jsonable_encoder(data)).model_dump(), status_code=status_code)


def _failure(tool: str, status_code: int, code: str, message: str) -> JSONResponse:
    body = ToolFailure(tool=tool, error={"code": code, "message": message})
    return JSONResponse(body.model_dump(), status_code=status_code)


def _code_for(status_code: int) -> str:
    if status_code == 404:
        return "not_found"
    if status_code in (400, 422):
        return "validation_error"
    if status_code == 502:
        return "upstream_error"
    return "service_error"


class AgentToolRoute(APIRoute):
    """Turns FastAPI's request-validation errors (bad/missing/unknown fields) into the tool envelope."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()
        tool = self.path.rsplit("/", 1)[-1]

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError as exc:
                # Only field names and reasons are reported, never the submitted values.
                problems = "; ".join(
                    f"{'.'.join(str(p) for p in err['loc'] if p != 'body') or 'body'}: {err['msg']}"
                    for err in exc.errors()
                )
                return _failure(tool, 422, "validation_error", f"Invalid input - {problems}")

        return handler


router = APIRouter(prefix="/api/agent", tags=["agent-tools"], route_class=AgentToolRoute)
TOOL_AUTH = [Depends(require_agora_tool_auth)]  # applied per POST route; the read-only catalogue stays open


def _run(tool: str, fn: Callable[[], JSONResponse]) -> JSONResponse:
    """Run a tool body and translate service errors into the failure envelope (never leaks internals)."""
    try:
        return fn()
    except (TicketError, GeneratedDocumentError, RetrievalError) as exc:
        return _failure(tool, exc.status_code, _code_for(exc.status_code), str(exc))
    except LLMError as exc:
        return _failure(tool, 502, "upstream_error", str(exc))
    except ValueError as exc:
        return _failure(tool, 422, "validation_error", str(exc))
    except ConfigError as exc:
        logger.error("Configuration error in %s: %s", tool, exc)  # details stay in the server log
        return _failure(tool, 503, "not_configured", "Server is not configured correctly (see server logs).")
    except Exception:
        logger.exception("Unexpected error in tool %s", tool)
        return _failure(tool, 500, "service_error", "Unexpected server error.")


def _ticket_view(ticket: dict) -> dict:
    keys = ("id", "ticket_number", "title", "description", "category", "priority", "status", "created_at", "updated_at")
    return {k: ticket.get(k) for k in keys}


# ----------------------------------------------------------------------------- catalogue
@router.get("/tools")
def list_tools():
    """Provider-independent tool definitions (name, description, JSON-Schema parameters)."""
    return {"tools": TOOL_DEFINITIONS}


# ----------------------------------------------------------------------------- search_knowledge
# Plain `def` routes run in FastAPI's threadpool, so the blocking Supabase/Gemini calls are fine.
@router.post("/tools/search_knowledge", dependencies=TOOL_AUTH)
def search_knowledge(body: SearchKnowledgeInput):
    tool = "search_knowledge"

    def run():
        result = rag_service.answer_question(body.question)
        sources = [
            {
                "ref": s["ref"],
                "document_id": s["document_id"],
                "filename": s["filename"],
                "chunk_index": s["chunk_index"],
                "similarity": s["similarity"],
                "cited": s["cited"],  # true only if the answer text actually references this source
                "excerpt": s["content"][:EXCERPT_CHARS],
            }
            for s in result["sources"]
        ]
        return _success(tool, {
            "question": result["question"],
            "found": bool(sources),  # false = nothing relevant in the documents; the answer is the standard no-answer text
            "answer": result["answer"],
            "citations": [s["ref"] for s in sources if s["cited"]],
            "sources": sources,
            "metadata": result["metadata"],
        })

    return _run(tool, run)


# ----------------------------------------------------------------------------- create_ticket
@router.post("/tools/create_ticket", dependencies=TOOL_AUTH)
def create_ticket(body: CreateTicketInput):
    """Two-step: without `confirmed` this only previews (nothing is written); with confirmed=true it creates."""
    tool = "create_ticket"

    def run():
        proposed = body.model_dump(exclude={"confirmed"})
        if not body.confirmed:
            return _success(tool, {
                "created": False,
                "requires_confirmation": True,
                "proposed_ticket": proposed,
                "message": (
                    "No ticket has been created yet. Read these details back to the user and ask them to confirm. "
                    "Only after they confirm, call create_ticket again with the same details and confirmed=true."
                ),
            })
        ticket, created = ticket_service.create_ticket(proposed)  # id / ticket_number / status come from the database
        if created:
            return _success(tool, {
                "created": True, "duplicate": False, "ticket": _ticket_view(ticket),
                "message": f"Ticket {ticket['ticket_number']} was created.",
            }, 201)
        return _success(tool, {
            "created": False, "duplicate": True, "ticket": _ticket_view(ticket),
            "message": f"An identical ticket ({ticket['ticket_number']}) was created moments ago, so no new ticket was made.",
        })

    return _run(tool, run)


# ----------------------------------------------------------------------------- get_ticket_status
@router.post("/tools/get_ticket_status", dependencies=TOOL_AUTH)
def get_ticket_status(body: GetTicketStatusInput):
    tool = "get_ticket_status"
    return _run(tool, lambda: _success(tool, {"ticket": _ticket_view(ticket_service.get_ticket(body.ticket_id_or_number))}))


# ----------------------------------------------------------------------------- generate_document
@router.post("/tools/generate_document", dependencies=TOOL_AUTH)
def generate_document(body: GenerateDocumentInput):
    tool = "generate_document"

    def run():
        doc = documentation_service.generate_document(body.model_dump())
        return _success(tool, {
            "saved": True,  # only reached after the database confirmed the insert
            "document_id": doc["id"],
            "title": doc["title"],
            "document_type": doc["document_type"],
            "related_ticket_id": doc.get("related_ticket_id"),
            "created_at": doc["created_at"],
            "content": doc["content"],
        }, 201)

    return _run(tool, run)
