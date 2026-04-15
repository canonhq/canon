"""AI-assisted spec section editing with streaming."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

import anthropic

from canon import analytics

from .client import AgentConfig, ClaudeClient

logger = logging.getLogger(__name__)

SPEC_EDITOR_CONFIG = AgentConfig(
    model="claude-sonnet-4-6",
    max_output_tokens=4_000,
    temperature=0.3,
)

IMPROVE_SYSTEM_PROMPT = """\
You are a senior technical writer improving a spec section.

Given a section title and its current content, rewrite the prose to be clearer,
more precise, and better structured. Preserve the original meaning and scope.

Rules:
- Output the improved content preserving ALL original structure
- Do not wrap in markdown code fences
- Keep the same level of technical detail
- Improve clarity, eliminate ambiguity, fix grammar
- Use short paragraphs and bullet points where appropriate
- PRESERVE all HTML comments exactly as they appear (<!-- canon:... --> etc.)
- PRESERVE all markdown headings (## / ###) in the same hierarchy
- PRESERVE all acceptance criteria checkboxes (- [x] / - [ ]) and their text
- PRESERVE YAML frontmatter (--- delimited block) if present at the top
- Only improve the prose paragraphs between structural elements, do not remove anything
"""

GENERATE_ACS_SYSTEM_PROMPT = """\
You are a senior technical writer generating acceptance criteria for a spec section.

Given a section title and its content, generate specific, testable acceptance criteria.

Rules:
- Output ONLY checklist items, one per line: - [ ] <criterion>
- Each criterion must be specific and independently testable
- Avoid vague criteria like "should work correctly"
- Cover the key behaviors described in the content
- Generate 3-8 criteria depending on section complexity
- Do not output anything else — no headings, no explanations
- Do NOT duplicate any existing acceptance criteria from the input
"""

EXPAND_SYSTEM_PROMPT = """\
You are a senior technical writer expanding a spec section.

Given a section title and its current content, expand the prose with more detail,
edge cases, and implementation considerations.

Rules:
- Output the expanded content preserving ALL original structure
- Do not wrap in markdown code fences
- Build on the existing content, don't replace it
- Add detail about edge cases, error handling, and constraints
- Use short paragraphs and bullet points where appropriate
- PRESERVE all HTML comments exactly as they appear (<!-- canon:... --> etc.)
- PRESERVE all markdown headings (## / ###) in the same hierarchy
- PRESERVE all acceptance criteria checkboxes (- [x] / - [ ]) and their text
- PRESERVE YAML frontmatter (--- delimited block) if present at the top
- Insert new prose between existing structural elements, do not remove anything
"""


async def _stream_completion(
    system_prompt: str,
    user_message: str,
    client: ClaudeClient,
    config: AgentConfig | None = None,
    *,
    feature: str = "spec_edit",
    action: str = "",
    distinct_id: str = "",
) -> AsyncIterator[str]:
    """Stream a completion from Claude, emitting a ``$ai_generation`` event on success."""
    api_key = client.api_key
    if not client.is_available or not api_key:
        yield "<!-- AI editing unavailable: ANTHROPIC_API_KEY not set -->\n"
        return

    cfg = config or SPEC_EDITOR_CONFIG
    start = time.monotonic()

    try:
        async with (
            anthropic.AsyncAnthropic(api_key=api_key) as async_client,
            async_client.messages.stream(
                model=cfg.model,
                max_tokens=cfg.max_output_tokens,
                temperature=cfg.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream,
        ):
            async for text in stream.text_stream:
                yield text

            # Token counts are only available after the full stream is consumed.
            # We emit manually because the PostHog AsyncAnthropic wrapper does
            # not support the .messages.stream() context manager pattern.
            try:
                final = await stream.get_final_message()
                duration = time.monotonic() - start
                analytics.track_ai_generation(
                    model=cfg.model,
                    input_tokens=final.usage.input_tokens,
                    output_tokens=final.usage.output_tokens,
                    latency_seconds=duration,
                    feature=feature,
                    action=action,
                    distinct_id=distinct_id or analytics.SERVER_ACTOR,
                )
            except Exception:
                logger.warning(
                    "Failed to capture LLM usage for %s/%s", feature, action, exc_info=True
                )
    except anthropic.APIError as e:
        logger.error("Spec editing API error: %s", e)
        yield "\n\n<!-- Editing failed. Please try again. -->\n"


async def improve_section_stream(
    title: str,
    content: str,
    acceptance_criteria: list[str],
    client: ClaudeClient,
) -> AsyncIterator[str]:
    """Stream an improved version of a spec section's prose."""
    parts = [f"Section: {title}\n\nCurrent content:\n{content}"]
    if acceptance_criteria:
        acs = "\n".join(f"- [ ] {ac}" for ac in acceptance_criteria)
        parts.append(
            f"\nExisting acceptance criteria (for context, do not include in output):\n{acs}"
        )

    async for chunk in _stream_completion(
        IMPROVE_SYSTEM_PROMPT, "\n".join(parts), client, action="improve"
    ):
        yield chunk


async def generate_acs_stream(
    title: str,
    content: str,
    client: ClaudeClient,
) -> AsyncIterator[str]:
    """Stream generated acceptance criteria for a spec section."""
    user_message = f"Section: {title}\n\nContent:\n{content}"

    async for chunk in _stream_completion(
        GENERATE_ACS_SYSTEM_PROMPT, user_message, client, action="generate_acs"
    ):
        yield chunk


async def expand_section_stream(
    title: str,
    content: str,
    client: ClaudeClient,
) -> AsyncIterator[str]:
    """Stream an expanded version of a spec section's prose."""
    user_message = f"Section: {title}\n\nCurrent content:\n{content}"

    async for chunk in _stream_completion(
        EXPAND_SYSTEM_PROMPT, user_message, client, action="expand"
    ):
        yield chunk
