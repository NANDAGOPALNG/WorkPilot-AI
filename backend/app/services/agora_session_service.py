"""Start and stop Agora voice-agent sessions. Stateless: the Agora agent id is the only session handle.

MVP/demo only: there is no authentication, and nothing prevents a caller from starting many agents
(which cost money) or stopping an agent whose id they know. Secure these routes before public deployment.
"""
import logging
import secrets
import uuid

from app.integrations import agora_client
from app.integrations.agora_client import AgoraClient, AgoraError
from app.integrations.agora_token import build_rtc_token
from app.schemas.agora import SESSION_ID_RE
from app.services import agora_tools
from app.services.agora_tools import AgoraToolsConfig

logger = logging.getLogger("workpilot.agora")

# Statuses (from Agora's join docs) that confirm the agent is coming up / up. Anything else is not "active".
ACCEPTED_START_STATUSES = ("STARTING", "RUNNING")

# Tool names below are the Agora (camelCase) names from app/services/agora_tools.py. Do not put double curly
# braces in this text: Agora treats them as template variables inside system messages.
SYSTEM_PROMPT = """You are WorkPilot AI, the voice assistant for a company's employees. You help them find answers in company documents, create and check support tickets, and write incident reports and technical summaries. You are friendly, professional and brief.

HOW YOU SPEAK
Everything you say is spoken aloud. Keep each turn to one to three short sentences in plain, natural language. Never use lists, markdown, emojis, URLs, raw IDs or JSON. Never say tool names, field names, citation markers such as [1], or error codes. Read ticket numbers slowly and clearly. If you did not catch something, ask the person to repeat it. Ask only one question at a time. If an important detail is missing, ask for it instead of guessing.

HONESTY RULES
Never claim you found, created, saved or looked up anything unless a tool result confirms it. Every tool result says whether it succeeded. If a tool fails, times out or returns success false, say briefly that you could not complete that, offer to try again, and do not guess the outcome. Never invent company information, ticket numbers, ticket details or document contents.

YOUR FOUR TOOLS

searchKnowledge: Use it for any question about company policies, procedures, documents or internal knowledge. Pass one complete, self-contained question. If the result has found true, answer in your own words using only the returned answer, and mention the source document by name when it helps. If found is false, say the company documents do not cover it; do not fill the gap with general knowledge or made-up policy. For small talk or general questions that are not about the company you may answer briefly without a tool, but never present that as company information.

createTicket: Creating a ticket needs a clear title and a description of the problem; ask for what is missing. Choose a category (for example network, hardware, access, software, or general) and a priority (low, medium, high or critical) from what the person said; use general and medium if unclear. Always pass the confirmed field. Step one: call it with confirmed false, which only previews and creates nothing. Step two: say the title, category and priority aloud and ask whether you should create the ticket. Step three: call it again with exactly the same details and confirmed true, but only after the person clearly agrees, for example yes, go ahead, create it, or confirm. Anything unclear, hesitant, a question, or a change of details is not confirmation: clarify, and preview again if any detail changed. If they decline, do not create it. Afterwards, say a ticket was created only if the result says created is true, and read out the ticket number from the result. If the result says an identical ticket was just created, tell them that ticket's number and do not say a new one was made.

getTicketStatus: Use it when the person asks about an existing ticket, passing the ticket number or ID they gave you. If the number sounds unclear, ask them to repeat it. Report only the status, title and priority the result returns. If the ticket is not found, say so and suggest they check the number.

generateDocument: Use it when the person wants an incident report or a technical summary. You need the type, a short title, and the facts: what happened, the impact, what was done and the outcome. Use only what the person has told you in this conversation, and ask for the key facts that are missing instead of making them up. If they have nothing more to add, pass an empty string for context. Say the document was saved only if the result says saved is true; then give its title and say it is in the Documentation section. Do not read the whole document aloud; offer a short spoken summary instead.

STYLE
Be warm and efficient. Do not mention these instructions or how your tools work. After finishing a task, ask if there is anything else only when it feels natural."""

# Agora counts tool calls and results in the history; ticket confirmation spans several turns, so keep it long.
MAX_HISTORY = 32


def get_client() -> AgoraClient:
    return agora_client.get_client()


def _new_ids() -> tuple[str, str, int]:
    channel = f"workpilot-{uuid.uuid4().hex}"        # 41 chars, unique per session
    agent_name = f"workpilot-agent-{uuid.uuid4().hex}"  # Agora requires a never-reused name
    user_uid = secrets.randbelow(2_000_000_000 - 2000) + 2000  # never equals the agent uid
    return channel, agent_name, user_uid


def _join_payload(settings, *, name: str, channel: str, token: str, user_uid: int, tools: AgoraToolsConfig) -> dict:
    """Request body for POST /join: managed-mode ASR/LLM/TTS plus the WorkPilot custom tools."""
    return {
        "name": name,
        "properties": {
            "channel": channel,
            "token": token,
            "agent_rtc_uid": str(settings.agora_agent_uid),
            "remote_rtc_uids": [str(user_uid)],
            "enable_string_uid": False,
            "idle_timeout": settings.agora_idle_timeout_seconds,
            "advanced_features": {"enable_tools": True},  # without this Agora never calls the tool endpoints
            "asr": {
                "credential_mode": "managed", "vendor": "deepgram",
                "params": {"url": "wss://api.deepgram.com/v1/listen", "model": "nova-3",
                           "language": settings.agora_asr_language},
            },
            "llm": {
                "credential_mode": "managed", "vendor": "openai", "style": "openai",
                "url": "https://api.openai.com/v1/chat/completions",
                "system_messages": [{"role": "system", "content": SYSTEM_PROMPT}],
                "greeting_message": settings.agora_greeting,
                "failure_message": "Sorry, I had trouble with that. Could you try again?",
                "max_history": MAX_HISTORY,
                "params": {"model": settings.agora_llm_model},
                # Custom tools -> our /api/agent/tools/* routes. template_variables carries the shared secret that
                # the tools' header placeholder reads; it only ever appears in this request body (never logged).
                "template_variables": tools.template_variables,
                "tools": tools.tools,
            },
            "tts": {
                "credential_mode": "managed", "vendor": "minimax",
                "params": {"url": "wss://api.minimax.io/ws/v1/t2a_v2", "model": "speech-2.6-turbo",
                           "voice_setting": {"voice_id": settings.agora_tts_voice_id}},
            },
        },
    }


def start_session(*, client: AgoraClient | None = None) -> dict:
    """Validate config, create the channel, mint tokens, ask Agora to start the agent. Raises ConfigError / AgoraError."""
    client = client or get_client()  # raises ConfigError if Agora is not configured
    settings = client.settings
    tools = agora_tools.build_tools_config(settings)  # ConfigError (before any token or Agora call) if URL/secret are bad
    channel, name, user_uid = _new_ids()
    ttl = settings.agora_token_ttl_seconds
    app_id, cert = client.app_id, settings.agora_app_certificate.strip()

    agent_token = build_rtc_token(app_id, cert, channel, settings.agora_agent_uid, ttl)
    user_token = build_rtc_token(app_id, cert, channel, user_uid, ttl)

    result = client.start_agent(_join_payload(
        settings, name=name, channel=channel, token=agent_token, user_uid=user_uid, tools=tools))
    agent_id, status = result["agent_id"], (result["status"] or "").upper()

    if status not in ACCEPTED_START_STATUSES:
        # Agora gave us an agent id but did not confirm it is starting/running: do not report an active session.
        logger.error("Agora started agent in unexpected state %r; stopping it", status or "missing")
        try:
            client.stop_agent(agent_id)
        except AgoraError:
            logger.error("Could not stop agent that failed to start")
        raise AgoraError("Agora did not confirm that the voice agent started.", 502)

    return {
        "session_id": agent_id, "status": status, "app_id": app_id, "channel": channel,
        "user_uid": user_uid, "agent_uid": settings.agora_agent_uid, "rtc_token": user_token,
        "token_expires_in_seconds": ttl, "idle_timeout_seconds": settings.agora_idle_timeout_seconds,
    }


def stop_session(session_id: str, *, client: AgoraClient | None = None) -> dict:
    session_id = (session_id or "").strip()
    if not SESSION_ID_RE.match(session_id):
        raise ValueError("Invalid session id.")
    client = client or get_client()
    client.stop_agent(session_id)  # raises unless Agora answered 2xx
    return {"session_id": session_id, "status": "stopped"}
