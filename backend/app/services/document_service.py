import logging
import uuid

from app.services import embedding_service
from app.services.embedding_service import EmbeddingError
from app.utils.chunking import chunk_text
from app.utils.file_validation import CANONICAL_MIME, clean_filename, validate_upload
from app.utils.text_extraction import TextExtractionError, extract_text

logger = logging.getLogger("workpilot.documents")

MIN_TEXT_CHARS = 50       # below this we treat the file as having no meaningful text
MAX_CHUNKS = 500          # keeps one upload request within a sane time / API quota
INSERT_BATCH = 50         # chunk rows per insert call
LIST_COLUMNS = "id,filename,file_type,file_size,status,created_at"


class DocumentError(Exception):
    def __init__(self, message: str, status_code: int = 500, document_id: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.document_id = document_id


def _resolve(db, bucket):
    if db is None:
        from app.core.database import get_supabase

        db = get_supabase()
    if bucket is None:
        from app.core.config import get_settings

        bucket = get_settings().supabase_storage_bucket
    return db, bucket


def ingest_document(filename, content_type, data: bytes, *, db=None, bucket=None, embed_fn=None) -> dict:
    """Validate -> store -> extract -> chunk -> embed -> save chunks -> mark ready.

    Raises FileValidationError (nothing stored) or DocumentError. If DocumentError carries a
    document_id, the document row exists with status 'failed' (chunks and file removed).
    """
    file_type = validate_upload(filename, content_type, data)
    display_name = clean_filename(filename)
    db, bucket = _resolve(db, bucket)
    if embed_fn is None:
        embedding_service.check_configured()  # fail before storing anything
        embed_fn = embedding_service.embed_texts

    doc_id = str(uuid.uuid4())
    storage_path = f"documents/{doc_id}.{file_type}"  # unique, ASCII-safe key
    storage = db.storage.from_(bucket)

    try:
        storage.upload(
            path=storage_path,
            file=data,
            file_options={"content-type": CANONICAL_MIME[file_type], "upsert": "false"},
        )
    except Exception:
        logger.exception("Storage upload failed")
        raise DocumentError("Could not store the file.", 502) from None

    try:
        inserted = db.table("documents").insert({
            "id": doc_id,
            "filename": display_name,
            "file_type": file_type,
            "storage_path": storage_path,
            "file_size": len(data),
            "status": "processing",
        }).execute()
    except Exception:
        logger.exception("Could not insert document record")
        _remove_object(storage, storage_path)
        raise DocumentError("Could not create the document record.", 500) from None

    try:
        chunk_count = _process(db, doc_id, data, file_type, embed_fn)
        db.table("documents").update({"status": "ready"}).eq("id", doc_id).execute()
    except Exception as exc:
        if isinstance(exc, DocumentError):
            error = exc
        else:
            logger.exception("Unexpected error processing document %s", doc_id)
            error = DocumentError("Unexpected error while processing the document.", 500)
        error.document_id = doc_id
        _mark_failed(db, storage, doc_id, storage_path)
        raise error from None

    rows = getattr(inserted, "data", None) or [{}]
    return {
        "id": doc_id,
        "filename": display_name,
        "file_type": file_type,
        "file_size": len(data),
        "status": "ready",
        "chunk_count": chunk_count,
        "created_at": rows[0].get("created_at"),
    }


def _process(db, doc_id, data, file_type, embed_fn) -> int:
    try:
        text = extract_text(data, file_type)
    except TextExtractionError as exc:
        raise DocumentError(str(exc), 422) from None
    if len(text) < MIN_TEXT_CHARS:
        raise DocumentError(
            "No meaningful text could be extracted (scanned/image-only files are not supported).",
            422,
        )

    chunks = chunk_text(text)
    if not chunks:
        raise DocumentError("No usable text chunks were produced.", 422)
    if len(chunks) > MAX_CHUNKS:
        raise DocumentError(
            f"Document is too large to index ({len(chunks)} chunks, limit {MAX_CHUNKS}).", 422
        )

    try:
        embeddings = embed_fn(chunks)
    except EmbeddingError as exc:
        raise DocumentError(f"Embedding failed: {exc}", 502) from None
    if len(embeddings) != len(chunks):
        raise DocumentError("Embedding count did not match chunk count.", 502)

    rows = [
        {"document_id": doc_id, "chunk_index": i, "content": content, "embedding": emb}
        for i, (content, emb) in enumerate(zip(chunks, embeddings))
    ]
    try:
        for start in range(0, len(rows), INSERT_BATCH):
            db.table("document_chunks").insert(rows[start:start + INSERT_BATCH]).execute()
    except Exception:
        logger.exception("Could not store chunks for document %s", doc_id)
        raise DocumentError("Could not store document chunks.", 500) from None
    return len(rows)


def _mark_failed(db, storage, doc_id, storage_path) -> None:
    """Best effort: drop partial chunks, flag the row failed, remove our own uploaded file."""
    for description, action in (
        ("delete chunks", lambda: db.table("document_chunks").delete().eq("document_id", doc_id).execute()),
        ("mark failed", lambda: db.table("documents").update({"status": "failed"}).eq("id", doc_id).execute()),
    ):
        try:
            action()
        except Exception:
            logger.exception("Cleanup step '%s' failed for document %s", description, doc_id)
    _remove_object(storage, storage_path)


def _remove_object(storage, storage_path) -> None:
    try:
        storage.remove([storage_path])
    except Exception:
        logger.exception("Could not remove storage object %s", storage_path)


def list_documents(*, db=None, limit: int = 100) -> list[dict]:
    db, _ = _resolve(db, "unused")
    try:
        response = (
            db.table("documents").select(LIST_COLUMNS).order("created_at", desc=True).limit(limit).execute()
        )
    except Exception:
        logger.exception("Could not list documents")
        raise DocumentError("Could not list documents.", 500) from None
    return response.data or []


def delete_document(document_id: str, *, db=None, bucket=None) -> None:
    """Delete the stored file first, then the row (chunks cascade).

    If the file removal fails, the row is kept so the delete can simply be retried.
    """
    db, bucket = _resolve(db, bucket)
    try:
        found = db.table("documents").select("id,storage_path").eq("id", document_id).execute().data
    except Exception:
        logger.exception("Could not look up document %s", document_id)
        raise DocumentError("Could not look up the document.", 500) from None
    if not found:
        raise DocumentError("Document not found.", 404)

    try:
        db.storage.from_(bucket).remove([found[0]["storage_path"]])  # missing object is not an error
    except Exception:
        logger.exception("Could not remove file for document %s", document_id)
        raise DocumentError("Could not delete the stored file; nothing was deleted. Try again.", 502) from None

    try:
        db.table("documents").delete().eq("id", document_id).execute()
    except Exception:
        logger.exception("Could not delete document row %s", document_id)
        raise DocumentError(
            "The stored file was deleted but the record could not be removed. Retry the delete.", 500
        ) from None
