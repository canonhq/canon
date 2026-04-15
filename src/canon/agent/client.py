"""Anthropic SDK wrapper for Claude agent runtime."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import anthropic
from pydantic import BaseModel

from canon import analytics

logger = logging.getLogger(__name__)


class AgentUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("ANTHROPIC_API_KEY is not set — agent is unavailable")


class AgentAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AgentConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_input_tokens: int = 128_000
    max_output_tokens: int = 16_000
    max_context_tokens: int = 950_000  # Sonnet 4.6 has 1M context; leave margin for output
    temperature: float = 0


DEFAULT_AGENT_CONFIG = AgentConfig()


class CompletionResult(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int


class ClaudeClient:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._posthog_enabled = False
        if not key:
            self._client: anthropic.Anthropic | None = None
            return
        ph = analytics.get_client()
        if ph is not None:
            try:
                from posthog.ai.anthropic import Anthropic as PHAnthropic

                self._client = PHAnthropic(api_key=key, posthog_client=ph)
                self._posthog_enabled = True
            except Exception:
                logger.warning(
                    "Failed to initialise PostHog-wrapped Anthropic client — "
                    "falling back to standard client (LLM observability disabled)",
                    exc_info=True,
                )
                self._client = anthropic.Anthropic(api_key=key)
        else:
            self._client = anthropic.Anthropic(api_key=key)

    @property
    def is_available(self) -> bool:
        return self._client is not None

    @property
    def api_key(self) -> str | None:
        """Return the API key, or None if unavailable."""
        return self._client.api_key if self._client else None

    def for_api_key(self, api_key: str) -> ClaudeClient:
        """Return a new ClaudeClient using a different API key (e.g. BYOK)."""
        return ClaudeClient(api_key=api_key)

    def complete(
        self, system_prompt: str, user_message: str, config: AgentConfig, org: str = ""
    ) -> CompletionResult:
        if not self._client:
            analytics.track(
                "agent_call_completed",
                properties={
                    "model": config.model,
                    "duration_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "success": False,
                    "error_message": "Agent unavailable (no API key)",
                },
                groups={"organization": org} if org else None,
            )
            raise AgentUnavailableError()

        start = time.monotonic()
        success = True
        error_message = ""
        input_tokens = 0
        output_tokens = 0

        try:
            ph_kwargs: dict[str, Any] = {}
            if self._posthog_enabled:
                ph_kwargs = {
                    "posthog_distinct_id": org or analytics.SERVER_ACTOR,
                    "posthog_properties": {"feature": "pr_analysis"},
                }
                if org:
                    ph_kwargs["posthog_groups"] = {"organization": org}

            response = self._client.messages.create(
                model=config.model,
                max_tokens=config.max_output_tokens,
                temperature=config.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                **ph_kwargs,
            )

            text = "".join(block.text for block in response.content if block.type == "text")
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

            return CompletionResult(
                text=text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except anthropic.APIError as e:
            success = False
            error_message = str(e)
            raise AgentAPIError(str(e), getattr(e, "status_code", None)) from e
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            # TODO(Phase 2): Remove after SRE dashboards migrate to $ai_generation
            # events. See llm-observability.md Section 6.
            analytics.track(
                "agent_call_completed",
                properties={
                    "model": config.model,
                    "duration_ms": duration_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "success": success,
                    "error_message": error_message,
                },
                groups={"organization": org} if org else None,
            )


async def get_claude_client_for_org(
    org_login: str,
    default_client: ClaudeClient,
    billing_service: object | None = None,
) -> ClaudeClient:
    """Resolve the right ClaudeClient for an org based on their subscription plan.

    - Starter (BYOK): uses the org's stored Anthropic API key
    - Pro/Enterprise: uses Canon's default API key
    - No subscription: uses default (self-hosted behavior)
    """
    if billing_service is None:
        return default_client

    try:
        from ..billing.models import Plan
        from ..billing.service import BillingService

        if not isinstance(billing_service, BillingService):
            return default_client

        sub = await billing_service.get_subscription(org_login)
        if sub is None:
            return default_client

        if sub.plan == Plan.STARTER:
            byok_key = await billing_service.get_anthropic_key(org_login)
            if byok_key:
                return default_client.for_api_key(byok_key)
            # Key missing or marked invalid — check status for a specific log message
            key_status = await billing_service.get_anthropic_key_status(org_login)
            if key_status.exists and key_status.status == "invalid":
                logger.warning(
                    "Starter plan org %s has invalid BYOK key — agent unavailable", org_login
                )
            else:
                logger.warning("Starter plan org %s has no BYOK key — agent unavailable", org_login)
            raise AgentUnavailableError()

        # Pro and Enterprise use Canon's key
        return default_client

    except AgentUnavailableError:
        raise
    except ImportError:
        # Billing module not deployed yet — acceptable fallback
        logger.info("Billing module not available for org %s — using default client", org_login)
        return default_client
    except Exception:
        logger.error(
            "Unexpected error resolving client for org %s — refusing to silently fall back",
            org_login,
            exc_info=True,
        )
        raise AgentUnavailableError() from None
