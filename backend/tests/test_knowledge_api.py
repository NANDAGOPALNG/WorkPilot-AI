import pytest

pytest.importorskip("httpx")  # needed by FastAPI's TestClient: pip install httpx

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import knowledge
from app.core.config import ConfigError
from app.services.llm_service import LLMError
from app.services.retrieval_service import RetrievalError

app = FastAPI()
app.include_router(knowledge.router)
client = TestClient(app)

ANSWER = {
    "question": "q?", "answer": "Restart [1].", "metadata": {"chunks_retrieved": 1, "chunks_used": 1, "grounded": True},
    "sources": [{"ref": 1, "document_id": "d", "filename": "IT.pdf", "chunk_id": "c", "chunk_index": 0,
                 "similarity": 0.8, "content": "text", "cited": True}],
}


def ask(question="q?"):
    return client.post("/api/knowledge/ask", json={"question": question})


def test_empty_or_oversized_questions_are_rejected():
    assert ask("").status_code == 422
    assert ask("   ").status_code == 422
    assert ask("x" * 1001).status_code == 422
    assert client.post("/api/knowledge/ask", json={}).status_code == 422


def test_success_returns_answer_and_sources(monkeypatch):
    monkeypatch.setattr(knowledge.rag_service, "answer_question", lambda q: ANSWER)
    body = ask().json()
    assert ask().status_code == 200
    assert body["answer"] == "Restart [1]." and body["sources"][0]["filename"] == "IT.pdf"


def test_failures_map_to_http_errors(monkeypatch):
    def raises(exc):
        def fn(q): raise exc
        return fn

    monkeypatch.setattr(knowledge.rag_service, "answer_question", raises(RetrievalError("search failed", 502)))
    assert ask().status_code == 502
    monkeypatch.setattr(knowledge.rag_service, "answer_question", raises(LLMError("Gemini request failed.")))
    assert ask().status_code == 502
    monkeypatch.setattr(knowledge.rag_service, "answer_question", raises(ConfigError("GEMINI_API_KEY missing")))
    r = ask()
    assert r.status_code == 503 and "GEMINI_API_KEY" not in r.text
