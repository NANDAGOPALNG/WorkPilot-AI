import logging
import math
import time
from functools import lru_cache

from app.core.config import ConfigError, get_settings

logger = logging.getLogger("workpilot.embeddings")

BATCH_SIZE = 50
MAX_ATTEMPTS = 3
RETRY_STATUS_CODES = {429, 500, 503}

DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"  # for chunks being stored
QUERY_TASK = "RETRIEVAL_QUERY"        # for user questions (used by the later retrieval step)


class EmbeddingError(RuntimeError):
    pass


def check_configured() -> None:
    if not get_settings().gemini_api_key:
        raise ConfigError("GEMINI_API_KEY is not set in backend/.env")


@lru_cache
def _get_client():
    check_configured()
    from google import genai  # google-genai SDK

    return genai.Client(api_key=get_settings().gemini_api_key)


def _build_config(task_type: str, dimension: int):
    from google.genai import types

    return types.EmbedContentConfig(task_type=task_type, output_dimensionality=dimension)


def _normalize(vector: list[float]) -> list[float]:
    # Gemini only returns unit-length vectors at 3072 dims; normalise the truncated ones.
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def embed_texts(
    texts: list[str],
    task_type: str = DOCUMENT_TASK,
    *,
    client=None,
    model: str | None = None,
    dimension: int | None = None,
) -> list[list[float]]:
    """Embed texts in batches. Returns one normalised vector per text, each of `dimension` floats."""
    if not texts:
        return []
    if any(not isinstance(t, str) or not t.strip() for t in texts):
        raise EmbeddingError("Cannot embed empty text.")

    settings = get_settings() if (model is None or dimension is None) else None
    model = model or settings.embedding_model
    dimension = dimension or settings.embedding_dimension
    client = client or _get_client()
    config = _build_config(task_type, dimension)

    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        response = _call_with_retry(client, model, batch, config)
        embeddings = getattr(response, "embeddings", None) or []
        if len(embeddings) != len(batch):
            raise EmbeddingError("Embedding API returned an unexpected number of vectors.")
        for emb in embeddings:
            values = list(emb.values)
            if len(values) != dimension:
                raise EmbeddingError(
                    f"Embedding has {len(values)} dimensions, expected {dimension}."
                )
            vectors.append(_normalize(values))
    return vectors


def embed_text(text: str, task_type: str = DOCUMENT_TASK, **kwargs) -> list[float]:
    return embed_texts([text], task_type, **kwargs)[0]


def _call_with_retry(client, model, batch, config):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return client.models.embed_content(model=model, contents=batch, config=config)
        except Exception as exc:
            code = getattr(exc, "code", None)
            if attempt < MAX_ATTEMPTS and code in RETRY_STATUS_CODES:
                delay = 2 ** attempt
                logger.warning("Embedding call failed (code %s), retrying in %ss", code, delay)
                time.sleep(delay)
                continue
            # Log only the exception type/code, never request details.
            logger.error("Embedding call failed: %s (code %s)", type(exc).__name__, code)
            raise EmbeddingError("Embedding request to Gemini failed.") from None


get_client = _get_client  # shared Gemini client, also used by llm_service
