"""Shared test setup."""
import types

import pytest


@pytest.fixture(autouse=True)
def no_tool_secret_unless_a_test_sets_one(monkeypatch):
    """Tool-route tests must not depend on a developer's real backend/.env.

    Settings() reads backend/.env, which will contain AGORA_TOOLS_SHARED_SECRET once voice is set up. Without this,
    the tool-behaviour tests (which send no auth header) would start returning 401 on that machine. Tests of the
    authentication itself set the secret explicitly (see the `tool_secret` fixture in test_agora_tools.py).
    """
    try:
        from app.api import dependencies
    except ImportError:  # fastapi/pydantic not installed: the tests that need them skip themselves
        return
    monkeypatch.setattr(dependencies, "get_settings", lambda: types.SimpleNamespace(agora_tools_shared_secret=None))
