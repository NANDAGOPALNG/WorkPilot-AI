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
        extra="ignore",         # unknown vars in .env are ignored
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

    # Agora Conversational AI (optional: only needed for /api/agora/* voice sessions; backend only, never the frontend)
    agora_app_id: str | None = None
    agora_app_certificate: str | None = None   # secret: signs RTC tokens
    agora_customer_id: str | None = None       # secret: Agora RESTful API key (Console -> Developer Toolkit)
    agora_customer_secret: str | None = None   # secret
    agora_api_base_url: str = "https://api.agora.io/api/conversational-ai-agent/v2"
    agora_agent_uid: int = Field(default=1000, ge=1, le=2_000_000_000)          # the agent's RTC uid
    agora_token_ttl_seconds: int = Field(default=3600, ge=60, le=86400)         # RTC token lifetime (Agora max 24h)
    agora_idle_timeout_seconds: int = Field(default=120, ge=1, le=3600)         # agent leaves this long after the user does
    agora_http_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    agora_asr_language: str = "en-US"
    agora_llm_model: str = "gpt-4o-mini"
    agora_tts_voice_id: str = "English_captivating_female1"
    agora_greeting: str = "Hi, I'm WorkPilot. How can I help you today?"

    # Agora custom tools: Agora's cloud calls the four agent-tool routes of THIS backend over public HTTPS.
    # Both are validated when a voice session starts (app/services/agora_tools.py), not here, so a mistake in
    # them can never stop the rest of the backend from loading its settings.
    agora_tools_base_url: str | None = None        # public https:// origin of this backend, e.g. a tunnel or deployed URL
    agora_tools_shared_secret: str | None = None   # secret: sent by Agora in a header, checked on every tool call

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
