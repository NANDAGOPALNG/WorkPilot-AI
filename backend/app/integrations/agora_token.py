"""Minimal RTC-only AccessToken2 ("007") builder, so no Agora SDK dependency is needed.

Mirrors the RTC part of Agora's official python3 token builder:
https://github.com/AgoraIO/Tools/tree/master/DynamicKey/AgoraDynamicKey/python3
Tokens must only ever be generated on the server: they are signed with the App Certificate.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
import zlib

MAX_EXPIRY_SECONDS = 86400

_SERVICE_RTC = 1
_PRIV_JOIN_CHANNEL = 1
_PRIV_PUBLISH_AUDIO = 2
_PRIV_PUBLISH_VIDEO = 3
_PRIV_PUBLISH_DATA = 4


def _u16(v: int) -> bytes:
    return struct.pack("<H", v)


def _u32(v: int) -> bytes:
    return struct.pack("<I", v)


def _string(b: bytes) -> bytes:
    return _u16(len(b)) + b


def _is_hex32(value: str) -> bool:
    if len(value) != 32:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def build_rtc_token(app_id: str, app_certificate: str, channel: str, uid: int, expire_seconds: int) -> str:
    """Token letting `uid` join `channel` and publish audio/data until it expires `expire_seconds` from now."""
    # Messages never include the credential values, only which one is wrong.
    if not _is_hex32(app_id) or not _is_hex32(app_certificate):
        raise ValueError("app_id and app_certificate must each be 32 hexadecimal characters.")
    if not channel or len(channel.encode()) > 64:
        raise ValueError("channel must be 1-64 bytes.")
    if not 1 <= expire_seconds <= MAX_EXPIRY_SECONDS:
        raise ValueError(f"expire_seconds must be between 1 and {MAX_EXPIRY_SECONDS}.")
    if isinstance(uid, bool) or not isinstance(uid, int) or uid < 1:
        raise ValueError("uid must be a positive integer.")

    privileges = {_PRIV_JOIN_CHANNEL: expire_seconds, _PRIV_PUBLISH_AUDIO: expire_seconds,
                  _PRIV_PUBLISH_VIDEO: expire_seconds, _PRIV_PUBLISH_DATA: expire_seconds}
    privilege_map = _u16(len(privileges)) + b"".join(_u16(k) + _u32(privileges[k]) for k in sorted(privileges))
    service = _u16(_SERVICE_RTC) + privilege_map + _string(channel.encode()) + _string(str(uid).encode())

    issue_ts = int(time.time())
    salt = secrets.SystemRandom().randint(1, 99999999)
    signing_key = hmac.new(_u32(issue_ts), app_certificate.encode(), hashlib.sha256).digest()
    signing_key = hmac.new(_u32(salt), signing_key, hashlib.sha256).digest()

    signing_info = _string(app_id.encode()) + _u32(issue_ts) + _u32(expire_seconds) + _u32(salt) + _u16(1) + service
    signature = hmac.new(signing_key, signing_info, hashlib.sha256).digest()
    return "007" + base64.b64encode(zlib.compress(_string(signature) + signing_info)).decode()
