import logging
import time

from app.core.config import get_settings
from app.services import embedding_service
from app.services.embedding_service import MAX_ATTEMPTS, RETRY_STATUS_CODES

logger = logging.getLogger("workpilot.llm")


class LLMError(RuntimeError):
    pass


def _build_config(system_instruction: str | None, temperature: float):
    from google.genai import types

    return types.GenerateContentConfig(system_instruction=system_instruction, temperature=temperature)


def generate_text(
    prompt: str,
    *,
    system_instruction: str | None = None,
    temperature: float = 0.2,
    client=None,
    model: str | None = None,
) -> str:
    """Generate text with Gemini (model from LLM_MODEL). Raises LLMError on failure."""
    if not prompt or not prompt.strip():
        raise LLMError("Prompt must not be empty.")
    client = client or embedding_service.get_client()  # raises ConfigError without GEMINI_API_KEY
    model = model or get_settings().llm_model
    config = _build_config(system_instruction, temperature)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            break
        except Exception as exc:
            code = getattr(exc, "code", None)
            if attempt < MAX_ATTEMPTS and code in RETRY_STATUS_CODES:
                logger.warning("Gemini call failed (code %s), retrying", code)
                time.sleep(2 ** attempt)
                continue
            # Log only the exception type/code, never request details or keys.
            logger.error("Gemini call failed: %s (code %s)", type(exc).__name__, code)
            raise LLMError("Gemini request failed.") from None

    text = getattr(response, "text", None)
    if not text or not text.strip():
        raise LLMError("Gemini returned an empty response.")
    return text.strip()
