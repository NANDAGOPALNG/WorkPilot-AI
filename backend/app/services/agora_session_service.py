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

logger = logging.getLogger("workpilot.agora")

# Statuses (from Agora's join docs) that confirm the agent is coming up / up. Anything else is not "active".
ACCEPTED_START_STATUSES = ("STARTING", "RUNNING")

SYSTEM_PROMPT = (
    "You are WorkPilot AI, a friendly voice assistant for employees. Keep replies short and conversational, "
    "suitable for being spoken aloud. You are not yet connected to company documents or the ticketing system, "
    "so you cannot look up policies, create tickets or check ticket status. If asked, say so plainly and "
    "never pretend that you have performed an action or found information in company documents."
)


def get_client() -> AgoraClient:
    return agora_client.get_client()


def _new_ids() -> tuple[str, str, int]:
    channel = f"workpilot-{uuid.uuid4().hex}"        # 41 chars, unique per session
    agent_name = f"workpilot-agent-{uuid.uuid4().hex}"  # Agora requires a never-reused name
    user_uid = secrets.randbelow(2_000_000_000 - 2000) + 2000  # never equals the agent uid
    return channel, agent_name, user_uid


def _join_payload(settings, *, name: str, channel: str, token: str, user_uid: int) -> dict:
    """Request body for POST /join, using Agora's documented managed-mode ASR/LLM/TTS configuration."""
    return {
        "name": name,
        "properties": {
            "channel": channel,
            "token": token,
            "agent_rtc_uid": str(settings.agora_agent_uid),
            "remote_rtc_uids": [str(user_uid)],
            "enable_string_uid": False,
            "idle_timeout": settings.agora_idle_timeout_seconds,
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
                "max_history": 10,
                "params": {"model": settings.agora_llm_model},
            },
            "tts": {
                "credential_mode": "managed", "vendor": "minimax",
                "params": {"url": "wss://api.minimax.io/ws/v1/t2a_v2", "model": "speech-2.6-turbo",
                           "voice_setting": {"voice_id": settings.agora_tts_voice_id}},
            },
        },
    }


def start_session(*, client: AgoraClient | None = None) -> dict:
    """Create the channel, mint tokens, ask Agora to start the agent. Raises ConfigError / AgoraError."""
    client = client or get_client()  # raises ConfigError if Agora is not configured
    settings = client.settings
    channel, name, user_uid = _new_ids()
    ttl = settings.agora_token_ttl_seconds
    app_id, cert = client.app_id, settings.agora_app_certificate.strip()

    agent_token = build_rtc_token(app_id, cert, channel, settings.agora_agent_uid, ttl)
    user_token = build_rtc_token(app_id, cert, channel, user_uid, ttl)

    result = client.start_agent(_join_payload(settings, name=name, channel=channel, token=agent_token, user_uid=user_uid))
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
