import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import agent_tools, agora, documents, generated_documents, knowledge, tickets
from app.core.config import ConfigError
from app.core.database import get_supabase

logger = logging.getLogger("workpilot")

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
app.include_router(agent_tools.router)  # NOTE: unauthenticated; protect before any public deployment
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