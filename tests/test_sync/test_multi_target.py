"""Tests for multi-target ticket sync — error tracking, shadow sync, drift detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from canon.parser.parse import parse_spec
from canon.sync.engine import forward_sync, forward_sync_multi
from canon.sync.mapping import RoutingRule, TicketMappingConfig, TicketSystemConfig
from canon.sync.models import CreateTicketInput, CreateTicketResult


class MockAdapter:
    def __init__(self, *, create_error: Exception | None = None):
        self.created: list[CreateTicketInput] = []
        self.create_error = create_error

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        self.created.append(input)
        if self.create_error:
            raise self.create_error
        return CreateTicketResult(ticket_id="GH-1", ticket_url="https://github.com/issues/1")

    async def update_ticket(self, input) -> None:
        pass

    async def get_ticket_status(self, ticket_id: str):
        pass

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        pass

    async def search_tickets(self, project_key: str, title_pattern: str) -> list:
        return []

    @property
    def system_name(self) -> str:
        return "github"

    @property
    def capabilities(self):
        from canon.sync.adapters.base import AdapterCapabilities

        return AdapterCapabilities()


class TestSyncErrorTracking:
    async def test_forward_sync_error_tracked_in_result(self):
        """Forward sync errors should be captured in SyncResult.errors."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:todo -->

Content.
"""
        doc = parse_spec(raw).document
        adapter = MockAdapter(create_error=RuntimeError("API timeout"))

        _, result = await forward_sync(doc, adapter, "test-project")

        assert len(result.errors) == 1
        assert "API timeout" in result.errors[0].error


class TestAdapterResolutionTracking:
    def test_resolve_adapter_tracks_failure(self):
        """_resolve_adapter should track PostHog event when no adapter found."""
        from canon.github.handlers.on_push import _resolve_adapter
        from canon.sync.mapping import TicketMappingConfig

        with (
            patch("canon.github.handlers.on_push.analytics") as mock_analytics,
            patch("canon.github.handlers.on_push.create_adapter", return_value=None),
        ):
            adapter, _pk, _cfg = _resolve_adapter(
                TicketMappingConfig(), None, "MY-PROJECT", "docs/specs/test.md"
            )

            assert adapter is None
            mock_analytics.track.assert_called_once_with(
                "sync_adapter_resolution_failed",
                properties={
                    "file_path": "docs/specs/test.md",
                    "project_key": "MY-PROJECT",
                },
            )


class TestRoutingRuleShadowTargets:
    def test_routing_rule_accepts_shadow_targets(self):
        rule = RoutingRule(
            match={"tags": ["product"]},
            target="linear",
            shadow_targets=["jira", "github"],
        )
        assert rule.shadow_targets == ["jira", "github"]

    def test_routing_rule_defaults_to_empty_shadows(self):
        rule = RoutingRule(match={"default": True}, target="linear")
        assert rule.shadow_targets == []


class TestShadowTargetValidation:
    def test_valid_shadow_targets(self):
        config = TicketMappingConfig(
            ticket_systems={
                "linear": TicketSystemConfig(system="linear", project="CANON"),
                "jira": TicketSystemConfig(system="jira", project="CAN"),
                "github": TicketSystemConfig(system="github", project="canonhq/canon"),
            },
            routing=[
                RoutingRule(
                    match={"tags": ["product"]},
                    target="linear",
                    shadow_targets=["jira", "github"],
                ),
            ],
        )
        assert len(config.routing) == 1

    def test_invalid_shadow_target_raises(self):
        with pytest.raises(ValidationError, match="unknown shadow target"):
            TicketMappingConfig(
                ticket_systems={
                    "linear": TicketSystemConfig(system="linear", project="CANON"),
                },
                routing=[
                    RoutingRule(
                        match={"default": True},
                        target="linear",
                        shadow_targets=["nonexistent"],
                    ),
                ],
            )

    def test_shadow_target_same_as_primary_raises(self):
        with pytest.raises(ValidationError, match="cannot shadow itself"):
            TicketMappingConfig(
                ticket_systems={
                    "linear": TicketSystemConfig(system="linear", project="CANON"),
                },
                routing=[
                    RoutingRule(
                        match={"default": True},
                        target="linear",
                        shadow_targets=["linear"],
                    ),
                ],
            )

    def test_duplicate_shadow_targets_raises(self):
        with pytest.raises(ValidationError, match="duplicate shadow targets"):
            TicketMappingConfig(
                ticket_systems={
                    "linear": TicketSystemConfig(system="linear", project="CANON"),
                    "jira": TicketSystemConfig(system="jira", project="CAN"),
                },
                routing=[
                    RoutingRule(
                        match={"default": True},
                        target="linear",
                        shadow_targets=["jira", "jira"],
                    ),
                ],
            )


class MockAdapterWithName:
    """Mock adapter that tracks which system it represents."""

    def __init__(self, system: str, ticket_prefix: str):
        self.system = system
        self.ticket_prefix = ticket_prefix
        self.created: list[CreateTicketInput] = []
        self._counter = 0

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        self._counter += 1
        self.created.append(input)
        tid = f"{self.ticket_prefix}-{self._counter}"
        return CreateTicketResult(ticket_id=tid, ticket_url=f"https://example.com/{tid}")

    async def update_ticket(self, input) -> None:
        pass

    async def get_ticket_status(self, ticket_id: str):
        from canon.parser.models import SectionStatus
        from canon.sync.models import TicketStatusResult

        return TicketStatusResult(
            ticket_id=ticket_id,
            status=SectionStatus(state="todo"),
            raw_status="open",
        )

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        pass

    async def search_tickets(self, project_key: str, title_pattern: str) -> list:
        return []

    @property
    def system_name(self) -> str:
        return self.system

    @property
    def capabilities(self):
        from canon.sync.adapters.base import AdapterCapabilities

        return AdapterCapabilities()


class TestMultiTargetForwardSync:
    @pytest.mark.asyncio
    async def test_creates_tickets_in_primary_and_shadow(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Feature

<!-- canon:system:1 status:todo -->

Content.
"""
        doc = parse_spec(raw).document
        primary_adapter = MockAdapterWithName("linear", "LIN")
        shadow_adapters = {
            "jira": (
                MockAdapterWithName("jira", "CAN"),
                TicketSystemConfig(system="jira", project="CAN"),
            ),
            "github": (
                MockAdapterWithName("github", "GH"),
                TicketSystemConfig(system="github", project="canonhq/canon"),
            ),
        }

        _markdown, _result = await forward_sync_multi(
            doc,
            primary_adapter=primary_adapter,
            primary_config=TicketSystemConfig(system="linear", project="CANON"),
            primary_project="CANON",
            shadow_adapters=shadow_adapters,
        )

        # Primary ticket created
        assert len(primary_adapter.created) == 1
        # Shadow tickets created
        assert len(shadow_adapters["jira"][0].created) == 1
        assert len(shadow_adapters["github"][0].created) == 1
        # Shadow tickets should have canon:shadow label
        for _name, (adapter, _cfg) in shadow_adapters.items():
            assert "canon:shadow" in adapter.created[0].labels

    @pytest.mark.asyncio
    async def test_shadow_failure_does_not_block_primary(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Feature

<!-- canon:system:1 status:todo -->

Content.
"""
        doc = parse_spec(raw).document
        primary_adapter = MockAdapterWithName("linear", "LIN")

        failing_adapter = MockAdapterWithName("jira", "CAN")
        failing_adapter.create_ticket = AsyncMock(side_effect=RuntimeError("Jira down"))

        shadow_adapters = {
            "jira": (
                failing_adapter,
                TicketSystemConfig(system="jira", project="CAN"),
            ),
        }

        _markdown, result = await forward_sync_multi(
            doc,
            primary_adapter=primary_adapter,
            primary_config=TicketSystemConfig(system="linear", project="CANON"),
            primary_project="CANON",
            shadow_adapters=shadow_adapters,
        )

        # Primary should succeed
        assert len(result.created) >= 1
        # Shadow error should be in errors
        assert any("Jira down" in e.error for e in result.errors)


class TestPushHandlerMultiTarget:
    def test_resolve_all_targets_integration(self):
        """Verify routing rules with shadows resolve correctly."""
        from canon.sync.router import resolve_all_targets

        systems = {
            "linear": TicketSystemConfig(system="linear", project="CANON"),
            "jira": TicketSystemConfig(system="jira", project="CAN"),
            "github": TicketSystemConfig(system="github", project="canonhq/canon"),
        }
        routing = [
            RoutingRule(
                match={"tags": ["product"]},
                target="linear",
                shadow_targets=["jira", "github"],
            ),
            RoutingRule(match={"default": True}, target="linear"),
        ]

        from canon.parser.models import SpecDocument, SpecFrontmatter

        doc = SpecDocument(
            file_path="docs/specs/test.md",
            frontmatter=SpecFrontmatter(
                title="Test",
                status="draft",
                owner="test",
                team="test",
                tags=["product"],
            ),
            sections=[],
            raw="",
        )

        primary, shadows = resolve_all_targets(None, doc, routing, systems)
        assert primary == "linear"
        assert set(shadows) == {"jira", "github"}


class TestFullMultiTargetConfigParsing:
    def test_canon_yaml_with_routing_and_shadows(self):
        from canon.config.parse import parse_canon_yaml

        raw = """
team: canonhq

ticket_systems:
  github:
    system: github
    project: "canonhq/canon-private"
    status_map:
      forward:
        draft: "open|canon:draft"
        todo: "open|canon:todo"
        in_progress: "open|canon:in-progress"
        done: "closed|canon:done"
        blocked: "open|canon:blocked"
        deprecated: "closed|canon:deprecated"
  linear:
    system: linear
    project: "CANON"
  jira:
    system: jira
    project: "CAN"

routing:
  - match:
      tags: [product, feature, bug]
    target: linear
    shadow_targets: [jira, github]
  - match:
      tags: [community, docs, plugin-sdk]
    target: github
    shadow_targets: [linear]
  - match:
      tags: [enterprise, infra, ops]
    target: jira
    shadow_targets: [linear, github]
  - match:
      default: true
    target: linear

specs:
  auto_tickets: true
  require_review: false
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0

        mapping = result.config.ticket_mapping
        assert mapping is not None
        assert len(mapping.ticket_systems) == 3
        assert len(mapping.routing) == 4
        assert mapping.routing[0].shadow_targets == ["jira", "github"]
        assert mapping.routing[3].shadow_targets == []
