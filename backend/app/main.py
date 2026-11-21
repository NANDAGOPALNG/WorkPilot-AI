import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import agent_tools, agora, documents, generated_documents, knowledge, tickets
from app.core.config import ConfigError
from app.core.database import get_supabase

logger = logging.getLogger("workpilot")


def _configure_app_logging() -> None:
    """Make the app's own INFO logs (workpilot.*) visible.

    uvicorn only configures its own loggers, so without this every logger.info() in the app is dropped and only
    warnings appear. No handler is added when the host process (or a test runner) already set logging up.
    """
    app_logger = logging.getLogger("workpilot")
    if app_logger.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)


_configure_app_logging()

app = FastAPI(
    title="WorkPilot AI",
    description="Voice-first enterprise AI assistant",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(knowledge.router)
app.include_router(tickets.router)
app.include_router(generated_documents.router)
app.include_router(agent_tools.router)  # POST tool routes need X-WorkPilot-Tool-Secret when AGORA_TOOLS_SHARED_SECRET is set
app.include_router(agora.router)  # NOTE: unauthenticated demo API; protect before any public deployment


@app.get("/health")
def health(check_db: bool = False):
    """Liveness check. Add ?check_db=true to also verify the Supabase connection."""
    body = {"status": "healthy", "service": "workpilot-api"}
    if not check_db:
        return body

    try:
        # Cheap query: proves URL + key work and that migration 001 has been applied.
        get_supabase().table("documents").select("id").limit(1).execute()
        body["database"] = "ok"
        return body
    except ConfigError as exc:
        logger.error("Supabase not configured: %s", exc)
        body.update(status="degraded", database="not_configured")
    except Exception:
        logger.exception("Supabase health check failed")
        body.update(status="degraded", database="error")
    return JSONResponse(body, status_code=503)

@app.get("/")
async def root():
    return {
        "message": "Welcome to WorkPilot AI API"
    }