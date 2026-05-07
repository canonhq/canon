"""Cross-source ranking and token-budget enforcement for ContextBundle items."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from canon_slack.work_context.models import WorkContextItem

# Weights tuned empirically; see Open Question #1 in the design doc
_SOURCE_WEIGHT: dict[str, float] = {
    "canon_spec": 1.0,
    "canon_pr_analysis": 0.9,
    "github_pr": 0.8,
    "linear_ticket": 0.8,
    "jira_ticket": 0.8,
    "github_issue": 0.8,
    "ticket": 0.8,
    "github_commit": 0.6,
    "slack_thread": 0.5,
}


def _recency_weight(timestamp: datetime, today: datetime | None = None) -> float:
    """Exponential decay: weight ~ e^(-days_old / 30). 30d half-life."""
    today = today or datetime.now(UTC)
    days_old = max(0.0, (today - timestamp).total_seconds() / 86400.0)
    return math.exp(-days_old / 30.0)


def _keyword_overlap(text: str, query: str) -> float:
    """Fraction of query tokens present in text. 0-1."""
    q_tokens = {t for t in query.lower().split() if len(t) > 2}
    if not q_tokens:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for t in q_tokens if t in text_lower)
    return hits / len(q_tokens)


def score_items(items: list[WorkContextItem], query: str) -> None:
    """Mutates items in place, setting `relevance_score` for each."""
    today = datetime.now(UTC)
    for item in items:
        recency = _recency_weight(item.timestamp, today=today)
        overlap = _keyword_overlap(f"{item.title}\n{item.summary}", query)
        weight = _SOURCE_WEIGHT.get(item.source, 0.5)
        item.relevance_score = recency * (0.3 + 0.7 * overlap) * weight


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token (OpenAI/Anthropic ballpark)."""
    return len(text) // 4


def apply_token_budget(items: list[WorkContextItem], max_tokens: int) -> list[WorkContextItem]:
    """Greedy-fill `max_tokens` with items in descending relevance_score order.

    Sort items by relevance, then walk the list adding each item that still
    fits within the remaining budget. An item too large to fit is **skipped**
    (not aborted on) — subsequent smaller items still get a chance to fill
    the budget. This is bin-packing, not prefix-truncation.

    Trade-off: a high-relevance oversized item is silently dropped in favour
    of lower-relevance items that fit. Acceptable in v1 because items are
    short (~50-300 tokens) and budget is generous (6000), so oversized items
    are rare. If the source mix changes (e.g. embedding full PR diffs) and
    high-relevance items routinely exceed the per-item slice, revisit this.
    """
    sorted_items = sorted(items, key=lambda i: i.relevance_score, reverse=True)
    kept: list[WorkContextItem] = []
    used = 0
    for item in sorted_items:
        item_tokens = estimate_tokens(item.title) + estimate_tokens(item.summary)
        if used + item_tokens > max_tokens:
            continue  # skip-not-stop: try the next (smaller) item
        kept.append(item)
        used += item_tokens
    return kept
