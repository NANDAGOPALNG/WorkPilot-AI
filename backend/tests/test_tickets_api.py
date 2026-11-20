import pytest

pytest.importorskip("httpx")  # needed by FastAPI's TestClient: pip install httpx
pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import generated_documents, tickets
from app.services import llm_service
from fake_supabase import FakeDB

app = FastAPI()
app.include_router(tickets.router)
app.include_router(generated_documents.router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr("app.core.database.get_supabase", lambda: db)  # services resolve the client lazily
    return db


def create(**kw):
    return client.post("/api/tickets", json={"title": "Laptop will not boot", **kw})


def test_create_ticket_validation():
    assert create(title="").status_code == 422
    assert create(title="   ").status_code == 422
    assert client.post("/api/tickets", json={}).status_code == 422
    assert create(priority="urgent").status_code == 422
    assert create(description="x" * 5001).status_code == 422


def test_create_ticket_and_duplicate_suppression():
    r = create(priority="high")
    body = r.json()
    assert r.status_code == 201 and body["ticket_number"] == "TKT-1001" and body["status"] == "open"
    assert body["category"] == "general" and body["priority"] == "high"
    again = create(priority="high")
    assert again.status_code == 200 and again.json()["id"] == body["id"]


def test_list_get_and_404():
    created = create().json()
    create(title="Other", priority="critical")
    assert client.get("/api/tickets").json()["count"] == 2
    assert client.get("/api/tickets?priority=critical").json()["count"] == 1
    assert client.get("/api/tickets?status=bogus").status_code == 422
    assert client.get("/api/tickets?limit=0").status_code == 422
    assert client.get(f"/api/tickets/{created['id']}").json()["ticket_number"] == "TKT-1001"
    assert client.get("/api/tickets/TKT-1001").status_code == 200
    assert client.get("/api/tickets/TKT-9999").status_code == 404
    assert client.get("/api/tickets/garbage").status_code == 422


def test_patch_ticket():
    t = create().json()
    r = client.patch(f"/api/tickets/{t['id']}", json={"status": "resolved", "priority": "low"})
    assert r.status_code == 200 and r.json()["status"] == "resolved" and r.json()["title"] == t["title"]
    assert client.patch(f"/api/tickets/{t['id']}", json={"status": "done"}).status_code == 422
    assert client.patch(f"/api/tickets/{t['id']}", json={}).status_code == 422
    for protected in ({"ticket_number": "TKT-5"}, {"id": "x"}, {"created_at": "2020-01-01"}, {"updated_at": "x"}):
        assert client.patch(f"/api/tickets/{t['id']}", json=protected).status_code == 422
    assert client.patch("/api/tickets/TKT-9999", json={"status": "closed"}).status_code == 404


def test_generated_documents_endpoints(monkeypatch):
    monkeypatch.setattr(llm_service, "generate_text", lambda prompt, system_instruction=None: "# T\n\n## Summary\nok")
    payload = {"title": "VPN outage", "document_type": "incident_report", "description": "VPN down"}
    assert client.post("/api/generated-documents", json={**payload, "document_type": "poem"}).status_code == 422
    assert client.post("/api/generated-documents", json={**payload, "description": " "}).status_code == 422
    r = client.post("/api/generated-documents", json=payload)
    assert r.status_code == 201 and r.json()["content"].startswith("# T") and r.json()["id"]
    doc_id = r.json()["id"]
    assert client.get(f"/api/generated-documents/{doc_id}").json()["title"] == "VPN outage"
    assert client.get("/api/generated-documents").json()["count"] == 1
    assert client.get("/api/generated-documents/3f2b1c9e-8a7d-4c55-9a0e-0d6f1b2c3d4e").status_code == 404
    missing = client.post("/api/generated-documents", json={**payload, "related_ticket_id": "3f2b1c9e-8a7d-4c55-9a0e-0d6f1b2c3d4e"})
    assert missing.status_code == 404


def test_generated_document_gemini_failure_is_502(monkeypatch, fake_db):
    def down(*a, **k): raise llm_service.LLMError("Gemini request failed.")
    monkeypatch.setattr(llm_service, "generate_text", down)
    r = client.post("/api/generated-documents", json={"title": "t", "document_type": "technical_summary", "description": "d"})
    assert r.status_code == 502 and not fake_db.tables.get("generated_documents")
