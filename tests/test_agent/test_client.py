"""Port of claude-client tests."""

from __future__ import annotations

import pytest

from canon.agent.client import (
    AgentUnavailableError,
    ClaudeClient,
)


class TestClaudeClient:
    def test_unavailable_without_key(self):
        client = ClaudeClient(api_key="")
        assert not client.is_available

    def test_available_with_key(self):
        client = ClaudeClient(api_key="test-key")
        assert client.is_available

    def test_complete_raises_when_unavailable(self):
        client = ClaudeClient(api_key="")
        from canon.agent.client import AgentConfig

        with pytest.raises(AgentUnavailableError):
            client.complete("system", "user", AgentConfig())

    def test_unavailable_error_message(self):
        err = AgentUnavailableError()
        assert "ANTHROPIC_API_KEY" in str(err)
