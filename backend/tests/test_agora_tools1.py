"""Agora custom-tool integration: join-payload tool config, tool-callback authentication, configuration failures.

No real Agora session is ever created: Agora's REST API is replaced by httpx.MockTransport (FakeAgora), and the
tool routes run against the in-memory FakeDB.
"""
import json
import logging
import re
import types
from urllib.parse import urlsplit

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fake_supabase import FakeDB
from test_agora import AGENT_ID, TOOLS_SECRET, TOOLS_URL, FakeAgora, make_settings

from app.api import dependencies
from app.api.routes import agent_tools
from app.api.routes import agora as agora_routes
from app.core.config import ConfigError
from app.core.security import TOOL_SECRET_HEADER, secrets_match
from app.schemas.agent import (
    TOOL_DEFINITIONS,
    CreateTicketInput,
    GenerateDocumentInput,
    GetTicketStatusInput,
    SearchKnowledgeInput,
)
from app.services import agora_session_service as svc
from app.services import agora_tools, documentation_service, rag_service, ticket_service

BACKEND_MODELS = {
    "search_knowledge": SearchKnowledgeInput,
    "create_ticket": CreateTicketInput,
    "get_ticket_status": GetTicketStatusInput,
    "generate_document": GenerateDocumentInput,
}
AGORA_NAMES = {
    "search_knowledge": "searchKnowledge",
    "create_ticket": "createTicket",
    "get_ticket_status": "getTicketStatus",
    "generate_document": "generateDocument",
}
EXPECTED_TYPES = {
    "search_knowledge": {"question": "string"},
    "create_ticket": {"title": "string", "description": "string", "category": "string", "priority": "string",
                      "confirmed": "boolean"},
    "get_ticket_status": {"ticket_id_or_number": "string"},
    "generate_document": {"title": "string", "document_type": "string", "description": "string", "context": "string"},
}
SAMPLE_ARGS = {
    "search_knowledge": {"question": "How do I reset my VPN?"},
    "create_ticket": {"title": "VPN down", "description": "Cannot connect since 10am", "category": "network",
                      "priority": "high", "confirmed": False},
    "get_ticket_status": {"ticket_id_or_number": "TKT-1001"},
    "generate_document": {"title": "VPN outage", "document_type": "incident_report",
                          "description": "VPN was down from 10am", "context": ""},
}
SCHEMA_KEYWORDS_AGORA_ACCEPTS = {"type", "description", "enum", "items", "properties", "required", "additionalProperties"}


# ------------------------------------------------------------------ helpers
@pytest.fixture
def cfg():
    return agora_tools.build_tools_config(make_settings())


@pytest.fixture
def fake():
    return FakeAgora()


def by_backend_name(config) -> dict:
    """{'create_ticket': <agora tool>, ...} keyed by the last segment of each tool's endpoint URL."""
    return {t["server"]["url"].rsplit("/", 1)[-1]: t for t in config.tools}


def render_body(body: dict, args: dict) -> dict:
    """Mimic Agora's body templating: a complete {{args.x}} is replaced by the argument, keeping its JSON type.
    A missing argument raises KeyError, which stands for Agora's UnresolvedTemplate (call dropped)."""
    out = {}
    for key, value in body.items():
        if isinstance(value, str) and value.startswith("{{args."):
            out[key] = args[value[len("{{args."):-2]]
        else:
            out[key] = value
    return out


def render_headers(headers: dict, template_variables: dict) -> dict:
    out = {}
    for key, value in headers.items():
        if value.startswith("{{template_variables."):
            value = template_variables[value[len("{{template_variables."):-2]]
        out[key] = value
    return out


tools_app = FastAPI()
tools_app.include_router(agent_tools.router)
tools_api = TestClient(tools_app)


def call_like_agora(config, backend_name: str, args: dict, *, secret_override=None):
    """Send exactly the request Agora's engine would build from the tool config, to our real route."""
    tool = by_backend_name(config)[backend_name]
    headers = render_headers(tool["server"]["headers"], config.template_variables)
    if secret_override is not None:
        headers[TOOL_SECRET_HEADER] = secret_override
    return tools_api.post(urlsplit(tool["server"]["url"]).path, json=render_body(tool["server"]["body"], args),
                          headers=headers)


@pytest.fixture
def tool_secret(monkeypatch):
    """Configure AGORA_TOOLS_SHARED_SECRET for the tool routes (the real _configured_secret code runs)."""
    monkeypatch.setattr(dependencies, "get_settings", lambda: make_settings(agora_tools_shared_secret=TOOLS_SECRET))
    return TOOLS_SECRET


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr("app.core.database.get_supabase", lambda: db)
    return db


# ------------------------------------------------------------------ tool definitions
def test_exactly_the_four_backend_tools_are_exposed_with_agora_compliant_names(cfg):
    assert set(agora_tools.TOOL_NAME_MAP) == {d["name"] for d in TOOL_DEFINITIONS} == set(AGORA_NAMES)
    names = [t["function"]["name"] for t in cfg.tools]
    assert names == list(AGORA_NAMES.values())
    for name in names:  # Agora: starts with a letter, letters+digits only, <= 64, no mcp prefix, not ragsearch_tool
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", name)
        assert not name.lower().startswith("mcp") and name.lower() != "ragsearch_tool"
    assert len({n.lower() for n in names}) == len(names) <= 32  # no conflicts, within the 32-tool limit
    # the backend's snake_case names would have been rejected by Agora, which is why they are mapped
    assert not any(re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", d["name"]) for d in TOOL_DEFINITIONS)
    agora_tools.validate_tools(cfg.tools, cfg.template_variables)


def test_each_tool_has_type_function_sync_execution_post_and_https_endpoint(cfg):
    for tool in cfg.tools:
        assert tool["type"] == "function" and tool["execution"] == {"mode": "sync"}
        assert tool["function"]["description"].strip()
        assert tool["server"]["method"] == "POST"
        assert tool["server"]["url"].startswith("https://")
        assert 1000 <= tool["server"]["timeout_ms"] <= 100000


def test_endpoint_urls_point_at_the_existing_backend_routes(cfg):
    mounted = {r.path for r in agent_tools.router.routes}
    for backend_name, tool in by_backend_name(cfg).items():
        parts = urlsplit(tool["server"]["url"])
        assert (parts.scheme, parts.netloc) == ("https", "tools.example.com")
        assert parts.path == f"/api/agent/tools/{backend_name}" and parts.path in mounted
        assert AGORA_NAMES[backend_name] == tool["function"]["name"]
        assert not parts.query and not parts.fragment


@pytest.mark.parametrize("configured, prefix", [
    ("https://abc-123.ngrok-free.app/", "https://abc-123.ngrok-free.app"),
    ("  https://api.example.com  ", "https://api.example.com"),
    ("https://api.example.com/backend/", "https://api.example.com/backend"),
    ("https://api.example.com:8443", "https://api.example.com:8443"),
])
def test_base_url_is_normalised_into_endpoint_urls(configured, prefix):
    config = agora_tools.build_tools_config(make_settings(agora_tools_base_url=configured))
    assert by_backend_name(config)["search_knowledge"]["server"]["url"] == f"{prefix}/api/agent/tools/search_knowledge"


def test_parameter_schemas_match_the_tools(cfg):
    for backend_name, tool in by_backend_name(cfg).items():
        schema = tool["function"]["parameters"]
        expected = EXPECTED_TYPES[backend_name]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert {k: v["type"] for k, v in schema["properties"].items()} == expected
        assert all(v["description"].strip() for v in schema["properties"].values())
        # every parameter is required: the body maps each one, and a missing {{args.x}} would drop the call
        assert schema["required"] == list(expected)


def test_parameter_schemas_use_only_keywords_agora_handles_reliably(cfg):
    def walk(node):
        for key, value in node.items():
            assert key in SCHEMA_KEYWORDS_AGORA_ACCEPTS, key  # no $ref, $defs, anyOf, format, pattern, min/max, default
            if key == "properties":
                for sub in value.values():
                    walk(sub)
    for tool in cfg.tools:
        walk(tool["function"]["parameters"])
    assert len(json.dumps(cfg.tools).encode()) < 64 * 1024


def test_enums_and_required_fields_agree_with_the_backend_models(cfg):
    tools = by_backend_name(cfg)
    ticket = CreateTicketInput.model_json_schema()["properties"]["priority"]["enum"]
    doc = GenerateDocumentInput.model_json_schema()["properties"]["document_type"]["enum"]
    assert tools["create_ticket"]["function"]["parameters"]["properties"]["priority"]["enum"] == ticket
    assert tools["generate_document"]["function"]["parameters"]["properties"]["document_type"]["enum"] == doc
    for backend_name, model in BACKEND_MODELS.items():
        exposed = set(tools[backend_name]["function"]["parameters"]["properties"])
        assert exposed <= set(model.model_fields)  # nothing the backend would reject as an unknown field
        backend_required = {n for n, f in model.model_fields.items() if f.is_required()}
        assert backend_required <= exposed  # the LLM can always supply what the backend needs
    # not exposed to the voice agent: a UUID nobody can say aloud
    assert "related_ticket_id" not in tools["generate_document"]["function"]["parameters"]["properties"]


# ------------------------------------------------------------------ body mapping
@pytest.mark.parametrize("backend_name", list(BACKEND_MODELS))
def test_body_maps_every_parameter_by_complete_placeholder(cfg, backend_name):
    tool = by_backend_name(cfg)[backend_name]
    props = list(tool["function"]["parameters"]["properties"])
    assert tool["server"]["body"] == {p: "{{args.%s}}" % p for p in props}
    assert set(SAMPLE_ARGS[backend_name]) == set(props)


@pytest.mark.parametrize("backend_name", list(BACKEND_MODELS))
def test_rendered_body_is_accepted_by_the_backend_input_model(cfg, backend_name):
    body = render_body(by_backend_name(cfg)[backend_name]["server"]["body"], SAMPLE_ARGS[backend_name])
    BACKEND_MODELS[backend_name].model_validate(body)  # extra="forbid" would reject any wrongly named field


def test_confirmed_keeps_its_boolean_type_and_empty_context_becomes_none(cfg):
    for confirmed in (False, True):
        body = render_body(by_backend_name(cfg)["create_ticket"]["server"]["body"],
                           {**SAMPLE_ARGS["create_ticket"], "confirmed": confirmed})
        assert body["confirmed"] is confirmed
        assert CreateTicketInput.model_validate(body).confirmed is confirmed
    body = render_body(by_backend_name(cfg)["generate_document"]["server"]["body"], SAMPLE_ARGS["generate_document"])
    assert GenerateDocumentInput.model_validate(body).context is None


def test_an_omitted_argument_would_drop_the_call_so_the_schema_makes_confirmed_mandatory(cfg):
    tool = by_backend_name(cfg)["create_ticket"]
    assert "confirmed" in tool["function"]["parameters"]["required"]
    args = {k: v for k, v in SAMPLE_ARGS["create_ticket"].items() if k != "confirmed"}
    with pytest.raises(KeyError):
        render_body(tool["server"]["body"], args)


# ------------------------------------------------------------------ authentication configuration
def test_secret_travels_only_as_a_complete_header_template_variable(cfg):
    assert cfg.template_variables == {"workpilot_tool_secret": TOOLS_SECRET}
    for tool in cfg.tools:
        headers = tool["server"]["headers"]
        assert headers[TOOL_SECRET_HEADER] == "{{template_variables.workpilot_tool_secret}}"
        assert not any("{{args." in v for v in headers.values())
    assert TOOLS_SECRET not in json.dumps(cfg.tools) and TOOLS_SECRET not in repr(cfg)


def test_join_payload_enables_tools_and_carries_the_tool_config(fake):
    svc.start_session(client=fake.client())
    body_text = fake.requests[0].content.decode()
    props = fake.sent_json()["properties"]
    llm = props["llm"]

    assert props["advanced_features"] == {"enable_tools": True}
    assert llm["tools"] == agora_tools.build_tools_config(make_settings()).tools
    assert [t["function"]["name"] for t in llm["tools"]] == list(AGORA_NAMES.values())
    assert llm["template_variables"] == {"workpilot_tool_secret": TOOLS_SECRET}
    assert body_text.count(TOOLS_SECRET) == 1  # only inside template_variables, never in prompt, greeting or tools
    # the existing voice configuration is untouched
    assert props["channel"].startswith("workpilot-") and props["agent_rtc_uid"] == "1000"
    assert llm["credential_mode"] == "managed" and llm["vendor"] == "openai" and llm["style"] == "openai"
    assert llm["greeting_message"] == make_settings().agora_greeting and llm["failure_message"]
    assert llm["params"] == {"model": "gpt-4o-mini"} and llm["max_history"] == svc.MAX_HISTORY >= 10
    assert props["asr"]["vendor"] == "deepgram" and props["tts"]["vendor"] == "minimax"


def test_system_prompt_is_workpilot_specific_and_no_longer_says_tools_are_missing():
    prompt = svc.SYSTEM_PROMPT
    assert "WorkPilot AI" in prompt
    assert "not yet connected" not in prompt and "cannot look up" not in prompt
    for agora_name in AGORA_NAMES.values():
        assert agora_name in prompt
    for rule in ("confirmed false", "confirmed true", "created is true", "saved is true", "found is false",
                 "not confirmation", "spoken aloud"):
        assert rule in prompt
    assert "{{" not in prompt and "}}" not in prompt  # Agora would treat these as template variables
    assert TOOLS_SECRET not in prompt


def test_system_prompt_is_what_is_sent_to_agora(fake):
    svc.start_session(client=fake.client())
    assert fake.sent_json()["properties"]["llm"]["system_messages"] == [{"role": "system", "content": svc.SYSTEM_PROMPT}]


@pytest.mark.parametrize("mutate", [
    lambda t: t[0]["function"].__setitem__("name", "search_knowledge"),          # underscore
    lambda t: t[0]["function"].__setitem__("name", "mcpSearch"),                  # reserved prefix
    lambda t: t[0]["function"].__setitem__("name", "ragsearch_tool"),
    lambda t: t[1]["function"].__setitem__("name", "SEARCHKNOWLEDGE"),            # duplicate, case-insensitive
    lambda t: t[0]["server"]["headers"].__setitem__("X-Bad", "{{args.question}}"),
    lambda t: t[0]["server"]["body"].__setitem__("question", "q: {{args.question}}"),
    lambda t: t[0]["server"]["body"].__setitem__("question", "{{args.unknown}}"),
    lambda t: t[0]["server"]["headers"].__setitem__("X-Bad", "{{template_variables.undefined}}"),
    lambda t: t[0]["server"].__setitem__("timeout_ms", 500),
    lambda t: t[0]["server"].__setitem__("method", "PUT"),
    lambda t: t[0]["server"].__setitem__("url", "http://tools.example.com/x"),
    lambda t: t[0]["function"]["parameters"]["properties"]["question"].__setitem__("maxLength", 10),
    lambda t: t[0]["function"]["parameters"].__setitem__("required", ["nope"]),
    lambda t: t.extend(json.loads(json.dumps(t[0])) for _ in range(40)),          # more than 32 tools
])
def test_validator_rejects_configurations_agora_would_refuse(cfg, mutate):
    tools = json.loads(json.dumps(cfg.tools))
    mutate(tools)
    with pytest.raises(ConfigError):
        agora_tools.validate_tools(tools, cfg.template_variables)


# ------------------------------------------------------------------ configuration failures
BAD_SETTINGS = [
    ({"agora_tools_base_url": None}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "   "}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "http://tools.example.com"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "tools.example.com"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://localhost:8000"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://127.0.0.1:8000"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://192.168.1.20"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://10.0.0.5"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://[::1]"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://workpilot-backend"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://my-laptop.local"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://user:pass-LEAK@tools.example.com"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://tools.example.com/?key=abc-LEAK"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_base_url": "https://tools.example.com:notaport"}, "AGORA_TOOLS_BASE_URL"),
    ({"agora_tools_shared_secret": None}, "AGORA_TOOLS_SHARED_SECRET"),
    ({"agora_tools_shared_secret": "     "}, "AGORA_TOOLS_SHARED_SECRET"),
    ({"agora_tools_shared_secret": "tooshort-LEAK"}, "AGORA_TOOLS_SHARED_SECRET"),
    ({"agora_tools_shared_secret": "has spaces inside-LEAK-0123456789"}, "AGORA_TOOLS_SHARED_SECRET"),
    ({"agora_tools_shared_secret": "non-ascii-ünïcode-LEAK-0123456789"}, "AGORA_TOOLS_SHARED_SECRET"),
]


@pytest.mark.parametrize("over, variable", BAD_SETTINGS)
def test_start_session_refuses_bad_tool_settings_before_calling_agora(fake, over, variable):
    with pytest.raises(ConfigError) as exc:
        svc.start_session(client=fake.client(**over))
    message = str(exc.value)
    assert variable in message  # names the variable...
    for value in over.values():
        if value and value.strip():
            assert value.strip() not in message  # ...never the value
    assert "LEAK" not in message
    assert fake.requests == []  # no agent was started with broken tool URLs


def test_api_reports_bad_tool_config_as_503_without_details(monkeypatch, fake, caplog):
    monkeypatch.setattr(svc, "get_client", lambda: fake.client(agora_tools_base_url=None))
    app = FastAPI()
    app.include_router(agora_routes.router)
    with caplog.at_level(logging.DEBUG):
        r = TestClient(app).post("/api/agora/sessions")
    assert r.status_code == 503 and "not configured" in r.json()["detail"]["message"]
    assert "AGORA_" not in r.text and fake.requests == []
    assert "AGORA_TOOLS_BASE_URL" in caplog.text  # the operator can still see what to fix, in the server log


def test_stopping_a_session_does_not_need_the_tool_settings(fake):
    client = fake.client(agora_tools_base_url=None, agora_tools_shared_secret=None)
    assert svc.stop_session(AGENT_ID, client=client) == {"session_id": AGENT_ID, "status": "stopped"}
    assert str(fake.requests[0].url).endswith(f"/agents/{AGENT_ID}/leave")


def test_valid_settings_start_a_session_exactly_as_before(fake):
    out = svc.start_session(client=fake.client())
    assert out["session_id"] == AGENT_ID and out["status"] == "RUNNING" and out["rtc_token"].startswith("007")
    assert set(out) == {"session_id", "status", "app_id", "channel", "user_uid", "agent_uid", "rtc_token",
                        "token_expires_in_seconds", "idle_timeout_seconds"}
    assert TOOLS_SECRET not in json.dumps(out)


def test_base_url_validator_returns_normalised_value():
    assert agora_tools.validate_base_url(" https://a.example.com/x/ ") == "https://a.example.com/x"


# ------------------------------------------------------------------ callback authentication
CALLS = {
    "search_knowledge": {"question": "q?"},
    "create_ticket": {"title": "t", "description": "d", "confirmed": True},
    "get_ticket_status": {"ticket_id_or_number": "TKT-1001"},
    "generate_document": {"title": "t", "document_type": "incident_report", "description": "d"},
}
AUTH = {TOOL_SECRET_HEADER: TOOLS_SECRET}


@pytest.fixture
def services_must_not_run(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("a tool ran without valid credentials")
    monkeypatch.setattr(rag_service, "answer_question", explode)
    monkeypatch.setattr(ticket_service, "create_ticket", explode)
    monkeypatch.setattr(ticket_service, "get_ticket", explode)
    monkeypatch.setattr(documentation_service, "generate_document", explode)


@pytest.mark.parametrize("tool", list(CALLS))
def test_tool_routes_reject_requests_without_the_secret(tool, tool_secret, fake_db, services_must_not_run):
    r = tools_api.post(f"/api/agent/tools/{tool}", json=CALLS[tool])
    assert r.status_code == 401 and r.json()["detail"]["code"] == "unauthorized"
    assert TOOLS_SECRET not in r.text
    assert not fake_db.tables.get("tickets")


@pytest.mark.parametrize("tool", list(CALLS))
@pytest.mark.parametrize("wrong", ["wrong-value-LEAK", TOOLS_SECRET + "x", TOOLS_SECRET[:-1], TOOLS_SECRET.upper(),
                                   "", "short"])
def test_tool_routes_reject_a_wrong_secret(tool, wrong, tool_secret, fake_db, services_must_not_run, caplog):
    with caplog.at_level(logging.DEBUG):
        r = tools_api.post(f"/api/agent/tools/{tool}", json=CALLS[tool], headers={TOOL_SECRET_HEADER: wrong})
    assert r.status_code == 401
    assert TOOLS_SECRET not in r.text + caplog.text
    if wrong:
        assert wrong not in r.text + caplog.text  # the supplied value is not echoed or logged either
    assert not fake_db.tables.get("tickets")


def test_authentication_is_checked_before_input_validation(tool_secret, services_must_not_run):
    assert tools_api.post("/api/agent/tools/create_ticket", json={}).status_code == 401
    assert tools_api.post("/api/agent/tools/create_ticket", json={}, headers=AUTH).status_code == 422


def test_correct_secret_reaches_every_tool(tool_secret, fake_db, monkeypatch):
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda q: {"question": q, "answer": "A", "sources": [], "metadata": {}})
    monkeypatch.setattr(documentation_service, "generate_document", lambda data: {
        "id": "doc-1", "title": data["title"], "document_type": data["document_type"], "related_ticket_id": None,
        "created_at": "2026-01-01T00:00:00Z", "content": "# x"})

    assert tools_api.post("/api/agent/tools/search_knowledge", json=CALLS["search_knowledge"], headers=AUTH).status_code == 200
    created = tools_api.post("/api/agent/tools/create_ticket", json=CALLS["create_ticket"], headers=AUTH)
    assert created.status_code == 201 and created.json()["data"]["ticket"]["ticket_number"] == "TKT-1001"
    status = tools_api.post("/api/agent/tools/get_ticket_status", json=CALLS["get_ticket_status"], headers=AUTH)
    assert status.status_code == 200 and status.json()["data"]["ticket"]["status"] == "open"
    doc = tools_api.post("/api/agent/tools/generate_document", json=CALLS["generate_document"], headers=AUTH)
    assert doc.status_code == 201 and doc.json()["data"]["saved"] is True


def test_header_name_is_case_insensitive(tool_secret, monkeypatch):
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda q: {"question": q, "answer": "A", "sources": [], "metadata": {}})
    r = tools_api.post("/api/agent/tools/search_knowledge", json=CALLS["search_knowledge"],
                       headers={"x-workpilot-tool-secret": TOOLS_SECRET})
    assert r.status_code == 200


def test_tool_catalogue_stays_open_and_leaks_nothing(tool_secret):
    r = tools_api.get("/api/agent/tools")
    assert r.status_code == 200 and {t["name"] for t in r.json()["tools"]} == set(AGORA_NAMES)
    assert TOOLS_SECRET not in r.text


def test_without_a_configured_secret_local_development_stays_open(monkeypatch):
    # conftest.py already makes the secret unset by default; the documented local workflow (curl/Swagger) still works
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda q: {"question": q, "answer": "A", "sources": [], "metadata": {}})
    assert tools_api.post("/api/agent/tools/search_knowledge", json=CALLS["search_knowledge"]).status_code == 200


def test_secret_lookup_handles_unset_blank_and_unloadable_settings(monkeypatch):
    def use(settings=None, error=None):
        def get_settings():
            if error:
                raise error
            return settings
        monkeypatch.setattr(dependencies, "get_settings", get_settings)
        return dependencies._configured_secret()

    assert use(types.SimpleNamespace(agora_tools_shared_secret=None)) is None
    assert use(types.SimpleNamespace(agora_tools_shared_secret="   ")) is None
    assert use(types.SimpleNamespace(agora_tools_shared_secret=f"  {TOOLS_SECRET} ")) == TOOLS_SECRET
    assert use(error=ConfigError("no supabase")) is None


def test_secrets_match_is_exact_and_never_raises():
    assert secrets_match(TOOLS_SECRET, TOOLS_SECRET) is True
    assert secrets_match(TOOLS_SECRET + " ", TOOLS_SECRET) is False
    assert secrets_match("é" * 20, TOOLS_SECRET) is False  # non-ASCII input must not raise
    assert not secrets_match(None, TOOLS_SECRET) and not secrets_match("", "") and not secrets_match(TOOLS_SECRET, None)


# ------------------------------------------------------------------ ticket confirmation, end to end through Agora's request shape
def test_ticket_flow_preview_then_confirm_then_lookup(cfg, tool_secret, fake_db):
    args = {"title": "VPN down", "description": "Cannot connect since 10am", "category": "network",
            "priority": "high", "confirmed": False}

    preview = call_like_agora(cfg, "create_ticket", args)  # what the LLM does first
    data = preview.json()["data"]
    assert preview.status_code == 200 and data["created"] is False and data["requires_confirmation"] is True
    assert data["proposed_ticket"] == {k: v for k, v in args.items() if k != "confirmed"}
    assert "ticket" not in data and not fake_db.tables.get("tickets")  # nothing written without confirmation

    created = call_like_agora(cfg, "create_ticket", {**args, "confirmed": True})  # only after an explicit yes
    cdata = created.json()["data"]
    assert created.status_code == 201 and cdata["created"] is True
    assert cdata["ticket"]["ticket_number"] == "TKT-1001" and len(fake_db.tables["tickets"]) == 1

    looked_up = call_like_agora(cfg, "get_ticket_status", {"ticket_id_or_number": "TKT-1001"})
    ticket = looked_up.json()["data"]["ticket"]
    assert looked_up.status_code == 200 and ticket["status"] == "open" and ticket["title"] == "VPN down"


def test_ticket_lookup_of_an_unknown_ticket_reports_not_found(cfg, tool_secret, fake_db):
    r = call_like_agora(cfg, "get_ticket_status", {"ticket_id_or_number": "TKT-9999"})
    body = r.json()
    assert r.status_code == 404 and body["success"] is False and body["error"]["code"] == "not_found"


def test_agora_shaped_requests_with_a_wrong_secret_never_create_tickets(cfg, tool_secret, fake_db):
    r = call_like_agora(cfg, "create_ticket", {**SAMPLE_ARGS["create_ticket"], "confirmed": True},
                        secret_override="not-the-secret")
    assert r.status_code == 401 and not fake_db.tables.get("tickets")


def test_invalid_priority_from_the_model_is_rejected_and_creates_nothing(cfg, tool_secret, fake_db):
    r = call_like_agora(cfg, "create_ticket", {**SAMPLE_ARGS["create_ticket"], "priority": "urgent", "confirmed": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert not fake_db.tables.get("tickets")


def test_generate_document_request_shape_reaches_the_service(cfg, tool_secret, monkeypatch):
    seen = {}

    def fake_generate(data):
        seen.update(data)
        return {"id": "doc-1", "title": data["title"], "document_type": data["document_type"],
                "related_ticket_id": None, "created_at": "2026-01-01T00:00:00Z", "content": "# VPN outage"}

    monkeypatch.setattr(documentation_service, "generate_document", fake_generate)
    r = call_like_agora(cfg, "generate_document", SAMPLE_ARGS["generate_document"])
    assert r.status_code == 201 and r.json()["data"]["saved"] is True and r.json()["data"]["document_id"] == "doc-1"
    assert seen["context"] is None and seen["related_ticket_id"] is None and seen["document_type"] == "incident_report"


# ------------------------------------------------------------------ secret leakage
@pytest.fixture
def api_with(monkeypatch):
    app = FastAPI()
    app.include_router(agora_routes.router)
    client = TestClient(app)

    def _use(fake_agora=None, **settings):
        fake_agora = fake_agora or FakeAgora()
        monkeypatch.setattr(svc, "get_client", lambda: fake_agora.client(**settings))
        return client, fake_agora
    return _use


def test_session_responses_and_logs_never_contain_the_tool_secret(api_with, caplog):
    api, _ = api_with()
    with caplog.at_level(logging.DEBUG):
        start = api.post("/api/agora/sessions")
        stop = api.post(f"/api/agora/sessions/{AGENT_ID}/stop")
    assert start.status_code == 201
    assert TOOLS_SECRET not in start.text + stop.text + caplog.text


def test_tool_secret_echoed_back_by_agora_is_scrubbed(api_with, caplog):
    echo = {"reason": f"invalid template value {TOOLS_SECRET}", "detail": TOOLS_SECRET}
    api, _ = api_with(FakeAgora(join=(400, echo)))
    with caplog.at_level(logging.DEBUG):
        r = api.post("/api/agora/sessions")
    assert r.status_code == 502
    assert TOOLS_SECRET not in r.text + caplog.text


def test_config_errors_and_start_logs_never_contain_the_secret_value(fake, caplog):
    with caplog.at_level(logging.DEBUG):
        svc.start_session(client=fake.client())
        with pytest.raises(ConfigError):
            svc.start_session(client=fake.client(agora_tools_base_url="http://insecure.example.com"))
    assert TOOLS_SECRET not in caplog.text
