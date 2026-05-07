"""Classify @canon mentions into intent + recency profile."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from canon.agent.client import AgentConfig
from canon_slack.work_context.models import Intent, RecencyProfile

logger = logging.getLogger(__name__)


# Regex shortcuts — exact matches return Intent.LOOKUP with confidence 1.0
_LOOKUP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(?:what(?:'s| is) the )?status (?:of )?", re.IGNORECASE),
    re.compile(r"^(?:list|show) ", re.IGNORECASE),
    re.compile(r"^(?:what(?:'s| is)(?: the)? )?coverage", re.IGNORECASE),
    re.compile(r"^my specs?\b", re.IGNORECASE),
    re.compile(r"^what specs? do i own", re.IGNORECASE),
    re.compile(r"^my team\b", re.IGNORECASE),
    re.compile(r"^team coverage", re.IGNORECASE),
    re.compile(r"^list me\b", re.IGNORECASE),
]

_LLM_PROMPT = """You classify Slack questions to a small bot. Output ONLY a JSON object on one line. No prose.

Intents:
- "lookup": asking for a specific factual value (status, list, coverage)
- "discussion": asking what's currently happening or in flight
- "investigation": asking why something happened or causal chains over longer history

Recency profiles:
- "recent": last 7 days (use for "what's happening")
- "historical": last 90 days (use for "why did" / "when")
- "mixed": short for messages, long for code (use when uncertain)

Output: {"intent": "...", "recency_profile": "...", "confidence": 0.0-1.0}"""

_LLM_TIMEOUT_SECONDS = 1.0


class IntentClassifier:
    def __init__(self, claude_client: Any | None) -> None:
        self._claude = claude_client

    async def classify(self, query: str) -> tuple[Intent, RecencyProfile, float]:
        # 1. Regex shortcut
        for pattern in _LOOKUP_PATTERNS:
            if pattern.match(query):
                return (Intent.LOOKUP, RecencyProfile.RECENT, 1.0)

        # 2. LLM fallback (with timeout)
        if self._claude is None or not getattr(self._claude, "is_available", False):
            return (Intent.DISCUSSION, RecencyProfile.MIXED, 0.0)

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._claude.complete,
                    _LLM_PROMPT,
                    query,
                    AgentConfig(
                        model="claude-haiku-4-5-20251001",
                        max_output_tokens=200,
                        temperature=0,
                    ),
                ),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
            parsed = json.loads(result.text.strip())
            intent = Intent(parsed["intent"])
            recency = RecencyProfile(parsed["recency_profile"])
            conf = float(parsed["confidence"])
            return (intent, recency, conf)
        except TimeoutError:
            logger.warning("IntentClassifier: LLM call timed out")
            return (Intent.DISCUSSION, RecencyProfile.MIXED, 0.0)
        except (KeyError, ValueError, json.JSONDecodeError):
            logger.warning("IntentClassifier: LLM returned malformed response")
            return (Intent.DISCUSSION, RecencyProfile.MIXED, 0.0)
        except Exception:
            logger.warning("IntentClassifier: LLM call failed", exc_info=True)
            return (Intent.DISCUSSION, RecencyProfile.MIXED, 0.0)
