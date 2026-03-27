---
title: "LLM Observability via PostHog"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-03-26
updated: 2026-03-26
tags: [llm, observability, posthog, anthropic, cost-tracking]
---

# LLM Observability via PostHog

Replace manual token tracking with PostHog's native Anthropic wrapper (`posthog.ai.anthropic`) to get automatic `$ai_generation` events across all LLM call sites — enabling the built-in LLM analytics dashboard for cost tracking, latency histograms, token breakdowns, and trace views.

## 1. Background

<!-- canon:system:1 status:todo -->

Canon makes LLM calls in three places:

| Call Site | Module | Pattern | Tracked Today? |
|-----------|--------|---------|----------------|
| PR analysis | `agent/client.py` `ClaudeClient.complete()` | Sync `messages.create()` | Custom `agent_call_completed` event (tokens, duration, model) |
| Spec editing (improve / expand / generate ACs) | `agent/spec_editor.py` `_stream_completion()` | Async streaming `messages.stream()` | Not tracked |
| Spec generation | `agent/spec_generator.py` `generate_spec_stream()` | Async streaming `messages.stream()` | Not tracked |

**Problems:**
- Streaming calls (spec editing, spec generation) have zero observability — no token counts, no cost data, no latency tracking
- The custom `agent_call_completed` event doesn't populate PostHog's built-in LLM analytics dashboard, which expects `$ai_generation` events
- No trace IDs linking multi-step agent workflows
- No per-org cost attribution for billing visibility

**PostHog's Anthropic integration** (`posthog.ai.anthropic`) provides drop-in `Anthropic` and `AsyncAnthropic` wrappers that automatically capture `$ai_generation` events with model, tokens, cost, latency, and custom properties — including streaming support.

### Cloud vs OSS

| Concern | Cloud (managed) | OSS (self-hosted) |
|---------|-----------------|---------------------|
| PostHog configured? | Always — Canon's PostHog project key is deployed | Optional — operator may not set `POSTHOG_KEY` |
| Anthropic API key | Canon-managed (Pro/Enterprise) or BYOK (Starter) | Operator's own key |
| LLM analytics value | Cost attribution per org, billing visibility, abuse detection | Operator's own usage monitoring |
| Behavior when PostHog absent | N/A | Wrapper must no-op gracefully — LLM calls still work, just untracked |

The integration must preserve the existing guarantee: **analytics never breaks the application**. When PostHog is not configured (OSS without `POSTHOG_KEY`), all LLM calls must work identically — the wrapper simply doesn't emit events.

## 2. Expose PostHog Client Singleton

<!-- canon:system:2 status:done -->

The `posthog.ai.anthropic` wrapper requires a `posthog_client` parameter. The existing `analytics.py` module holds the PostHog client as a private `_client` singleton.

### Implementation

Add a `get_client()` accessor to `src/canon/analytics.py`:

```python
def get_client() -> Any:
    """Return the PostHog client instance, or None if not initialised.

    Used by posthog.ai wrappers that need the client reference.
    """
    return _client
```

### Cloud vs OSS

- **Cloud**: `get_client()` always returns a live `Posthog` instance
- **OSS**: Returns `None` when `POSTHOG_KEY` is not set — callers must handle this

### Acceptance Criteria

- [x] `analytics.get_client()` returns the initialized PostHog client when configured
<!-- canon:realized-in:PR#471 file:src/canon/analytics.py -->
- [x] `analytics.get_client()` returns `None` when PostHog is not initialized
<!-- canon:realized-in:PR#471 file:tests/test_analytics.py -->
- [ ] No changes to existing `track()`, `identify()`, `capture_exception()` behavior

## 3. Wrap Sync Client (`ClaudeClient`)

<!-- canon:system:3 status:done -->

Replace the vanilla `anthropic.Anthropic` in `ClaudeClient.__init__()` with `posthog.ai.anthropic.Anthropic` to automatically capture `$ai_generation` events on every `messages.create()` call.

### Implementation

```python
# agent/client.py
from canon import analytics

class ClaudeClient:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            self._client = None
            return

        ph = analytics.get_client()
        if ph is not None:
            from posthog.ai.anthropic import Anthropic as PHAnthropic
            self._client = PHAnthropic(api_key=key, posthog_client=ph)
        else:
            self._client = anthropic.Anthropic(api_key=key)
```

On each `complete()` call, pass PostHog metadata:

```python
response = self._client.messages.create(
    model=config.model,
    max_tokens=config.max_output_tokens,
    temperature=config.temperature,
    system=system_prompt,
    messages=[{"role": "user", "content": user_message}],
    posthog_distinct_id=org or analytics.SERVER_ACTOR,
    posthog_groups={"organization": org} if org else None,
    posthog_properties={"feature": "pr_analysis"},
)
```

When PostHog is not configured (OSS), the vanilla `anthropic.Anthropic` client is used and `posthog_*` kwargs are omitted entirely via conditional `ph_kwargs` dict construction. This prevents potential errors from unknown kwargs.

### Cloud vs OSS

- **Cloud**: Every `complete()` call emits both `$ai_generation` (automatic via wrapper) and `agent_call_completed` (existing manual tracking). The custom event is retained for backward compatibility with SRE dashboard panels.
- **OSS without PostHog**: Falls back to vanilla `anthropic.Anthropic`. No `$ai_generation` events emitted. No behavior change.
- **BYOK (Starter plan)**: `for_api_key()` creates a new `ClaudeClient` with a different API key. The new client must also use the PostHog wrapper so BYOK usage is tracked under Canon's PostHog project — this is critical for billing visibility.

### Acceptance Criteria

- [x] `ClaudeClient` uses `posthog.ai.anthropic.Anthropic` when PostHog is configured
<!-- canon:realized-in:PR#471 file:src/canon/agent/client.py -->
- [x] `ClaudeClient` falls back to `anthropic.Anthropic` when PostHog is not configured
- [x] `$ai_generation` events include `feature=pr_analysis` in properties
- [ ] `$ai_generation` events include org as `distinct_id` and `organization` group
- [ ] `for_api_key()` (BYOK) creates a client that also uses the PostHog wrapper
- [ ] Existing `agent_call_completed` custom event continues to fire (backward compat)
- [ ] LLM calls work identically when PostHog is absent (OSS graceful degradation)

## 4. Wrap Async Streaming Client

<!-- canon:system:4 status:done -->

Add manual `$ai_generation` event emission in `spec_editor.py` and `spec_generator.py` after streaming completes. The PostHog AsyncAnthropic wrapper does not support the `.messages.stream()` context manager pattern, so events are emitted via `analytics.track_ai_generation()` using token counts from `stream.get_final_message()`.

### Implementation

Streaming calls currently create a fresh `AsyncAnthropic` per invocation:

```python
# Current (spec_editor.py, spec_generator.py)
async with anthropic.AsyncAnthropic(api_key=api_key) as async_client:
    async with async_client.messages.stream(...) as stream:
        async for text in stream.text_stream:
            yield text
```

Replace with:

```python
from canon import analytics

ph = analytics.get_client()
if ph is not None:
    from posthog.ai.anthropic import AsyncAnthropic as PHAsyncAnthropic
    client_cls = PHAsyncAnthropic
    extra_kwargs = {"posthog_client": ph}
else:
    client_cls = anthropic.AsyncAnthropic
    extra_kwargs = {}

async with client_cls(api_key=api_key, **extra_kwargs) as async_client:
    async with async_client.messages.stream(
        ...,
        posthog_distinct_id=distinct_id,
        posthog_properties={"feature": feature, "action": action},
    ) as stream:
        async for text in stream.text_stream:
            yield text
```

Each streaming call site should pass a `feature` and `action`:

| Module | Feature | Action |
|--------|---------|--------|
| `spec_editor.py` → `improve_section_stream` | `spec_edit` | `improve` |
| `spec_editor.py` → `generate_acs_stream` | `spec_edit` | `generate_acs` |
| `spec_editor.py` → `expand_section_stream` | `spec_edit` | `expand` |
| `spec_generator.py` → `generate_spec_stream` | `spec_generate` | `generate` |

### Cloud vs OSS

- **Cloud**: Streaming calls now emit `$ai_generation` events — filling the observability gap for spec editing and generation
- **OSS without PostHog**: Falls back to vanilla `AsyncAnthropic`. Streaming works identically.
- **BYOK**: Spec editing and generation routes resolve the client via `get_claude_client_for_org()`. The API key passed to the streaming functions must produce a PostHog-wrapped `AsyncAnthropic` regardless of key source, so BYOK streaming usage is tracked.

### Acceptance Criteria

- [x] `spec_editor.py` streaming calls emit `$ai_generation` events when PostHog is configured
<!-- canon:realized-in:PR#471 file:src/canon/agent/spec_editor.py -->
- [x] `spec_generator.py` streaming calls emit `$ai_generation` events when PostHog is configured
<!-- canon:realized-in:PR#471 file:src/canon/agent/spec_generator.py -->
- [x] Each call includes `feature` and `action` in `posthog_properties`
- [x] Streaming behavior (chunk-by-chunk yielding) is unchanged
<!-- canon:realized-in:PR#471 file:tests/test_agent/test_spec_editor.py -->
- [ ] Graceful fallback to vanilla `AsyncAnthropic` when PostHog is absent
- [x] Error handling behavior is unchanged — API errors still logged and yielded as error comments

## 5. Per-Org Cost Attribution

<!-- canon:system:5 status:todo -->

Tag every `$ai_generation` event with organization context to enable per-org cost dashboards and billing reconciliation.

### Properties

Every LLM call should include:

| Property | Source | Purpose |
|----------|--------|---------|
| `posthog_distinct_id` | Org login or `canon-server` | Groups events by org |
| `posthog_groups.organization` | Org login | PostHog group analytics |
| `feature` | `pr_analysis`, `spec_edit`, `spec_generate` | Cost breakdown by feature |
| `action` | `analyze`, `improve`, `expand`, `generate_acs`, `generate` | Granular breakdown |
| `repo` | `owner/repo` | Cost per repo |
| `plan` | `starter`, `pro`, `enterprise`, `self_hosted` | Cloud billing tier |

### Cloud vs OSS

- **Cloud**: `plan` is resolved from the billing service. Enables cost-per-org dashboards and usage-based billing analysis.
- **OSS**: `plan` defaults to `self_hosted`. Org context may be empty — events are grouped under `canon-server` distinct ID.

### Acceptance Criteria

- [ ] All `$ai_generation` events include `organization` group when org context is available
- [ ] Events include `feature`, `action`, and `repo` in properties
- [ ] Cloud deployments include `plan` property from billing tier
- [ ] OSS deployments default `plan` to `self_hosted`
- [ ] PostHog LLM analytics dashboard shows cost breakdown by organization

## 6. Deprecation of Custom `agent_call_completed` Event

<!-- canon:system:6 status:in_progress -->

The existing `agent_call_completed` event in `ClaudeClient.complete()` overlaps with the automatic `$ai_generation` event. Plan a phased deprecation.

### Phase 1: Dual Emit (this spec)

Keep both events firing. The custom event powers existing SRE dashboard panels (`sre-alerting-monitoring.md` Section 4). The `$ai_generation` event populates the LLM analytics dashboard.

### Phase 2: Migrate Dashboards (follow-up)

Update SRE dashboard panels to query `$ai_generation` events instead of `agent_call_completed`. Once migrated, remove the manual `analytics.track()` calls from `ClaudeClient.complete()`.

### Acceptance Criteria

- [ ] Both `$ai_generation` and `agent_call_completed` fire during Phase 1
- [ ] `agent_call_completed` is annotated with a code comment marking it for Phase 2 deprecation
- [ ] No SRE dashboard or alert rule is broken by adding `$ai_generation` events

## 7. Rollout Plan

<!-- canon:system:7 status:todo -->

### Phase 1 — Expose client + wrap sync path (Sections 2–3)

- Add `get_client()` to `analytics.py`
- Swap `ClaudeClient` to use PostHog Anthropic wrapper
- Verify `$ai_generation` events appear in PostHog LLM analytics dashboard
- Verify BYOK clients also emit events
- **Risk**: Low — sync path already tracked, this upgrades the event format

### Phase 2 — Wrap async streaming (Section 4)

- Swap `spec_editor.py` and `spec_generator.py` to use PostHog `AsyncAnthropic`
- Verify streaming behavior unchanged
- Verify `$ai_generation` events captured for streaming calls
- **Risk**: Medium — streaming wrapper compatibility needs verification

### Phase 3 — Cost attribution + dashboards (Section 5)

- Add org/plan/repo metadata to all calls
- Build PostHog LLM analytics views: cost by org, cost by feature, daily spend
- **Risk**: Low — additive metadata, no behavior change

### Phase 4 — Deprecate custom event (Section 6)

- Migrate SRE dashboard panels from `agent_call_completed` to `$ai_generation`
- Remove manual tracking code
- **Risk**: Low — dashboard migration only

### Acceptance Criteria

- [ ] Phase 1 produces visible `$ai_generation` events in PostHog within 24 hours of deploy
- [ ] Each phase is a separate PR
- [ ] No phase introduces latency overhead on the LLM call path (PostHog capture is async/non-blocking)
- [ ] OSS deployments without `POSTHOG_KEY` pass all existing tests without modification

## 8. Open Questions

- Does the vanilla Anthropic SDK raise on unknown `posthog_*` kwargs, or silently ignore them? If it raises, we need conditional kwarg passing.
- Does `posthog.ai.anthropic.AsyncAnthropic` support the `.messages.stream()` context manager pattern? The docs confirm streaming support but we should verify the exact API shape.
- Should we add a `posthog_trace_id` linking PR analysis → spec updates within a single webhook event? Useful but adds complexity.
- What PostHog plan tier is needed for the LLM analytics dashboard? Verify it's available on Canon's current plan.
