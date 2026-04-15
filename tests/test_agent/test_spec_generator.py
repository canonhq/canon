"""Tests for AI-assisted spec generation (spec_generator.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from canon.agent.client import ClaudeClient
from canon.agent.spec_generator import (
    SPEC_GENERATOR_CONFIG,
    RepoContext,
    generate_spec_stream,
)


def _make_client(*, available: bool = True, api_key: str = "sk-test") -> ClaudeClient:
    """Create a ClaudeClient mock with configurable availability."""
    client = MagicMock(spec=ClaudeClient)
    client.is_available = available
    client.api_key = api_key if available else None
    return client


def _make_repo_context(**kwargs) -> RepoContext:
    return RepoContext(owner="acme", repo="widgets", **kwargs)


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
        usage = MagicMock()
        usage.input_tokens = self._input_tokens
        usage.output_tokens = self._output_tokens
        msg = MagicMock()
        msg.usage = usage
        return msg


def _mock_streaming_chain(chunks: list[str], **kwargs):
    """Build the mock chain for AsyncAnthropic → messages.stream() → text_stream."""
    mock_text_stream = AsyncStreamMock(chunks, **kwargs)

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_text_stream)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_async_anthropic = AsyncMock()
    mock_async_anthropic.__aenter__ = AsyncMock(return_value=mock_async_anthropic)
    mock_async_anthropic.__aexit__ = AsyncMock(return_value=False)
    mock_async_anthropic.messages.stream = MagicMock(return_value=mock_stream_ctx)

    return mock_async_anthropic


class TestGenerateSpecStream:
    @pytest.mark.asyncio
    async def test_yields_unavailable_when_no_api_key(self):
        client = _make_client(available=False)

        chunks = []
        async for chunk in generate_spec_stream("Build auth", _make_repo_context(), client):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "AI generation unavailable" in chunks[0]

    @pytest.mark.asyncio
    async def test_streams_text_from_anthropic(self):
        client = _make_client()
        mock_anthropic = _mock_streaming_chain(["# Spec\n", "## 1. Overview"])

        with patch(
            "canon.agent.spec_generator.anthropic.AsyncAnthropic",
            return_value=mock_anthropic,
        ):
            chunks = []
            async for chunk in generate_spec_stream("Build auth", _make_repo_context(), client):
                chunks.append(chunk)

        assert chunks == ["# Spec\n", "## 1. Overview"]

    @pytest.mark.asyncio
    async def test_tracks_ai_generation_after_stream(self):
        """After streaming completes, $ai_generation is emitted with correct metadata."""
        client = _make_client()
        mock_anthropic = _mock_streaming_chain(
            ["spec content"], input_tokens=200, output_tokens=100
        )

        with (
            patch(
                "canon.agent.spec_generator.anthropic.AsyncAnthropic",
                return_value=mock_anthropic,
            ),
            patch("canon.agent.spec_generator.analytics.track_ai_generation") as mock_track,
        ):
            chunks = []
            async for chunk in generate_spec_stream("Build auth", _make_repo_context(), client):
                chunks.append(chunk)

        assert chunks == ["spec content"]
        mock_track.assert_called_once()
        call_kwargs = mock_track.call_args[1]
        assert call_kwargs["model"] == SPEC_GENERATOR_CONFIG.model
        assert call_kwargs["input_tokens"] == 200
        assert call_kwargs["output_tokens"] == 100
        assert call_kwargs["feature"] == "spec_generate"
        assert call_kwargs["action"] == "generate"

    @pytest.mark.asyncio
    async def test_tracks_with_distinct_id(self):
        """Custom distinct_id is passed through to track_ai_generation."""
        client = _make_client()
        mock_anthropic = _mock_streaming_chain(["ok"])

        with (
            patch(
                "canon.agent.spec_generator.anthropic.AsyncAnthropic",
                return_value=mock_anthropic,
            ),
            patch("canon.agent.spec_generator.analytics.track_ai_generation") as mock_track,
        ):
            async for _ in generate_spec_stream(
                "Build auth", _make_repo_context(), client, distinct_id="org-acme"
            ):
                pass

        assert mock_track.call_args[1]["distinct_id"] == "org-acme"

    @pytest.mark.asyncio
    async def test_analytics_failure_does_not_break_streaming(self):
        """If get_final_message() raises, streaming still works."""
        client = _make_client()
        mock_anthropic = _mock_streaming_chain(["spec"])

        # Make get_final_message raise — need to reach into the mock chain
        mock_stream_ctx = mock_anthropic.messages.stream.return_value
        failing_stream = AsyncStreamMock(["spec"])
        failing_stream.get_final_message = AsyncMock(side_effect=RuntimeError("boom"))
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=failing_stream)

        with patch(
            "canon.agent.spec_generator.anthropic.AsyncAnthropic",
            return_value=mock_anthropic,
        ):
            chunks = []
            async for chunk in generate_spec_stream("Build auth", _make_repo_context(), client):
                chunks.append(chunk)

        assert chunks == ["spec"]

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
            "canon.agent.spec_generator.anthropic.AsyncAnthropic",
            return_value=mock_async_anthropic,
        ):
            chunks = []
            async for chunk in generate_spec_stream("Build auth", _make_repo_context(), client):
                chunks.append(chunk)

        assert len(chunks) == 1
        assert "Generation failed" in chunks[0]


class TestSpecGeneratorConfig:
    def test_default_config_values(self):
        assert SPEC_GENERATOR_CONFIG.model == "claude-sonnet-4-6"
        assert SPEC_GENERATOR_CONFIG.max_output_tokens == 8_000
        assert SPEC_GENERATOR_CONFIG.temperature == 0.3
