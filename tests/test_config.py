"""Settings, which are read from the environment and must be replaceable in tests."""

from __future__ import annotations

import pytest

from merlin_mcp.config import LIBRARIES, MERLIN, Settings, get_library, get_settings
from merlin_mcp.errors import UnknownLibraryError


def test_defaults_are_sane() -> None:
    settings = Settings.from_env()
    assert settings.timeout == 30.0
    assert settings.index_ttl == 3600.0
    assert settings.page_ttl == 900.0
    assert settings.not_found_ttl == 60.0
    assert settings.max_response_bytes == 32 * 1024 * 1024
    assert settings.log_level == "WARNING"


def test_numeric_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERLIN_MCP_TIMEOUT", "5")
    monkeypatch.setenv("MERLIN_MCP_CACHE_TTL", "120")
    settings = Settings.from_env()
    assert settings.timeout == 5.0
    assert settings.index_ttl == 120.0
    # The page TTL tracks the index TTL when it would otherwise exceed it.
    assert settings.page_ttl == 120.0


def test_a_malformed_number_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERLIN_MCP_TIMEOUT", "not-a-number")
    assert Settings.from_env().timeout == 30.0


def test_the_dedicated_token_variable_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "generic")
    monkeypatch.setenv("MERLIN_MCP_GITHUB_TOKEN", "specific")
    assert Settings.from_env().github_token == "specific"


def test_the_generic_token_variable_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERLIN_MCP_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "generic")
    assert Settings.from_env().github_token == "generic"


def test_the_user_agent_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERLIN_MCP_USER_AGENT", "custom/1.0")
    assert Settings.from_env().user_agent == "custom/1.0"


def test_the_default_user_agent_identifies_the_server() -> None:
    assert Settings.from_env().user_agent.startswith("merlin-mcp/")


def test_get_settings_is_cached_but_clearable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERLIN_MCP_TIMEOUT", "7")
    get_settings.cache_clear()
    assert get_settings().timeout == 7.0
    assert get_settings() is get_settings()

    monkeypatch.setenv("MERLIN_MCP_TIMEOUT", "9")
    assert get_settings().timeout == 7.0  # still the cached instance
    get_settings.cache_clear()
    assert get_settings().timeout == 9.0


def test_get_library_defaults_to_merlin() -> None:
    assert get_library(None) is MERLIN
    assert get_library("") is MERLIN
    assert get_library("  PERCEVAL ") is LIBRARIES["perceval"]


def test_get_library_rejects_an_unknown_name() -> None:
    with pytest.raises(UnknownLibraryError, match="known libraries"):
        get_library("numpy")
