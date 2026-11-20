import pytest

pytest.importorskip("httpx")  # needed by FastAPI's TestClient: pip install httpx
pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import agent_tools
from app.core.config import ConfigError
from app.schemas.agent import TOOL_DEFINITIONS
from app.services import llm_service, rag_service
from app.services.retrieval_service import RetrievalError
from fake_supabase import FakeDB

app = FastAPI()
app.include_router(agent_tools.router)
client = TestClient(app)

BASE = "/api/agent/tools"
UNKNOWN_UUID = "3f2b1c9e-8a7d-4c55-9a0e-0d6f1b2c3d4e"
LONG = "Gateway cert expired. " * 40  # > EXCERPT_CHARS


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr("app.core.database.get_supabase", lambda: db)
    return db


def call(tool, payload):
    return client.post(f"{BASE}/{tool}", json=payload)


def assert_success(r, tool, status=200):
    body = r.json()
    assert r.status_code == status, body
    assert set(body) == {"success", "tool", "data"} and body["success"] is True and body["tool"] == tool
    return body["data"]


def assert_failure(r, tool, status, code=None):
    body = r.json()
    assert r.status_code == status, body
    assert set(body) == {"success", "tool", "error"} and body["success"] is False and body["tool"] == tool
    assert body["error"]["message"]
    if code:
        assert body["error"]["code"] == code
    return body["error"]


# ----------------------------------------------------------------- search_knowledge
RAG_RESULT = {
    "question": "How do I reset my VPN?",
    "answer": "Restart the client [1].",
    "metadata": {"chunks_retrieved": 2, "chunks_used": 2, "grounded": True},
    "sources": [
        {"ref": 1, "document_id": "d1", "filename": "IT.pdf", "chunk_id": "c1", "chunk_index": 0,
         "similarity": 0.81, "content": LONG, "cited": True},
        {"ref": 2, "document_id": "d2", "filename": "HR.pdf", "chunk_id": "c2", "chunk_index": 3,
         "similarity": 0.55, "content": "other", "cited": False},
    ],
}


def test_search_knowledge_success(monkeypatch):
    seen = []
    monkeypatch.setattr(rag_service, "answer_question", lambda q: seen.append(q) or RAG_RESULT)
    data = assert_success(call("search_knowledge", {"question": "  How do I reset my VPN?  "}), "search_knowledge")
    assert seen == ["How do I reset my VPN?"]  # reuses the RAG service, input trimmed
    assert data["found"] is True and data["answer"] == "Restart the client [1]." and data["citations"] == [1]
    assert [s["filename"] for s in data["sources"]] == ["IT.pdf", "HR.pdf"]
    assert data["sources"][0]["cited"] is True and data["sources"][1]["cited"] is False
    assert len(data["sources"][0]["excerpt"]) == agent_tools.EXCERPT_CHARS
    assert "content" not in data["sources"][0] and "chunk_id" not in data["sources"][0]


def test_search_knowledge_no_documents_found(monkeypatch, fake_db):
    # Real RAG service with no retrieved chunks: nothing is generated and no citations are invented.
    monkeypatch.setattr("app.services.retrieval_service.retrieve_chunks", lambda q, top_k=None, threshold=None: [])
    def no_llm(*a, **k): raise AssertionError("LLM must not be called without context")
    monkeypatch.setattr(llm_service, "generate_text", no_llm)
    data = assert_success(call("search_knowledge", {"question": "What is the moon policy?"}), "search_knowledge")
    assert data["found"] is False and data["sources"] == [] and data["citations"] == []
    assert data["answer"] == rag_service.NO_ANSWER and data["metadata"]["grounded"] is False


def test_search_knowledge_strips_invented_citations(monkeypatch):
    monkeypatch.setattr("app.services.retrieval_service.retrieve_chunks", lambda q, top_k=None, threshold=None: [
        {"chunk_id": "c", "document_id": "d", "filename": "IT.pdf", "chunk_index": 0, "content": "text", "similarity": 0.9}])
    monkeypatch.setattr(llm_service, "generate_text", lambda p, system_instruction=None: "Yes [1][7].")
    data = assert_success(call("search_knowledge", {"question": "q?"}), "search_knowledge")
    assert "[7]" not in data["answer"] and data["citations"] == [1]


@pytest.mark.parametrize("exc, status, code", [
    (RetrievalError("Document search failed.", 502), 502, "upstream_error"),
    (llm_service.LLMError("Gemini request failed."), 502, "upstream_error"),
    (ConfigError("GEMINI_API_KEY=secret-value missing"), 503, "not_configured"),
    (RuntimeError("secret-value exploded"), 500, "service_error"),
])
def test_search_knowledge_failures(monkeypatch, exc, status, code):
    def boom(q): raise exc
    monkeypatch.setattr(rag_service, "answer_question", boom)
    r = call("search_knowledge", {"question": "q?"})
    assert_failure(r, "search_knowledge", status, code)
    assert "secret-value" not in r.text and "GEMINI_API_KEY" not in r.text


def test_search_knowledge_input_validation():
    for bad in ({}, {"question": ""}, {"question": "   "}, {"question": "x" * 1001}, {"question": 5},
                {"question": "q", "top_k": 99}):
        assert_failure(call("search_knowledge", bad), "search_knowledge", 422, "validation_error")


# ----------------------------------------------------------------- create_ticket
TICKET = {"title": "VPN down", "description": "Cannot connect since 10am", "category": "Network", "priority": "High"}


def test_create_ticket_without_confirmation_only_previews(fake_db):
    data = assert_success(call("create_ticket", TICKET), "create_ticket")
    assert data["created"] is False and data["requires_confirmation"] is True and "ticket" not in data
    assert data["proposed_ticket"] == {"title": "VPN down", "description": "Cannot connect since 10am",
                                       "category": "network", "priority": "high"}
    assert not fake_db.tables.get("tickets")  # nothing written
    assert not call("create_ticket", {**TICKET, "confirmed": False}).json()["data"]["created"]


def test_create_ticket_confirmed_returns_database_values(fake_db):
    data = assert_success(call("create_ticket", {**TICKET, "confirmed": True}), "create_ticket", 201)
    t = data["ticket"]
    assert data["created"] is True and data["duplicate"] is False
    assert t["ticket_number"] == "TKT-1001" and t["status"] == "open" and t["priority"] == "high"
    assert t["id"] == fake_db.tables["tickets"][0]["id"] and t["created_at"] and "TKT-1001" in data["message"]


def test_create_ticket_duplicate_is_not_created_twice(fake_db):
    first = call("create_ticket", {**TICKET, "confirmed": True}).json()["data"]["ticket"]
    r = call("create_ticket", {**TICKET, "confirmed": True})
    data = assert_success(r, "create_ticket", 200)
    assert data["created"] is False and data["duplicate"] is True and data["ticket"]["id"] == first["id"]
    assert len(fake_db.tables["tickets"]) == 1


def test_create_ticket_defaults():
    data = assert_success(call("create_ticket", {"title": "t", "description": "d"}), "create_ticket")
    assert data["proposed_ticket"]["category"] == "general" and data["proposed_ticket"]["priority"] == "medium"


@pytest.mark.parametrize("bad", [
    {},
    {"title": "", "description": "d"},
    {"title": "  ", "description": "d"},
    {"title": "t"},  # description required
    {"title": "t", "description": "   "},
    {"title": "x" * 201, "description": "d"},
    {"title": "t", "description": "x" * 5001},
    {"title": "t", "description": "d", "priority": "urgent"},
    {"title": "t", "description": "d", "confirmed": "maybe"},
])
def test_create_ticket_validation(bad, fake_db):
    assert_failure(call("create_ticket", {**bad, "confirmed": True} if "confirmed" not in bad else bad),
                   "create_ticket", 422, "validation_error")
    assert not fake_db.tables.get("tickets")


@pytest.mark.parametrize("protected", [
    {"id": UNKNOWN_UUID}, {"ticket_number": "TKT-5"}, {"status": "closed"},
    {"created_at": "2020-01-01"}, {"updated_at": "2020-01-01"},
])
def test_create_ticket_rejects_protected_fields(protected, fake_db):
    r = call("create_ticket", {**TICKET, "confirmed": True, **protected})
    assert_failure(r, "create_ticket", 422, "validation_error")
    assert not fake_db.tables.get("tickets")


def test_create_ticket_failure_is_reported_not_faked():
    app.dependency_overrides.clear()
    db = FakeDB(fail={"insert:tickets"})
    import app.core.database as database
    original = database.get_supabase
    database.get_supabase = lambda: db
    try:
        r = call("create_ticket", {**TICKET, "confirmed": True})
    finally:
        database.get_supabase = original
    err = assert_failure(r, "create_ticket", 500, "service_error")
    assert "created" not in r.text.replace("Could not create the ticket", "") and not db.tables.get("tickets")
    assert err["message"] == "Could not create the ticket."


# ----------------------------------------------------------------- get_ticket_status
def test_get_ticket_status_by_number_and_uuid():
    created = call("create_ticket", {**TICKET, "confirmed": True}).json()["data"]["ticket"]
    for ident in ("TKT-1001", "tkt-1001", f"  {created['id']}  "):
        t = assert_success(call("get_ticket_status", {"ticket_id_or_number": ident}), "get_ticket_status")["ticket"]
        assert t["ticket_number"] == "TKT-1001" and t["title"] == "VPN down" and t["description"]
        assert t["priority"] == "high" and t["status"] == "open" and t["category"] == "network"
        assert t["created_at"] and t["updated_at"] and t["id"] == created["id"]


def test_get_ticket_status_not_found():
    for ident in ("TKT-9999", UNKNOWN_UUID):
        err = assert_failure(call("get_ticket_status", {"ticket_id_or_number": ident}), "get_ticket_status", 404, "not_found")
        assert "not found" in err["message"].lower()


def test_get_ticket_status_validation():
    assert_failure(call("get_ticket_status", {"ticket_id_or_number": "garbage"}), "get_ticket_status", 422, "validation_error")
    for bad in ({}, {"ticket_id_or_number": " "}, {"ticket_id_or_number": "x" * 65}, {"ticket_id_or_number": "TKT-1", "extra": 1}):
        assert_failure(call("get_ticket_status", bad), "get_ticket_status", 422, "validation_error")


def test_get_ticket_status_db_failure_is_500():
    import app.core.database as database
    original = database.get_supabase
    database.get_supabase = lambda: FakeDB(fail={"select:tickets"})
    try:
        assert_failure(call("get_ticket_status", {"ticket_id_or_number": "TKT-1001"}), "get_ticket_status", 500, "service_error")
    finally:
        database.get_supabase = original


# ----------------------------------------------------------------- generate_document
DOC = {"title": "VPN outage", "document_type": "incident_report", "description": "VPN down for Mysuru users at 10:05."}
REPORT = "# VPN outage\n\n## Summary\nVPN was down.\n\n## Root Cause\nUndetermined."


def test_generate_document_success(monkeypatch, fake_db):
    monkeypatch.setattr(llm_service, "generate_text", lambda p, system_instruction=None: REPORT)
    data = assert_success(call("generate_document", {**DOC, "context": "Restarted gateway."}), "generate_document", 201)
    assert data["saved"] is True and data["content"] == REPORT and data["document_type"] == "incident_report"
    assert data["document_id"] == fake_db.tables["generated_documents"][0]["id"] and data["related_ticket_id"] is None


def test_generate_document_with_related_ticket(monkeypatch):
    monkeypatch.setattr(llm_service, "generate_text", lambda p, system_instruction=None: REPORT)
    ticket = call("create_ticket", {**TICKET, "confirmed": True}).json()["data"]["ticket"]
    data = assert_success(call("generate_document", {**DOC, "related_ticket_id": ticket["id"]}), "generate_document", 201)
    assert data["related_ticket_id"] == ticket["id"]
    assert_failure(call("generate_document", {**DOC, "related_ticket_id": UNKNOWN_UUID}), "generate_document", 404, "not_found")


def test_generate_document_gemini_failure_saves_nothing(monkeypatch, fake_db):
    def down(*a, **k): raise llm_service.LLMError("Gemini request failed.")
    monkeypatch.setattr(llm_service, "generate_text", down)
    assert_failure(call("generate_document", DOC), "generate_document", 502, "upstream_error")
    assert not fake_db.tables.get("generated_documents")


def test_generate_document_save_failure_is_not_reported_as_saved(monkeypatch):
    import app.core.database as database
    monkeypatch.setattr(llm_service, "generate_text", lambda p, system_instruction=None: REPORT)
    monkeypatch.setattr(database, "get_supabase", lambda: FakeDB(fail={"insert:generated_documents"}))
    r = call("generate_document", DOC)
    err = assert_failure(r, "generate_document", 500, "service_error")
    assert "could not be saved" in err["message"] and '"saved"' not in r.text


@pytest.mark.parametrize("bad", [
    {}, {**DOC, "document_type": "poem"}, {**DOC, "title": " "}, {**DOC, "description": ""},
    {**DOC, "related_ticket_id": "not-a-uuid"}, {**DOC, "description": "x" * 10001},
    {**DOC, "id": UNKNOWN_UUID}, {**DOC, "content": "forged"}, {**DOC, "created_at": "2020-01-01"},
])
def test_generate_document_validation(bad, monkeypatch, fake_db):
    def no_llm(*a, **k): raise AssertionError("LLM must not be called for invalid input")
    monkeypatch.setattr(llm_service, "generate_text", no_llm)
    assert_failure(call("generate_document", bad), "generate_document", 422, "validation_error")
    assert not fake_db.tables.get("generated_documents")


# ----------------------------------------------------------------- envelope & definitions
def test_validation_error_does_not_echo_submitted_values():
    r = call("create_ticket", {"title": "t", "description": "d", "priority": "SUPER-SECRET-VALUE"})
    assert "SUPER-SECRET-VALUE" not in r.text and "priority" in r.json()["error"]["message"]


def test_malformed_json_uses_the_failure_envelope():
    r = client.post(f"{BASE}/search_knowledge", content="{not json", headers={"content-type": "application/json"})
    assert_failure(r, "search_knowledge", 422, "validation_error")


def test_tool_definitions_endpoint_matches_routes():
    tools = client.get("/api/agent/tools").json()["tools"]
    assert [t["name"] for t in tools] == ["search_knowledge", "create_ticket", "get_ticket_status", "generate_document"]
    by_name = {t["name"]: t for t in tools}
    assert by_name["search_knowledge"]["parameters"]["required"] == ["question"]
    assert set(by_name["create_ticket"]["parameters"]["required"]) == {"title", "description"}
    assert set(by_name["create_ticket"]["parameters"]["properties"]) == {
        "title", "description", "category", "priority", "confirmed"}
    assert by_name["get_ticket_status"]["parameters"]["required"] == ["ticket_id_or_number"]
    gen = by_name["generate_document"]["parameters"]
    assert set(gen["required"]) == {"title", "document_type", "description"}
    assert set(gen["properties"]) == {"title", "document_type", "description", "context", "related_ticket_id"}
    assert gen["properties"]["document_type"]["enum"] == ["incident_report", "technical_summary"]
    for t in TOOL_DEFINITIONS:  # every definition has a description, an object schema and a live endpoint
        assert t["description"] and t["parameters"]["type"] == "object"
        assert call(t["name"], {}).status_code == 422  # route exists (404/405 would mean it does not)
        assert all("title" not in p for p in t["parameters"]["properties"].values())  # no pydantic title noise
