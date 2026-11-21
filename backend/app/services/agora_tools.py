"""Agora Conversational AI custom tools for WorkPilot's four backend agent tools.

Agora's engine lets the LLM call our HTTPS endpoints. This module only *describes* those endpoints in Agora's
wire format; it contains no tool logic. The tools themselves stay in app/api/routes/agent_tools.py and call the
existing services.

Official reference (checked against the current docs):
    https://docs.agora.io/en/ai/build/tools/custom-tools
    https://docs.agora.io/en/api-reference/api-ref/conversational-ai/join   (llm.tools, llm.template_variables,
                                                                             advanced_features.enable_tools)

Rules from those docs that shape this file:
  * Tool names: start with a letter, letters and digits only (NO underscores), <= 64 chars, case-insensitive
    unique, no `mcp` prefix, not `ragsearch_tool`. Our snake_case backend names are therefore mapped to camelCase.
  * `server.body` leaves must be constants or ONE complete placeholder ({{args.x}}, {{template_variables.x}},
    {{tool_call_id}}); {{args.*}} is not allowed in headers. A placeholder whose variable is missing or null makes
    the call fail with UnresolvedTemplate WITHOUT reaching our server. So every parameter that the body maps is
    declared `required` for the model; optional-in-the-backend fields are still always sent (see _SPECS).
  * Parameter schemas should stay simple: no $ref/$defs/anyOf/format/pattern/min/max (model support varies).
  * Header values are treated as secret by Agora (hidden from the LLM, logs and TTS). The shared secret travels as
    a `template_variables` value referenced from a header, i.e. as a complete header value.
"""
import ipaddress
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from app.core.config import ConfigError
from app.core.security import TOOL_SECRET_HEADER
from app.schemas.agent import TOOL_DEFINITIONS

# Name of the llm.template_variables entry that carries the secret, and how a header references it.
SECRET_VARIABLE = "workpilot_tool_secret"
SECRET_PLACEHOLDER = "{{template_variables.%s}}" % SECRET_VARIABLE

TOOLS_PATH = "/api/agent/tools"
MAX_TOOLS = 32
MIN_SECRET_LENGTH = 16
MAX_SCHEMA_BYTES = 64 * 1024

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")
_PLACEHOLDER_RE = re.compile(r"^\{\{(args\.[A-Za-z_][A-Za-z0-9_]*|template_variables\.[A-Za-z_][A-Za-z0-9_]*|tool_call_id)\}\}$")
_ALLOWED_SCHEMA_KEYS = {"type", "description", "enum", "items", "properties", "required", "additionalProperties"}
_RESERVED_NAMES = {"ragsearch_tool"}
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal")


@dataclass(frozen=True)
class _Spec:
    agora_name: str                     # camelCase name the LLM sees
    timeout_ms: int                     # Agora allows 1000-100000
    params: tuple[str, ...]             # backend input fields exposed to the LLM AND mapped into the body
    param_docs: dict = field(default_factory=dict)   # descriptions that replace/complete the backend's
    description: str | None = None      # replaces the backend description when set


# Why every exposed parameter is "required" here (even where the backend has a default): the body maps each one
# with a {{args.x}} placeholder, and an omitted optional argument would make Agora drop the call. Backend
# defaults (category "general", priority "medium", empty context) are therefore stated to the model instead.
# Backend fields that are not listed (e.g. related_ticket_id, a UUID the voice user can never say) are simply
# not exposed, so the LLM cannot send them.
_SPECS: dict[str, _Spec] = {
    "search_knowledge": _Spec(
        agora_name="searchKnowledge",
        timeout_ms=20_000,  # embedding + vector search + Gemini answer
        params=("question",),
    ),
    "create_ticket": _Spec(
        agora_name="createTicket",
        timeout_ms=10_000,
        params=("title", "description", "category", "priority", "confirmed"),
        description=(
            "Create a support ticket in two steps. ALWAYS pass confirmed. Step 1: call with confirmed=false to get "
            "a preview; nothing is created. Read the title, category and priority back to the user and ask them to "
            "confirm. Step 2: only after the user has clearly said yes, call again with the same details and "
            "confirmed=true. Tell the user a ticket exists only when the response has data.created=true, and quote "
            "data.ticket.ticket_number from the response."
        ),
        param_docs={
            "category": "Ticket category, e.g. network, hardware, access, software. Use general if unsure.",
            "priority": "One of low, medium, high, critical. Use medium if the user did not indicate urgency.",
            "confirmed": (
                "false = only preview, nothing is created. true = create the ticket; use true ONLY after the user "
                "has explicitly confirmed the previewed details."
            ),
        },
    ),
    "get_ticket_status": _Spec(
        agora_name="getTicketStatus",
        timeout_ms=8_000,
        params=("ticket_id_or_number",),
    ),
    "generate_document": _Spec(
        agora_name="generateDocument",
        timeout_ms=30_000,  # Gemini writes the whole document before it is saved
        params=("title", "document_type", "description", "context"),
        param_docs={
            "title": "Short title for the document.",
            "document_type": "incident_report for an incident report, technical_summary for a technical summary.",
            "description": "The facts the user has told you: what happened or what the topic is. Do not add anything the user did not say.",
            "context": "Further facts from the conversation (symptoms, actions taken, resolution). Use an empty string if there are none.",
        },
    ),
}

# backend tool name -> Agora tool name (exported for tests and docs)
TOOL_NAME_MAP: dict[str, str] = {backend: spec.agora_name for backend, spec in _SPECS.items()}


@dataclass(frozen=True)
class AgoraToolsConfig:
    """What the Agora join payload needs. `template_variables` holds the secret, so it is kept out of repr()."""

    tools: list
    template_variables: dict = field(repr=False)


# --------------------------------------------------------------------------- configuration checks
def validate_base_url(raw: str | None) -> str:
    """Return the normalised public base URL, or raise ConfigError. Messages never echo the value."""
    var = "AGORA_TOOLS_BASE_URL"
    if not (raw or "").strip():
        raise ConfigError(
            f"{var} is not set. Set it in backend/.env to the public https:// URL of this backend "
            f"(a deployed URL or an HTTPS tunnel); Agora's cloud cannot reach localhost."
        )
    try:
        parts = urlsplit(raw.strip())
        host, _port = parts.hostname, parts.port  # .port raises ValueError for a bad port
    except ValueError:
        raise ConfigError(f"{var} is not a valid URL.") from None
    if parts.scheme.lower() != "https":
        raise ConfigError(f"{var} must start with https:// (Agora only calls HTTPS tool endpoints).")
    if not host:
        raise ConfigError(f"{var} must include a host name, for example your-backend.example.com.")
    if parts.username is not None or parts.password is not None:
        raise ConfigError(f"{var} must not contain a username or password.")
    if parts.query or parts.fragment:
        raise ConfigError(f"{var} must not contain a query string or fragment.")
    if not _is_public_host(host):
        raise ConfigError(f"{var} must be publicly reachable: localhost, private and internal addresses are not allowed.")
    return urlunsplit(("https", parts.netloc, parts.path.rstrip("/"), "", ""))


def _is_public_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass  # not an IP literal: a name
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        return False
    return "." in host  # single-label names (e.g. a docker service name) are never public


def validate_secret(raw: str | None) -> str:
    """Return the stripped shared secret, or raise ConfigError. Messages never echo the value."""
    var = "AGORA_TOOLS_SHARED_SECRET"
    secret = (raw or "").strip()
    if not secret:
        raise ConfigError(
            f"{var} is not set. Generate one, e.g. python -c \"import secrets; print(secrets.token_urlsafe(32))\", "
            f"and put it in backend/.env."
        )
    if len(secret) < MIN_SECRET_LENGTH:
        raise ConfigError(f"{var} must be at least {MIN_SECRET_LENGTH} characters long.")
    if not re.fullmatch(r"[\x21-\x7e]+", secret):
        raise ConfigError(f"{var} may only contain visible ASCII characters (no spaces) because it is sent as an HTTP header.")
    return secret


# --------------------------------------------------------------------------- building the tools
def _simple_schema(prop: dict, description: str | None) -> dict:
    """Reduce a backend JSON-Schema property to the simple subset Agora/OpenAI function calling handles reliably."""
    node = dict(prop)
    if "anyOf" in node:  # pydantic's `X | None`  ->  X
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        if len(options) != 1:
            raise ConfigError("Unsupported tool parameter schema (anyOf).")
        node = {**options[0], **{k: v for k, v in node.items() if k == "description"}}
    if "$ref" in node or "allOf" in node or "oneOf" in node:
        raise ConfigError("Unsupported tool parameter schema ($ref/allOf/oneOf).")
    out = {k: v for k, v in node.items() if k in ("type", "description", "enum", "items")}
    if description:
        out["description"] = description
    if "type" not in out or not out.get("description"):
        raise ConfigError("Every exposed tool parameter needs a type and a description.")
    return out


def _build_tool(definition: dict, spec: _Spec, base_url: str) -> dict:
    backend_props = definition["parameters"]["properties"]
    unknown = [p for p in spec.params if p not in backend_props]
    if unknown:
        raise ConfigError(f"Tool {definition['name']} exposes unknown parameters: {', '.join(unknown)}.")
    return {
        "type": "function",
        "function": {
            "name": spec.agora_name,
            "description": spec.description or definition["description"],
            "parameters": {
                "type": "object",
                "properties": {p: _simple_schema(backend_props[p], spec.param_docs.get(p)) for p in spec.params},
                "required": list(spec.params),
                "additionalProperties": False,
            },
        },
        "execution": {"mode": "sync"},
        "server": {
            "method": "POST",
            "url": f"{base_url}{TOOLS_PATH}/{definition['name']}",
            "headers": {
                TOOL_SECRET_HEADER: SECRET_PLACEHOLDER,
                "Content-Type": "application/json",
            },
            "body": {p: "{{args.%s}}" % p for p in spec.params},
            "timeout_ms": spec.timeout_ms,
        },
    }


def build_tools_config(settings) -> AgoraToolsConfig:
    """Validate the tool settings and build Agora's `llm.tools` + `llm.template_variables`. Raises ConfigError."""
    base_url = validate_base_url(settings.agora_tools_base_url)
    secret = validate_secret(settings.agora_tools_shared_secret)
    definitions = {d["name"]: d for d in TOOL_DEFINITIONS}
    if set(definitions) != set(_SPECS):
        raise ConfigError("Agora tool mapping is out of sync with the backend tool definitions.")
    tools = [_build_tool(definitions[name], _SPECS[name], base_url) for name in _SPECS]
    template_variables = {SECRET_VARIABLE: secret}
    validate_tools(tools, template_variables)
    return AgoraToolsConfig(tools=tools, template_variables=template_variables)


# --------------------------------------------------------------------------- validation against Agora's rules
def validate_tools(tools: list, template_variables: dict) -> None:
    """Check a tool list against the limits in Agora's custom-tools documentation. Raises ConfigError."""
    if len(tools) > MAX_TOOLS:
        raise ConfigError(f"Agora supports at most {MAX_TOOLS} tools.")
    seen: set[str] = set()
    for tool in tools:
        fn, server = tool.get("function", {}), tool.get("server", {})
        name = fn.get("name", "")
        if tool.get("type") != "function":
            raise ConfigError("Agora tools must have type 'function'.")
        if not _NAME_RE.match(name) or name.lower().startswith("mcp") or name.lower() in _RESERVED_NAMES:
            raise ConfigError(f"Invalid Agora tool name: {name!r}.")
        if name.lower() in seen:
            raise ConfigError(f"Duplicate Agora tool name: {name!r}.")
        seen.add(name.lower())
        if not fn.get("description"):
            raise ConfigError(f"Tool {name} needs a description.")
        if tool.get("execution", {"mode": "sync"}).get("mode") != "sync":
            raise ConfigError("Only synchronous Agora tools are supported.")

        params = fn.get("parameters", {})
        if params.get("type") != "object" or not set(params.get("required", [])) <= set(params.get("properties", {})):
            raise ConfigError(f"Tool {name} has an invalid parameter schema.")
        _check_schema_keys(params)
        if len(json.dumps(params).encode()) > MAX_SCHEMA_BYTES:
            raise ConfigError(f"Tool {name}: parameter schema is too large.")

        if server.get("method") not in ("GET", "POST"):
            raise ConfigError(f"Tool {name}: only GET and POST are supported.")
        if not str(server.get("url", "")).startswith("https://"):
            raise ConfigError(f"Tool {name}: the endpoint must be an https:// URL.")
        if not 1000 <= server.get("timeout_ms", 10_000) <= 100_000:
            raise ConfigError(f"Tool {name}: timeout_ms must be between 1000 and 100000.")
        headers = server.get("headers", {})
        if len(headers) > 32:
            raise ConfigError(f"Tool {name}: too many headers.")
        if server["method"] == "GET" and "body" in server:
            raise ConfigError(f"Tool {name}: a GET tool cannot have a body.")

        declared = set(params.get("properties", {}))
        for value in headers.values():
            _check_placeholder(name, value, declared, template_variables, allow_args=False)
        _check_body(name, server.get("body"), declared, template_variables)


def _check_schema_keys(node) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in _ALLOWED_SCHEMA_KEYS:
                raise ConfigError(f"Unsupported keyword in a tool parameter schema: {key!r}.")
            if key == "properties":
                for sub in value.values():
                    _check_schema_keys(sub)
            elif key == "items":
                _check_schema_keys(value)


def _check_body(tool: str, node, declared: set, template_variables: dict) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _check_body(tool, value, declared, template_variables)
    elif isinstance(node, list):
        for value in node:
            _check_body(tool, value, declared, template_variables)
    elif isinstance(node, str):
        _check_placeholder(tool, node, declared, template_variables, allow_args=True)


def _check_placeholder(tool: str, value, declared: set, template_variables: dict, *, allow_args: bool) -> None:
    if not isinstance(value, str) or "{{" not in value:
        return  # constant
    match = _PLACEHOLDER_RE.match(value)
    if not match:
        raise ConfigError(f"Tool {tool}: a template placeholder must be the complete value (no concatenation).")
    ref = match.group(1)
    if ref.startswith("args."):
        if not allow_args:
            raise ConfigError(f"Tool {tool}: {{{{args.*}}}} is not allowed in headers.")
        if ref.removeprefix("args.") not in declared:
            raise ConfigError(f"Tool {tool}: the body references an undeclared parameter.")
    elif ref.startswith("template_variables.") and ref.removeprefix("template_variables.") not in template_variables:
        raise ConfigError(f"Tool {tool}: a template variable is referenced but not defined.")
