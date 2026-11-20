import io
import types
import zipfile

import pytest

from app.services import document_service as svc
from app.services.embedding_service import EmbeddingError
from app.utils.chunking import chunk_text
from app.utils.file_validation import MAX_FILE_SIZE, FileValidationError, validate_upload
from app.utils.text_extraction import TextExtractionError, extract_text

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
LONG_TEXT = "\n\n".join(f"Paragraph {i}. " + "Sentence about topic. " * 20 for i in range(30))


def make_docx(paragraphs=("Hello from a Word document.",), table=None) -> bytes:
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    if table:
        t = doc.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                t.cell(r, c).text = value
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_blank_pdf() -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def make_text_pdf(text="Hello PDF world") -> bytes:
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return out


# ---------------------------------------------------------------- validation
def test_validate_accepts_supported_types():
    assert validate_upload("a.txt", "text/plain", b"hello") == "txt"
    assert validate_upload("A.PDF", "application/pdf", make_blank_pdf()) == "pdf"
    assert validate_upload("a.docx", DOCX_MIME, make_docx()) == "docx"
    assert validate_upload("a.txt", "application/octet-stream", b"hello") == "txt"  # generic MIME ok


def test_validate_rejects_bad_extension_size_and_empty():
    with pytest.raises(FileValidationError) as e:
        validate_upload("evil.exe", "application/octet-stream", b"MZ")
    assert e.value.status_code == 415
    with pytest.raises(FileValidationError) as e:
        validate_upload("a.txt", "text/plain", b"x" * (MAX_FILE_SIZE + 1))
    assert e.value.status_code == 413
    with pytest.raises(FileValidationError) as e:
        validate_upload("a.txt", "text/plain", b"")
    assert e.value.status_code == 400


def test_validate_does_not_trust_name_or_mime():
    with pytest.raises(FileValidationError):  # right name, wrong content
        validate_upload("a.pdf", "application/pdf", b"just text")
    with pytest.raises(FileValidationError):  # specific but mismatching MIME
        validate_upload("a.pdf", "image/png", make_blank_pdf())
    with pytest.raises(FileValidationError):  # zip that isn't a docx
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("x.txt", "hi")
        validate_upload("a.docx", DOCX_MIME, buf.getvalue())
    with pytest.raises(FileValidationError):  # binary posing as txt
        validate_upload("a.txt", "text/plain", b"abc\x00def")


# ------------------------------------------------------------------ chunking
def test_chunking_basics():
    assert chunk_text("") == [] and chunk_text("  \n\n ") == []
    assert chunk_text("short text") == ["short text"]


def test_chunking_size_overlap_and_no_empty_chunks():
    chunks = chunk_text(LONG_TEXT, chunk_size=300, overlap=60)
    assert len(chunks) > 3
    assert all(c.strip() and len(c) <= 300 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt[:30].strip() in prev  # next chunk starts with the tail of the previous one


def test_chunking_handles_huge_unbroken_text():
    chunks = chunk_text("x" * 5000, chunk_size=300, overlap=50)
    assert all(0 < len(c) <= 300 for c in chunks)


# ---------------------------------------------------------------- extraction
def test_extract_txt_utf8_and_cp1252():
    assert extract_text("héllo\r\n\r\n\r\n\r\nworld".encode("utf-8"), "txt") == "héllo\n\nworld"
    assert "café" in extract_text("café".encode("cp1252"), "txt")


def test_extract_docx_paragraphs_and_tables():
    text = extract_text(make_docx(("Intro paragraph",), table=[["Name", "Role"], ["Asha", "SRE"]]), "docx")
    assert "Intro paragraph" in text and "Asha | SRE" in text


def test_extract_pdf_text_blank_and_garbage():
    assert "Hello PDF world" in extract_text(make_text_pdf(), "pdf")
    assert extract_text(make_blank_pdf(), "pdf") == ""
    with pytest.raises(TextExtractionError):
        extract_text(b"%PDF-1.4 not really a pdf", "pdf")


# ------------------------------------------------- ingestion error handling
class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.payload, self.filters = db, table, None, None, {}

    def insert(self, payload): self.op, self.payload = "insert", payload; return self
    def update(self, payload): self.op, self.payload = "update", payload; return self
    def delete(self): self.op = "delete"; return self
    def select(self, *_): self.op = "select"; return self
    def order(self, *_, **__): return self
    def limit(self, *_): return self
    def eq(self, key, value): self.filters[key] = value; return self

    def execute(self):
        if f"{self.op}:{self.table}" in self.db.fail:
            if self.db.fail_after.get(f"{self.op}:{self.table}", 0) > 0:
                self.db.fail_after[f"{self.op}:{self.table}"] -= 1
            else:
                raise RuntimeError("boom")
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "insert":
            new = self.payload if isinstance(self.payload, list) else [self.payload]
            rows.extend({**r, "created_at": "2026-01-01T00:00:00Z"} for r in new)
            return types.SimpleNamespace(data=rows[-len(new):])
        match = [r for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
        if self.op == "update":
            for r in match:
                r.update(self.payload)
        elif self.op == "delete":
            self.db.tables[self.table] = [r for r in rows if r not in match]
        return types.SimpleNamespace(data=match)


class FakeStorage:
    def __init__(self, db): self.db = db
    def from_(self, bucket): return self
    def upload(self, path, file, file_options=None):
        if "upload" in self.db.fail: raise RuntimeError("boom")
        self.db.objects[path] = file
    def remove(self, paths):
        if "remove" in self.db.fail: raise RuntimeError("boom")
        for p in paths: self.db.objects.pop(p, None)


class FakeDB:
    def __init__(self, fail=(), fail_after=None):
        self.tables, self.objects = {}, {}
        self.fail, self.fail_after = set(fail), fail_after or {}
        self.storage = FakeStorage(self)
    def table(self, name): return FakeQuery(self, name)


def fake_embed(chunks): return [[0.1] * 768 for _ in chunks]


def ingest(db, data=None, embed=fake_embed, name="notes.txt"):
    data = LONG_TEXT.encode() if data is None else data
    return svc.ingest_document(name, "text/plain", data, db=db, bucket="b", embed_fn=embed)


def test_ingest_success():
    db = FakeDB()
    result = ingest(db)
    assert result["status"] == "ready" and result["chunk_count"] == len(db.tables["document_chunks"])
    assert [c["chunk_index"] for c in db.tables["document_chunks"]] == list(range(result["chunk_count"]))
    assert db.tables["documents"][0]["status"] == "ready"
    assert list(db.objects) == [f"documents/{result['id']}.txt"]


def assert_failed_cleanly(db, exc, status):
    assert exc.value.status_code == status and exc.value.document_id
    assert db.tables["documents"][0]["status"] == "failed"
    assert not db.tables.get("document_chunks")  # no partial chunks left behind
    assert not db.objects                          # uploaded file removed


def test_ingest_no_extractable_text_marks_failed():
    db = FakeDB()
    with pytest.raises(svc.DocumentError) as exc:
        ingest(db, data=b"   \n\n  ")
    assert_failed_cleanly(db, exc, 422)


def test_ingest_embedding_failure_marks_failed():
    def broken(_): raise EmbeddingError("api down")
    db = FakeDB()
    with pytest.raises(svc.DocumentError) as exc:
        ingest(db, embed=broken)
    assert_failed_cleanly(db, exc, 502)


def test_ingest_wrong_embedding_count_marks_failed():
    db = FakeDB()
    with pytest.raises(svc.DocumentError) as exc:
        ingest(db, embed=lambda chunks: fake_embed(chunks)[:-1])
    assert_failed_cleanly(db, exc, 502)


def test_ingest_partial_chunk_insert_failure_removes_chunks(monkeypatch):
    monkeypatch.setattr(svc, "INSERT_BATCH", 1)
    db = FakeDB(fail={"insert:document_chunks"}, fail_after={"insert:document_chunks": 1})
    with pytest.raises(svc.DocumentError) as exc:  # first batch succeeds, second fails
        ingest(db)
    assert_failed_cleanly(db, exc, 500)


def test_ingest_storage_failure_creates_no_record():
    db = FakeDB(fail={"upload"})
    with pytest.raises(svc.DocumentError) as exc:
        ingest(db)
    assert exc.value.status_code == 502 and not db.tables.get("documents")


def test_ingest_invalid_file_stores_nothing():
    db = FakeDB()
    with pytest.raises(FileValidationError):
        svc.ingest_document("x.exe", "application/octet-stream", b"MZ", db=db, bucket="b", embed_fn=fake_embed)
    assert not db.objects and not db.tables


def test_delete_document_and_failure_paths():
    db = FakeDB()
    doc_id = ingest(db)["id"]
    db.fail = {"remove"}
    with pytest.raises(svc.DocumentError):  # storage failure: record kept so delete can be retried
        svc.delete_document(doc_id, db=db, bucket="b")
    assert db.tables["documents"]
    db.fail = set()
    svc.delete_document(doc_id, db=db, bucket="b")
    assert not db.tables["documents"] and not db.objects
    with pytest.raises(svc.DocumentError) as exc:
        svc.delete_document(doc_id, db=db, bucket="b")
    assert exc.value.status_code == 404
