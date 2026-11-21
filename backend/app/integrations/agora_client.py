"""Thin client for the Agora Conversational AI REST API (v2).

Uses the documented endpoints with Basic auth (Customer ID + Customer Secret):
    POST {base}/projects/{appid}/join                    start an agent  -> {agent_id, create_ts, status}
    POST {base}/projects/{appid}/agents/{agent_id}/leave stop an agent   -> {}
Docs: https://docs.agora.io/en/conversational-ai/rest-api/agent/join

Only this module talks to Agora. Request bodies contain an RTC token and headers contain the Basic
credentials, so neither is ever logged, and any text coming back from Agora is scrubbed of known secrets.
"""
import base64
import logging
from urllib.parse import quote

import httpx

from app.core.config import ConfigError, Settings, get_settings

logger = logging.getLogger("workpilot.agora")

_REQUIRED = {
    "agora_app_id": "AGORA_APP_ID",
    "agora_app_certificate": "AGORA_APP_CERTIFICATE",
    "agora_customer_id": "AGORA_CUSTOMER_ID",
    "agora_customer_secret": "AGORA_CUSTOMER_SECRET",
}


class AgoraError(RuntimeError):
    """A failed Agora call. The message is safe to show to API clients."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def check_configured(settings: Settings | None = None) -> Settings:
    """Return settings if every Agora credential is present and well-formed, else raise ConfigError.

    Messages name the environment variables only, never their values.
    """
    settings = settings or get_settings()
    missing = [env for attr, env in _REQUIRED.items() if not (getattr(settings, attr) or "").strip()]
    if missing:
        raise ConfigError(f"Agora is not configured. Set in backend/.env: {', '.join(missing)}.")
    bad = []
    for attr, env in (("agora_app_id", "AGORA_APP_ID"), ("agora_app_certificate", "AGORA_APP_CERTIFICATE")):
        value = getattr(settings, attr).strip()
        try:
            ok = len(value) == 32 and bytes.fromhex(value) is not None
        except ValueError:
            ok = False
        if not ok:
            bad.append(env)
    if bad:
        raise ConfigError(f"{', '.join(bad)} must be 32 hexadecimal characters (check for stray spaces or a truncated paste).")
    return settings


class AgoraClient:
    def __init__(self, settings: Settings | None = None, *, transport: httpx.BaseTransport | None = None):
        self._s = check_configured(settings)
        self._transport = transport  # tests inject httpx.MockTransport; production leaves this None
        raw = f"{self._s.agora_customer_id.strip()}:{self._s.agora_customer_secret.strip()}"
        self._auth = "Basic " + base64.b64encode(raw.encode()).decode()
        self._secrets = [v for v in (
            self._s.agora_app_certificate, self._s.agora_customer_secret, self._s.agora_customer_id,
            self._auth, self._auth.removeprefix("Basic "),
        ) if v]

    @property
    def settings(self) -> Settings:
        return self._s

    @property
    def app_id(self) -> str:
        return self._s.agora_app_id.strip()

    # ------------------------------------------------------------------ public API
    def start_agent(self, payload: dict) -> dict:
        """POST /join. Returns {"agent_id", "status", "create_ts"} once Agora has answered with an agent id."""
        data = self._request("start agent", "POST", "/join", payload)
        agent_id = data.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            logger.error("Agora join response had no agent_id")
            raise AgoraError("Agora returned an unexpected response (no agent id).", 502)
        status = data.get("status")
        return {"agent_id": agent_id, "status": status if isinstance(status, str) else None,
                "create_ts": data.get("create_ts")}

    def stop_agent(self, agent_id: str) -> None:
        """POST /agents/{id}/leave. Returns only after Agora answered 2xx; raises AgoraError otherwise."""
        path = f"/agents/{quote(agent_id, safe='')}/leave"
        try:
            self._request("stop agent", "POST", path, None)
        except AgoraError as exc:
            if exc.status_code == 404:
                raise AgoraError("Session not found. It may have already ended.", 404) from None
            raise

    # ------------------------------------------------------------------ internals
    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    def _request(self, op: str, method: str, path: str, body: dict | None) -> dict:
        url = f"{self._s.agora_api_base_url.rstrip('/')}/projects/{self.app_id}{path}"
        headers = {"Authorization": self._auth, "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self._s.agora_http_timeout_seconds, transport=self._transport) as http:
                response = http.request(method, url, headers=headers, json=body)
        except httpx.TimeoutException:
            logger.error("Agora %s timed out", op)
            raise AgoraError("Agora did not respond in time.", 504) from None
        except httpx.HTTPError as exc:
            logger.error("Agora %s request failed: %s", op, type(exc).__name__)  # type only: messages can contain URLs
            raise AgoraError("Could not reach Agora.", 502) from None

        if response.is_success:
            if not response.content.strip():
                return {}
            try:
                data = response.json()
            except ValueError:
                logger.error("Agora %s returned a non-JSON body", op)
                raise AgoraError("Agora returned an unexpected response.", 502) from None
            if not isinstance(data, dict):
                raise AgoraError("Agora returned an unexpected response.", 502)
            return data

        reason = self._error_reason(response)
        logger.error("Agora %s failed: HTTP %s %s", op, response.status_code, reason)
        code = response.status_code
        if code in (401, 403):
            raise AgoraError("Agora rejected the configured credentials. Check the AGORA_* settings.", 502)
        if code == 404:
            raise AgoraError("Agora could not find the requested resource.", 404)
        if code == 429:
            raise AgoraError("Agora is rate limiting requests. Try again shortly.", 429)
        if code in (400, 409, 422):
            raise AgoraError(f"Agora rejected the request{': ' + reason if reason else '.'}", 502)
        raise AgoraError("Agora returned an error. Try again later.", 502)

    def _error_reason(self, response: httpx.Response) -> str:
        """Agora's `reason`/`detail` text (documented error shape), scrubbed and truncated."""
        try:
            data = response.json()
        except ValueError:
            return ""
        if not isinstance(data, dict):
            return ""
        text = " - ".join(str(data[k]) for k in ("reason", "detail") if data.get(k))
        return self._scrub(text)[:200]


def get_client() -> AgoraClient:
    return AgoraClient()
