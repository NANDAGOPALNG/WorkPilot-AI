import base64
import json
import logging
import zlib

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import agora as agora_routes
from app.core.config import ConfigError, Settings
from app.integrations import agora_client
from app.integrations.agora_client import AgoraClient, AgoraError
from app.integrations.agora_token import build_rtc_token
from app.services import agora_session_service as svc

# Distinctive fake credentials so leaks are easy to spot.
APP_ID = "0123456789abcdef0123456789abcdef"
CERT = "fedcba9876543210fedcba9876543210"
CUSTOMER_ID = "customer-id-LEAKCHECK"
CUSTOMER_SECRET = "customer-secret-LEAKCHECK"
BASIC = base64.b64encode(f"{CUSTOMER_ID}:{CUSTOMER_SECRET}".encode()).decode()
SECRETS = [CERT, CUSTOMER_ID, CUSTOMER_SECRET, BASIC]
AGENT_ID = "1NT29X10YHxxxxxWJOXLYHNYB"
# start_session now requires the Agora custom-tool settings (see tests/test_agora_tools.py).
TOOLS_URL = "https://tools.example.com"
TOOLS_SECRET = "tools-secret-LEAKCHECK-0123456789"


def make_settings(**over) -> Settings:
    base = dict(supabase_url="https://x.supabase.co", supabase_service_role_key="k", agora_app_id=APP_ID,
                agora_app_certificate=CERT, agora_customer_id=CUSTOMER_ID, agora_customer_secret=CUSTOMER_SECRET,
                agora_tools_base_url=TOOLS_URL, agora_tools_shared_secret=TOOLS_SECRET)
    return Settings(_env_file=None, **{**base, **over})


class FakeAgora:
    """httpx.MockTransport handler that records requests and answers like Agora."""

    def __init__(self, join=None, leave=None):
        self.requests = []
        self.join = join or (200, {"agent_id": AGENT_ID, "create_ts": 1737111452, "status": "RUNNING"})
        self.leave = leave or (200, {})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.join if request.url.path.endswith("/join") else self.leave
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body) if not isinstance(body, str) else httpx.Response(status, text=body)

    def client(self, **settings) -> AgoraClient:
        return AgoraClient(make_settings(**settings), transport=httpx.MockTransport(self))

    def sent_json(self, index=0) -> dict:
        return json.loads(self.requests[index].content)


@pytest.fixture
def fake():
    return FakeAgora()


# ------------------------------------------------------------------ configuration
def test_missing_configuration_names_variables_not_values():
    with pytest.raises(ConfigError) as e:
        agora_client.check_configured(make_settings(agora_app_id=None, agora_customer_secret=None))
    msg = str(e.value)
    assert "AGORA_APP_ID" in msg and "AGORA_CUSTOMER_SECRET" in msg and "AGORA_CUSTOMER_ID" not in msg
    with pytest.raises(ConfigError):
        AgoraClient(make_settings(agora_app_certificate="   "))


def test_malformed_app_id_or_certificate_rejected_without_echoing_them():
    for bad in ("short", "z" * 32, APP_ID + "0"):
        with pytest.raises(ConfigError) as e:
            agora_client.check_configured(make_settings(agora_app_id=bad))
        assert "AGORA_APP_ID" in str(e.value) and bad not in str(e.value)


# ------------------------------------------------------------------ token builder
def _decode(token: str) -> bytes:
    assert token.startswith("007")
    return zlib.decompress(base64.b64decode(token[3:]))


def test_rtc_token_has_expected_structure():
    token = build_rtc_token(APP_ID, CERT, "chan-1", 4242, 3600)
    raw = _decode(token)
    assert APP_ID.encode() in raw and b"chan-1" in raw and b"4242" in raw
    assert CERT.encode() not in raw  # the certificate only signs, it is never embedded
    assert build_rtc_token(APP_ID, CERT, "chan-1", 4242, 3600) != token  # random salt


def test_rtc_token_matches_official_sdk_implementation():
    official = pytest.importorskip("agora_agent.agentkit.token")  # optional cross-check: pip install agora-agents
    mine = _decode(build_rtc_token(APP_ID, CERT, "chan-1", 4242, 3600))
    theirs = _decode(official.generate_rtc_token(APP_ID, CERT, "chan-1", 4242, expiry_seconds=3600))
    # Signature, issue time and salt differ per token; the service payload (channel, uid, privileges) must be identical.
    assert _service_tail(mine) == _service_tail(theirs)


def _service_tail(raw: bytes) -> bytes:
    sig_len = int.from_bytes(raw[:2], "little")
    body = raw[2 + sig_len:]
    app_id_len = int.from_bytes(body[:2], "little")
    return body[2 + app_id_len + 12:]  # skip app id, issue_ts, expire, salt


@pytest.mark.parametrize("args", [
    ("short", CERT, "c", 1, 60), (APP_ID, "x" * 32, "c", 1, 60), (APP_ID, CERT, "", 1, 60),
    (APP_ID, CERT, "c" * 65, 1, 60), (APP_ID, CERT, "c", 0, 60), (APP_ID, CERT, "c", True, 60),
    (APP_ID, CERT, "c", 1, 0), (APP_ID, CERT, "c", 1, 86401),
])
def test_rtc_token_input_validation(args):
    with pytest.raises(ValueError) as e:
        build_rtc_token(*args)
    assert CERT not in str(e.value)


# ------------------------------------------------------------------ client
def test_client_start_agent_uses_documented_endpoint_and_basic_auth(fake):
    result = fake.client().start_agent({"name": "n", "properties": {}})
    assert result == {"agent_id": AGENT_ID, "status": "RUNNING", "create_ts": 1737111452}
    req = fake.requests[0]
    assert req.method == "POST"
    assert str(req.url) == f"https://api.agora.io/api/conversational-ai-agent/v2/projects/{APP_ID}/join"
    assert req.headers["authorization"] == f"Basic {BASIC}"


def test_client_stop_agent_endpoint(fake):
    fake.client().stop_agent(AGENT_ID)
    assert str(fake.requests[0].url).endswith(f"/projects/{APP_ID}/agents/{AGENT_ID}/leave")


def test_client_stop_agent_escapes_the_id_in_the_path(fake):
    fake.client().stop_agent("../../x")
    assert "/agents/..%2F..%2Fx/leave" in str(fake.requests[0].url)


@pytest.mark.parametrize("response, status, text", [
    ((401, {"detail": "bad", "reason": "Unauthorized"}), 502, "credentials"),
    ((403, {}), 502, "credentials"),
    ((429, {}), 429, "rate limiting"),
    ((500, {"reason": "boom"}), 502, "Agora returned an error"),
    ((400, {"reason": "invalid channel"}), 502, "invalid channel"),
    ((200, "not json"), 502, "unexpected response"),
    ((200, {"status": "RUNNING"}), 502, "no agent id"),
    ((200, []), 502, "unexpected response"),
])
def test_client_start_failures(response, status, text):
    with pytest.raises(AgoraError) as e:
        FakeAgora(join=response).client().start_agent({})
    assert e.value.status_code == status and text in str(e.value)


def test_client_timeout_and_network_errors():
    with pytest.raises(AgoraError) as e:
        FakeAgora(join=(0, httpx.ReadTimeout("slow"))).client().start_agent({})
    assert e.value.status_code == 504
    with pytest.raises(AgoraError) as e:
        FakeAgora(join=(0, httpx.ConnectError("https://api.agora.io?token=" + CERT))).client().start_agent({})
    assert e.value.status_code == 502 and CERT not in str(e.value)


def test_client_stop_failures():
    with pytest.raises(AgoraError) as e:
        FakeAgora(leave=(404, {"reason": "not found"})).client().stop_agent(AGENT_ID)
    assert e.value.status_code == 404 and "not found" in str(e.value).lower()
    with pytest.raises(AgoraError) as e:
        FakeAgora(leave=(500, {})).client().stop_agent(AGENT_ID)
    assert e.value.status_code == 502


# ------------------------------------------------------------------ session service
def test_start_session_builds_documented_join_request_and_returns_connection_details(fake):
    out = svc.start_session(client=fake.client())
    body = fake.sent_json()
    props = body["properties"]

    assert out["session_id"] == AGENT_ID and out["status"] == "RUNNING" and out["app_id"] == APP_ID
    assert out["channel"] == props["channel"] and out["channel"].startswith("workpilot-")
    assert out["agent_uid"] == 1000 and props["agent_rtc_uid"] == "1000"
    assert props["remote_rtc_uids"] == [str(out["user_uid"])] and out["user_uid"] != out["agent_uid"]
    assert props["enable_string_uid"] is False and props["idle_timeout"] == 120
    assert body["name"].startswith("workpilot-agent-")
    for block in ("asr", "llm", "tts"):
        assert props[block]["credential_mode"] == "managed"
    assert props["token"].startswith("007") and out["rtc_token"].startswith("007") and props["token"] != out["rtc_token"]
    assert f"{out['user_uid']}".encode() in _decode(out["rtc_token"]) and out["channel"].encode() in _decode(out["rtc_token"])
    assert out["token_expires_in_seconds"] == 3600


def test_each_session_gets_a_unique_channel_agent_name_and_uid(fake):
    a, b = svc.start_session(client=fake.client()), svc.start_session(client=fake.client())
    assert a["channel"] != b["channel"] and fake.sent_json(0)["name"] != fake.sent_json(1)["name"]


def test_start_session_agora_failure_is_reported_not_faked():
    with pytest.raises(AgoraError):
        svc.start_session(client=FakeAgora(join=(500, {})).client())


@pytest.mark.parametrize("status", ["FAILED", "STOPPED", "IDLE", None])
def test_start_session_requires_agora_to_confirm_running_state(status):
    fake = FakeAgora(join=(200, {"agent_id": AGENT_ID, "status": status}))
    with pytest.raises(AgoraError) as e:
        svc.start_session(client=fake.client())
    assert "did not confirm" in str(e.value)
    assert str(fake.requests[-1].url).endswith(f"/agents/{AGENT_ID}/leave")  # cleaned up the half-started agent


def test_start_session_accepts_starting_status():
    out = svc.start_session(client=FakeAgora(join=(200, {"agent_id": AGENT_ID, "status": "STARTING"})).client())
    assert out["status"] == "STARTING"


def test_start_session_without_configuration(monkeypatch):
    monkeypatch.setattr(agora_client, "get_settings", lambda: make_settings(agora_app_id=None))
    with pytest.raises(ConfigError):
        svc.start_session()


def test_stop_session(fake):
    assert svc.stop_session(f" {AGENT_ID} ", client=fake.client()) == {"session_id": AGENT_ID, "status": "stopped"}


@pytest.mark.parametrize("bad", ["", "   ", "short", "has space in it", "../../etc/passwd", "a" * 65, "id;rm -rf"])
def test_stop_session_rejects_invalid_ids_without_calling_agora(bad, fake):
    with pytest.raises(ValueError):
        svc.stop_session(bad, client=fake.client())
    assert fake.requests == []


# ------------------------------------------------------------------ API
app = FastAPI()
app.include_router(agora_routes.router)
api = TestClient(app)


@pytest.fixture
def use(monkeypatch):
    def _use(fake_agora=None, **settings):
        fake_agora = fake_agora or FakeAgora()
        monkeypatch.setattr(svc, "get_client", lambda: fake_agora.client(**settings))
        return fake_agora
    return _use


def test_api_start_session_response_shape(use):
    use()
    r = api.post("/api/agora/sessions")
    body = r.json()
    assert r.status_code == 201
    assert set(body) == {"session_id", "status", "app_id", "channel", "user_uid", "agent_uid", "rtc_token",
                         "token_expires_in_seconds", "idle_timeout_seconds"}
    assert body["session_id"] == AGENT_ID and isinstance(body["user_uid"], int) and body["rtc_token"].startswith("007")


def test_api_start_session_not_configured(monkeypatch):
    monkeypatch.setattr(agora_client, "get_settings", lambda: make_settings(agora_app_id=None, agora_customer_id=None))
    r = api.post("/api/agora/sessions")
    assert r.status_code == 503 and "not configured" in r.json()["detail"]["message"]
    assert "AGORA_" not in r.text  # variable names stay in the server log


@pytest.mark.parametrize("join, status", [((500, {}), 502), ((429, {}), 429), ((401, {}), 502),
                                           ((0, httpx.ReadTimeout("t")), 504), ((200, {"agent_id": AGENT_ID, "status": "FAILED"}), 502)])
def test_api_start_session_agora_failures(use, join, status):
    use(FakeAgora(join=join))
    r = api.post("/api/agora/sessions")
    assert r.status_code == status and set(r.json()["detail"]) == {"message"}


def test_api_stop_session(use):
    fake = use()
    r = api.post(f"/api/agora/sessions/{AGENT_ID}/stop")
    assert r.status_code == 200 and r.json() == {"session_id": AGENT_ID, "status": "stopped"}
    assert len(fake.requests) == 1


def test_api_stop_session_failures(use):
    use(FakeAgora(leave=(500, {})))
    assert api.post(f"/api/agora/sessions/{AGENT_ID}/stop").status_code == 502
    use(FakeAgora(leave=(404, {})))
    r = api.post(f"/api/agora/sessions/{AGENT_ID}/stop")
    assert r.status_code == 404 and "stopped" not in r.text.replace("already ended", "")
    use(FakeAgora(leave=(0, httpx.ReadTimeout("t"))))
    assert api.post(f"/api/agora/sessions/{AGENT_ID}/stop").status_code == 504


def test_api_stop_session_invalid_input(use):
    fake = use()
    for bad in ("short", "a" * 65, "bad%20id%20here", "semi;colon;id"):
        assert api.post(f"/api/agora/sessions/{bad}/stop").status_code == 422
    assert api.get(f"/api/agora/sessions/{AGENT_ID}/stop").status_code == 405
    assert fake.requests == []


# ------------------------------------------------------------------ secret leakage
def assert_no_secrets(text: str):
    for secret in SECRETS:
        assert secret not in text, "secret leaked"


def test_success_responses_do_not_contain_credentials(use):
    use()
    start = api.post("/api/agora/sessions")
    stop = api.post(f"/api/agora/sessions/{AGENT_ID}/stop")
    assert_no_secrets(start.text + stop.text)


def test_error_responses_and_logs_do_not_leak_even_if_agora_echoes_secrets(use, caplog):
    echo = {"reason": f"bad auth Basic {BASIC} cert {CERT}", "detail": f"{CUSTOMER_ID}/{CUSTOMER_SECRET}"}
    use(FakeAgora(join=(400, echo), leave=(500, echo)))
    with caplog.at_level(logging.DEBUG):
        r1 = api.post("/api/agora/sessions")
        r2 = api.post(f"/api/agora/sessions/{AGENT_ID}/stop")
    assert r1.status_code == 502
    assert_no_secrets(r1.text + r2.text + caplog.text)


def test_unexpected_exceptions_do_not_leak(monkeypatch, caplog):
    def boom(**k): raise RuntimeError(f"failed with {CERT} {CUSTOMER_SECRET}")
    monkeypatch.setattr(svc, "start_session", boom)
    with caplog.at_level(logging.DEBUG):
        r = api.post("/api/agora/sessions")
    assert r.status_code == 500 and r.json()["detail"]["message"] == "Unexpected server error."
    assert CERT not in r.text and CUSTOMER_SECRET not in r.text


def test_join_request_body_and_logs_never_contain_the_app_certificate_or_rest_credentials(fake, caplog):
    with caplog.at_level(logging.DEBUG):
        svc.start_session(client=fake.client())
    assert_no_secrets(fake.requests[0].content.decode() + caplog.text)
    assert CERT not in fake.requests[0].content.decode()
