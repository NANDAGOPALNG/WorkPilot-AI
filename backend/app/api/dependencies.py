"""Shared FastAPI dependencies."""
import logging

from fastapi import Header, HTTPException

from app.core.config import ConfigError, get_settings
from app.core.security import TOOL_SECRET_HEADER, secrets_match

logger = logging.getLogger("workpilot.auth")


def _configured_secret() -> str | None:
    """The shared secret from AGORA_TOOLS_SHARED_SECRET, or None when it is not set.

    Settings that cannot be loaded at all (e.g. no Supabase configuration) count as "not set": in that state
    every tool fails on its own anyway, and it keeps the tool routes usable in unit tests without a backend/.env.
    """
    try:
        secret = get_settings().agora_tools_shared_secret
    except ConfigError:
        return None
    return (secret or "").strip() or None


def require_agora_tool_auth(provided: str | None = Header(default=None, alias=TOOL_SECRET_HEADER)) -> None:
    """Guard for the agent tool routes that Agora's cloud calls.

    - AGORA_TOOLS_SHARED_SECRET set  -> the request must carry the same value in the X-WorkPilot-Tool-Secret
      header, otherwise 401 and the tool never runs. (Voice sessions cannot start without the secret, so a
      working voice setup always has it set.)
    - AGORA_TOOLS_SHARED_SECRET unset -> open. This keeps curl / Swagger / the existing tests usable in plain
      local development. Never expose the backend through a public URL without setting the secret.

    Neither the expected nor the supplied value is ever logged or returned.
    """
    expected = _configured_secret()
    if expected is None:
        return
    if not secrets_match(provided, expected):
        logger.warning("Rejected an agent tool request: missing or invalid %s header", TOOL_SECRET_HEADER)
        raise HTTPException(401, detail={"code": "unauthorized", "message": "Missing or invalid tool credentials."})
