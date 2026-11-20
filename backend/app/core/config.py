from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env, resolved from this file so it works regardless of the working directory.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class ConfigError(RuntimeError):
    """Raised when required environment configuration is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # `SUPABASE_URL=` (blank) counts as missing
        extra="ignore",         # other vars in .env (Agora, LLM, ...) are for later steps
    )

    # Required
    supabase_url: str
    supabase_service_role_key: str

    # Optional (checked when ingestion/embedding actually runs)
    gemini_api_key: str | None = None

    # Optional, with defaults
    supabase_storage_bucket: str = "knowledge-documents"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimension: int = 768  # must match vector(768) in the SQL migrations
    frontend_url: str = "http://localhost:5173"

    # RAG question answering
    llm_model: str = "gemini-2.5-flash"  # any Gemini text model your key can use
    retrieval_top_k: int = Field(default=5, ge=1, le=20)
    retrieval_threshold: float = Field(default=0.5, ge=0.0, le=1.0)  # min cosine similarity

    @field_validator("supabase_url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("https://", "http://")):
            raise ValueError("must start with https:// (e.g. https://xxxx.supabase.co)")
        return v

    @field_validator("supabase_service_role_key")
    @classmethod
    def _strip_key(cls, v: str) -> str:
        return v.strip()


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        # Only report variable names and reasons, never the values.
        problems = "\n".join(
            f"  - {'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}"
            for err in exc.errors()
        )
        raise ConfigError(
            f"Invalid or missing environment configuration:\n{problems}\n"
            f"Copy backend/.env.example to backend/.env and fill in the values "
            f"(expected at {ENV_FILE})."
        ) from None
