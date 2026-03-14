"""Anthropic SDK wrapper for Claude agent runtime."""

from __future__ import annotations

import os

import anthropic
from pydantic import BaseModel


class AgentUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("ANTHROPIC_API_KEY is not set — agent is unavailable")


class AgentAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AgentConfig(BaseModel):
    model: str = "claude-sonnet-4-5-20250929"
    max_input_tokens: int = 128_000
    max_output_tokens: int = 16_000
    temperature: float = 0


DEFAULT_AGENT_CONFIG = AgentConfig()


class CompletionResult(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int


class ClaudeClient:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client: anthropic.Anthropic | None = anthropic.Anthropic(api_key=key) if key else None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    @property
    def api_key(self) -> str | None:
        """Return the API key, or None if unavailable."""
        return self._client.api_key if self._client else None

    def complete(
        self, system_prompt: str, user_message: str, config: AgentConfig
    ) -> CompletionResult:
        if not self._client:
            raise AgentUnavailableError()

        try:
            response = self._client.messages.create(
                model=config.model,
                max_tokens=config.max_output_tokens,
                temperature=config.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            text = "".join(block.text for block in response.content if block.type == "text")

            return CompletionResult(
                text=text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
        except anthropic.APIError as e:
            raise AgentAPIError(str(e), getattr(e, "status_code", None)) from e
