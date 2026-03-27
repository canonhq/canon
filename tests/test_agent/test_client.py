"""Port of claude-client tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from canon.agent.client import (
    AgentConfig,
    AgentUnavailableError,
    ClaudeClient,
)


class TestClaudeClient:
    def test_unavailable_without_key(self):
        client = ClaudeClient(api_key="")
        assert not client.is_available

    @patch("canon.agent.client.analytics.get_client", return_value=None)
    def test_available_with_key(self, _mock_get):
        client = ClaudeClient(api_key="test-key")
        assert client.is_available

    def test_complete_raises_when_unavailable(self):
        client = ClaudeClient(api_key="")

        with pytest.raises(AgentUnavailableError):
            client.complete("system", "user", AgentConfig())

    def test_unavailable_error_message(self):
        err = AgentUnavailableError()
        assert "ANTHROPIC_API_KEY" in str(err)

    @patch("canon.agent.client.analytics.get_client")
    def test_uses_posthog_wrapper_when_configured(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        mock_ph_cls = MagicMock()
        with patch("posthog.ai.anthropic.Anthropic", mock_ph_cls):
            client = ClaudeClient(api_key="test-key")
        assert client.is_available
        mock_ph_cls.assert_called_once_with(
            api_key="test-key", posthog_client=mock_get_client.return_value
        )

    @patch("canon.agent.client.analytics.get_client", return_value=None)
    def test_uses_vanilla_anthropic_when_posthog_absent(self, _mock_get):
        client = ClaudeClient(api_key="test-key")
        assert client.is_available
        assert not client._posthog_enabled
        # Should be a vanilla anthropic.Anthropic, not PostHog-wrapped
        import anthropic

        assert isinstance(client._client, anthropic.Anthropic)

    @patch("canon.agent.client.analytics.get_client")
    def test_falls_back_when_posthog_import_fails(self, mock_get_client):
        """If posthog.ai.anthropic import fails, fall back to vanilla client."""
        mock_get_client.return_value = MagicMock()
        with patch("builtins.__import__", side_effect=_import_blocker("posthog.ai.anthropic")):
            client = ClaudeClient(api_key="test-key")
        assert client.is_available
        assert not client._posthog_enabled

    @patch("canon.agent.client.analytics.get_client")
    def test_complete_passes_posthog_kwargs_when_enabled(self, mock_get_client):
        """When PostHog is configured, posthog_* kwargs are passed to messages.create()."""
        mock_get_client.return_value = MagicMock()
        mock_ph_cls = MagicMock()
        with patch("posthog.ai.anthropic.Anthropic", mock_ph_cls):
            client = ClaudeClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="result")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        client._client.messages.create = MagicMock(return_value=mock_response)

        client.complete("system", "user", AgentConfig(), org="acme")

        call_kwargs = client._client.messages.create.call_args[1]
        assert call_kwargs["posthog_distinct_id"] == "acme"
        assert call_kwargs["posthog_properties"] == {"feature": "pr_analysis"}
        assert call_kwargs["posthog_groups"] == {"organization": "acme"}

    @patch("canon.agent.client.analytics.get_client", return_value=None)
    def test_complete_omits_posthog_kwargs_when_disabled(self, _mock_get):
        """When PostHog is absent, no posthog_* kwargs are passed."""
        client = ClaudeClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="result")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        client._client.messages.create = MagicMock(return_value=mock_response)

        client.complete("system", "user", AgentConfig())

        call_kwargs = client._client.messages.create.call_args[1]
        assert "posthog_distinct_id" not in call_kwargs
        assert "posthog_properties" not in call_kwargs
        assert "posthog_groups" not in call_kwargs


def _import_blocker(blocked_module: str):
    """Return an __import__ side_effect that blocks a specific module."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _blocker(name, *args, **kwargs):
        if name == blocked_module:
            raise ImportError(f"Mocked: {name} not available")
        return real_import(name, *args, **kwargs)

    return _blocker
