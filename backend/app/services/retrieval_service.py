import logging

from app.core.config import get_settings
from app.services import embedding_service
from app.services.embedding_service import QUERY_TASK, EmbeddingError

logger = logging.getLogger("workpilot.retrieval")


class RetrievalError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def retrieve_chunks(question: str, *, top_k=None, threshold=None, db=None, embed_fn=None) -> list[dict]:
    """Embed the question and return the most similar chunks (best first).

    Defaults for top_k / threshold come from RETRIEVAL_TOP_K / RETRIEVAL_THRESHOLD.
    Each result: chunk_id, document_id, filename, chunk_index, content, similarity.
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("Question must not be empty.")

    if top_k is None or threshold is None:
        settings = get_settings()
        top_k = settings.retrieval_top_k if top_k is None else top_k
        threshold = settings.retrieval_threshold if threshold is None else threshold

    if embed_fn is None:
        embedding_service.check_configured()  # raises ConfigError if GEMINI_API_KEY is missing
        embed_fn = lambda text: embedding_service.embed_text(text, QUERY_TASK)  # noqa: E731
    if db is None:
        from app.core.database import get_supabase

        db = get_supabase()

    try:
        embedding = embed_fn(question)
    except EmbeddingError as exc:
        raise RetrievalError(f"Could not embed the question: {exc}", 502) from None

    try:
        response = db.rpc(
            "match_document_chunks",
            {"query_embedding": embedding, "match_count": top_k, "match_threshold": threshold},
        ).execute()
    except Exception:
        logger.exception("match_document_chunks RPC failed")
        raise RetrievalError("Document search failed.", 502) from None

    rows = [row for row in (response.data or []) if row.get("content")]
    # Diagnostics only: counts and the best score, never the question or document text.
    logger.info(
        "Retrieval: %d chunk(s) at or above threshold %.2f (top_k=%d, best similarity=%s)",
        len(rows), threshold, top_k,
        f"{max(float(r['similarity']) for r in rows):.3f}" if rows else "n/a",
    )

    return [
        {
            "chunk_id": str(row["chunk_id"]),
            "document_id": str(row["document_id"]),
            "filename": row.get("filename") or "unknown",
            "chunk_index": row.get("chunk_index"),
            "content": row["content"],
            "similarity": float(row["similarity"]),
        }
        for row in rows
    ]
