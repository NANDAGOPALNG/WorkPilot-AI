"""Small security helpers. No framework imports, so they are trivially testable."""
import hmac

# Header Agora's engine adds to every custom-tool request (see app/services/agora_tools.py).
TOOL_SECRET_HEADER = "X-WorkPilot-Tool-Secret"


def secrets_match(provided: str | None, expected: str | None) -> bool:
    """Constant-time comparison. False when either side is missing or empty.

    Both sides are compared as UTF-8 bytes, so a non-ASCII header value cannot raise.
    """
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
