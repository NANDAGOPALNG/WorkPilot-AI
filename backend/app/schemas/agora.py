import re

from pydantic import BaseModel

# Agora agent ids look like "1NT29X10YHxxxxxWJOXLYHNYB". Reject anything else before it reaches Agora.
SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"
SESSION_ID_RE = re.compile(SESSION_ID_PATTERN)


class StartSessionResponse(BaseModel):
    """Everything a frontend RTC client needs to join. No REST credentials or App Certificate."""

    session_id: str            # Agora agent id; send it back to stop the session
    status: str                # as reported by Agora: STARTING or RUNNING
    app_id: str                # public identifier, required by the RTC SDK
    channel: str
    user_uid: int              # join the channel with this uid
    agent_uid: int
    rtc_token: str             # short-lived token for (channel, user_uid)
    token_expires_in_seconds: int
    idle_timeout_seconds: int  # the agent leaves this long after the user does


class StopSessionResponse(BaseModel):
    session_id: str
    status: str  # "stopped", only returned after Agora confirmed the stop
