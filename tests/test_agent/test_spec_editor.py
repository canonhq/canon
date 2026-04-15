"""Tests for AI-assisted spec section editing (spec_editor.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from canon.agent.client import AgentConfig, ClaudeClient
from canon.agent.spec_editor import (
    EXPAND_SYSTEM_PROMPT,
    GENERATE_ACS_SYSTEM_PROMPT,
    IMPROVE_SYSTEM_PROMPT,
    SPEC_EDITOR_CONFIG,
    _stream_completion,
    expand_section_stream,
    generate_acs_stream,
    improve_section_stream,
)


def _make_client(*, available: bool = True, api_key: str = "sk-test") -> ClaudeClient:
    """Create a ClaudeClient mock with configurable availability."""
    client = MagicMock(spec=ClaudeClient)
    client.is_available = available
    client.api_key = api_key if available else None
    return client


# ─── _stream_completion ───────────────────────────────────────────


class TestStreamCompletion:
    @pytest.mark.asyncio
    async def test_yields_unavailable_comment_when_no_api_key(self):
        """When ClaudeClient has no API key, yield a comment and return."""
        client = _make_client(available=False)

        chunks = []
        async for chunk in _stream_completion("system", "user msg", client):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "AI editing unavailable" in chunks[0]

    @pytest.mark.asyncio
    async def test_yields_unavailable_when_api_key_is_none(self):
        """When is_available is True but api_key is None, still yields unavailable."""
        client = _make_client(available=True, api_key="sk-test")
        client.api_key = None

        chunks = []
        async for chunk in _stream_completion("system", "user msg", client):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "AI editing unavailable" in chunks[0]

    @pytest.mark.asyncio
    async def test_streams_text_from_anthropic(self):
        """Successful streaming yields text chunks from the API."""
        client = _make_client()

        # Build a mock async context manager chain for the streaming API
        mock_text_stream = AsyncStreamMock(["Hello ", "world!"])

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_text_stream)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_async_anthropic = AsyncMock()
        mock_async_anthropic.__aenter__ = AsyncMock(return_value=mock_async_anthropic)
        mock_async_anthropic.__aexit__ = AsyncMock(return_value=False)
        mock_async_anthropic.messages.stream = MagicMock(return_value=mock_stream_ctx)

        with patch(
            "canon.agent.spec_editor.anthropic.AsyncAnthropic",
            return_value=mock_async_anthropic,
        ):
            chunks = []
            async for chunk in _stream_completion("system prompt", "user message", client):
                chunks.append(chunk)

        assert chunks == ["Hello ", "world!"]

    @pytest.mark.asyncio
    async def test_uses_custom_config(self):
        """When a custom AgentConfig is provided, it's used instead of the default."""
        client = _make_client()
        custom_config = AgentConfig(
            model="claude-opus-4-6", max_output_tokens=8000, temperature=0.5
        )

        mock_text_stream = AsyncStreamMock(["ok"])
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_text_stream)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_async_anthropic = AsyncMock()
        mock_async_anthropic.__aenter__ = AsyncMock(return_value=mock_async_anthropic)
        mock_async_anthropic.__aexit__ = AsyncMock(return_value=False)
        mock_async_anthropic.messages.stream = MagicMock(return_value=mock_stream_ctx)

        with patch(
            "canon.agent.spec_editor.anthropic.AsyncAnthropic",
            return_value=mock_async_anthropic,
        ):
            async for _ in _stream_completion("sys", "msg", client, config=custom_config):
                pass

        call_kwargs = mock_async_anthropic.messages.stream.call_args[1]
        assert call_kwargs["model"] == "claude-opus-4-6"
        assert call_kwargs["max_tokens"] == 8000
        assert call_kwargs["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_tracks_ai_generation_after_stream(self):
        """After streaming completes, $ai_generation is emitted."""
        client = _make_client()

        mock_text_stream = AsyncStreamMock(["Hello ", "world!"], input_tokens=100, output_tokens=50)

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_text_stream)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_async_anthropic = AsyncMock()
        mock_async_anthropic.__aenter__ = AsyncMock(return_value=mock_async_anthropic)
        mock_async_anthropic.__aexit__ = AsyncMock(return_value=False)
        mock_async_anthropic.messages.stream = MagicMock(return_value=mock_stream_ctx)

        with (
            patch(
                "canon.agent.spec_editor.anthropic.AsyncAnthropic",
                return_value=mock_async_anthropic,
            ),
            patch("canon.agent.spec_editor.analytics.track_ai_generation") as mock_track,
        ):
            chunks = []
            async for chunk in _stream_completion(
                "system", "user", client, feature="spec_edit", action="improve"
            ):
                chunks.append(chunk)

        assert chunks == ["Hello ", "world!"]
        mock_track.assert_called_once()
        call_kwargs = mock_track.call_args[1]
        assert call_kwargs["model"] == SPEC_EDITOR_CONFIG.model
        assert call_kwargs["input_tokens"] == 100
        assert call_kwargs["output_tokens"] == 50
        assert call_kwargs["feature"] == "spec_edit"
        assert call_kwargs["action"] == "improve"

    @pytest.mark.asyncio
    async def test_analytics_failure_does_not_break_streaming(self):
        """If get_final_message() raises, streaming still works."""
        client = _make_client()

        mock_text_stream = AsyncStreamMock(["Hello ", "world!"])
        # Override get_final_message to raise
        mock_text_stream.get_final_message = AsyncMock(side_effect=RuntimeError("boom"))

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_text_stream)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_async_anthropic = AsyncMock()
        mock_async_anthropic.__aenter__ = AsyncMock(return_value=mock_async_anthropic)
        mock_async_anthropic.__aexit__ = AsyncMock(return_value=False)
        mock_async_anthropic.messages.stream = MagicMock(return_value=mock_stream_ctx)

        with patch(
            "canon.agent.spec_editor.anthropic.AsyncAnthropic",
            return_value=mock_async_anthropic,
        ):
            chunks = []
            async for chunk in _stream_completion("system", "user", client):
                chunks.append(chunk)

        # Streaming still yields all chunks despite analytics failure
        assert chunks == ["Hello ", "world!"]

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        """On anthropic.APIError, yields an error comment."""
        client = _make_client()

        mock_async_anthropic = AsyncMock()
        mock_async_anthropic.__aenter__ = AsyncMock(return_value=mock_async_anthropic)
        mock_async_anthropic.__aexit__ = AsyncMock(return_value=False)
        mock_async_anthropic.messages.stream = MagicMock(
            side_effect=anthropic.APIError(
                message="rate limit exceeded",
                request=MagicMock(),
                body=None,
            )
        )

        with patch(
            "canon.agent.spec_editor.anthropic.AsyncAnthropic",
            return_value=mock_async_anthropic,
        ):
            chunks = []
            async for chunk in _stream_completion("sys", "msg", client):
                chunks.append(chunk)

        assert len(chunks) == 1
        assert "Editing failed" in chunks[0]


# ─── improve_section_stream ──────────────────────────────────────


class TestImproveSectionStream:
    @pytest.mark.asyncio
    async def test_passes_correct_system_prompt(self):
        """improve_section_stream uses IMPROVE_SYSTEM_PROMPT."""
        client = _make_client()
        captured_args = {}

        async def mock_stream(system_prompt, user_message, client_arg, config=None, **kwargs):
            captured_args["system"] = system_prompt
            captured_args["message"] = user_message
            yield "improved"

        with patch("canon.agent.spec_editor._stream_completion", side_effect=mock_stream):
            async for _ in improve_section_stream("Auth", "Login flow", [], client):
                pass

        assert captured_args["system"] == IMPROVE_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_includes_title_and_content_in_message(self):
        """User message includes the section title and content."""
        client = _make_client()
        captured_args = {}

        async def mock_stream(system_prompt, user_message, client_arg, config=None, **kwargs):
            captured_args["message"] = user_message
            yield "improved"

        with patch("canon.agent.spec_editor._stream_completion", side_effect=mock_stream):
            async for _ in improve_section_stream("Auth", "Login flow text", [], client):
                pass

        assert "Section: Auth" in captured_args["message"]
        assert "Login flow text" in captured_args["message"]

    @pytest.mark.asyncio
    async def test_includes_acceptance_criteria_when_provided(self):
        """When acceptance_criteria is non-empty, it's included as context."""
        client = _make_client()
        captured_args = {}

        async def mock_stream(system_prompt, user_message, client_arg, config=None, **kwargs):
            captured_args["message"] = user_message
            yield "improved"

        with patch("canon.agent.spec_editor._stream_completion", side_effect=mock_stream):
            acs = ["Login form works", "Session persists"]
            async for _ in improve_section_stream("Auth", "Content", acs, client):
                pass

        msg = captured_args["message"]
        assert "Login form works" in msg
        assert "Session persists" in msg
        assert "Existing acceptance criteria" in msg

    @pytest.mark.asyncio
    async def test_omits_ac_block_when_empty(self):
        """When acceptance_criteria is empty, AC context block is omitted."""
        client = _make_client()
        captured_args = {}

        async def mock_stream(system_prompt, user_message, client_arg, config=None, **kwargs):
            captured_args["message"] = user_message
            yield "improved"

        with patch("canon.agent.spec_editor._stream_completion", side_effect=mock_stream):
            async for _ in improve_section_stream("Auth", "Content", [], client):
                pass

        assert "Existing acceptance criteria" not in captured_args["message"]


# ─── generate_acs_stream ─────────────────────────────────────────


class TestGenerateAcsStream:
    @pytest.mark.asyncio
    async def test_uses_generate_acs_system_prompt(self):
        """generate_acs_stream uses GENERATE_ACS_SYSTEM_PROMPT."""
        client = _make_client()
        captured_args = {}

        async def mock_stream(system_prompt, user_message, client_arg, config=None, **kwargs):
            captured_args["system"] = system_prompt
            captured_args["message"] = user_message
            yield "- [ ] AC"

        with patch("canon.agent.spec_editor._stream_completion", side_effect=mock_stream):
            async for _ in generate_acs_stream("Dashboard", "Shows metrics", client):
                pass

        assert captured_args["system"] == GENERATE_ACS_SYSTEM_PROMPT
        assert "Section: Dashboard" in captured_args["message"]
        assert "Shows metrics" in captured_args["message"]


# ─── expand_section_stream ───────────────────────────────────────


class TestExpandSectionStream:
    @pytest.mark.asyncio
    async def test_uses_expand_system_prompt(self):
        """expand_section_stream uses EXPAND_SYSTEM_PROMPT."""
        client = _make_client()
        captured_args = {}

        async def mock_stream(system_prompt, user_message, client_arg, config=None, **kwargs):
            captured_args["system"] = system_prompt
            captured_args["message"] = user_message
            yield "expanded"

        with patch("canon.agent.spec_editor._stream_completion", side_effect=mock_stream):
            async for _ in expand_section_stream("API", "REST endpoints", client):
                pass

        assert captured_args["system"] == EXPAND_SYSTEM_PROMPT
        assert "Section: API" in captured_args["message"]
        assert "REST endpoints" in captured_args["message"]


# ─── Default config ──────────────────────────────────────────────


class TestSpecEditorConfig:
    def test_default_config_values(self):
        assert SPEC_EDITOR_CONFIG.model == "claude-sonnet-4-6"
        assert SPEC_EDITOR_CONFIG.max_output_tokens == 4_000
        assert SPEC_EDITOR_CONFIG.temperature == 0.3


# ─── Helpers ─────────────────────────────────────────────────────


class AsyncStreamMock:
    """Mock for an async text_stream attribute."""

    def __init__(
        self, chunks: list[str], *, input_tokens: int = 10, output_tokens: int = 5
    ) -> None:
        self._chunks = chunks
        self._index = 0
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    @property
    def text_stream(self):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk

    async def get_final_message(self):
        """Return a mock final message with usage data."""
        usage = MagicMock()
        usage.input_tokens = self._input_tokens
        usage.output_tokens = self._output_tokens
        msg = MagicMock()
        msg.usage = usage
        return msg
