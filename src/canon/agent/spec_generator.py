"""AI-assisted spec generation with streaming."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date

import anthropic

from canon import analytics

from .client import AgentConfig, ClaudeClient

logger = logging.getLogger(__name__)

SPEC_GENERATOR_CONFIG = AgentConfig(
    model="claude-sonnet-4-6",
    max_output_tokens=8_000,
    temperature=0.3,
)

SPEC_SYSTEM_PROMPT = """\
You are a senior technical writer generating a Canon-format spec document.

Output a complete markdown document with YAML frontmatter and numbered sections.

## Format

```
---
title: <concise title>
status: draft
owner: {owner}
team: {team}
review_status: draft
created: "{today}"
tags: [{tags}]
---

## 1. Overview

<1-2 paragraph summary of what this feature does and why it matters>

## 2. Requirements

<Detailed requirements prose>

### Acceptance Criteria

- [ ] <specific, testable criterion>
- [ ] <specific, testable criterion>

## 3. Design

<Technical approach, key decisions, architecture notes>

### Acceptance Criteria

- [ ] <design-level criterion>

## 4. Rollout Plan

<How to deploy, feature flags, migration steps, validation>
```

## Rules

- Every numbered section (##) SHOULD have an ### Acceptance Criteria subsection with checkboxes
- Acceptance criteria must be specific and testable — not vague
- Use the repo context (existing specs, config) to ensure consistency
- Match the team/project naming from the repo config if available
- Number sections sequentially: 1, 2, 3, ...
- Output ONLY the markdown document — no explanations before or after
"""


@dataclass
class RepoContext:
    """Context about the repo for spec generation."""

    owner: str
    repo: str
    existing_specs: list[str] = field(default_factory=list)
    team: str = ""
    project_key: str = ""
    user_name: str = ""


def _build_user_message(description: str, ctx: RepoContext, today: str) -> str:
    """Build the user prompt with repo context."""
    parts = [f"Generate a spec for the following feature:\n\n{description}"]

    parts.append(f"\n\nRepo: {ctx.owner}/{ctx.repo}")
    if ctx.user_name:
        parts.append(f"Author: {ctx.user_name}")
    if ctx.team:
        parts.append(f"Team: {ctx.team}")
    if ctx.project_key:
        parts.append(f"Project key: {ctx.project_key}")
    parts.append(f"Date: {today}")

    if ctx.existing_specs:
        specs_list = "\n".join(f"  - {s}" for s in ctx.existing_specs[:20])
        parts.append(f"\nExisting specs in this repo:\n{specs_list}")

    return "\n".join(parts)


async def generate_spec_stream(
    description: str,
    repo_context: RepoContext,
    client: ClaudeClient,
    config: AgentConfig | None = None,
    *,
    distinct_id: str = "",
) -> AsyncIterator[str]:
    """Stream spec generation using Claude.

    Yields text chunks as they arrive from the API.
    """
    api_key = client.api_key
    if not client.is_available or not api_key:
        yield "<!-- AI generation unavailable: ANTHROPIC_API_KEY not set -->\n"
        return

    cfg = config or SPEC_GENERATOR_CONFIG
    today = date.today().isoformat()
    user_message = _build_user_message(description, repo_context, today)

    system_prompt = SPEC_SYSTEM_PROMPT.replace("{owner}", repo_context.user_name or "")
    system_prompt = system_prompt.replace("{team}", repo_context.team or "")
    system_prompt = system_prompt.replace("{today}", today)
    system_prompt = system_prompt.replace("{tags}", "")

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
                    feature="spec_generate",
                    action="generate",
                    distinct_id=distinct_id or analytics.SERVER_ACTOR,
                )
            except Exception:
                logger.warning(
                    "Failed to capture LLM usage for spec_generate/generate", exc_info=True
                )
    except anthropic.APIError as e:
        logger.error("Spec generation API error: %s", e)
        yield "\n\n<!-- Generation failed. Please try again. -->\n"
