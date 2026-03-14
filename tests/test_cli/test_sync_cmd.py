"""Tests for canon sync command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from canon.cli.sync_cmd import run_sync
from canon.sync.mapping import TicketMappingConfig, TicketSystemConfig

SAMPLE_SPEC = """\
---
title: Auth Spec
status: active
owner: dev
team: platform
ticket_project: org/repo
---

## 1. Login Flow
<!-- specwright:system:1 status:todo -->

### Acceptance Criteria

- [ ] Username validation
"""

SAMPLE_CONFIG = """\
team: platform
ticket_system: github
project_key: org/repo
specs:
  doc_paths:
    - "docs/specs/*.md"
  require_review: false
"""

_DEFAULT_MAPPING = TicketMappingConfig(
    ticket_systems={"primary": TicketSystemConfig(system="github", project="org/repo")}
)


def _setup(tmp_path: Path) -> Path:
    (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "auth.md").write_text(SAMPLE_SPEC)
    return tmp_path


class TestRunSync:
    def test_no_token_exits(self, tmp_path: Path):
        _setup(tmp_path)
        with (
            patch(
                "canon.cli.sync_cmd._try_remote_adapter",
                return_value=None,
            ),
            patch(
                "canon.cli.sync_cmd.create_adapter_local",
                return_value=(None, TicketMappingConfig()),
            ),
            pytest.raises(SystemExit),
        ):
            run_sync(root=tmp_path)

    def test_no_specs(self, tmp_path: Path, capsys):
        (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
        mock_adapter = AsyncMock()
        with patch(
            "canon.cli.sync_cmd.create_adapter_local",
            return_value=(mock_adapter, _DEFAULT_MAPPING),
        ):
            run_sync(root=tmp_path)
            output = capsys.readouterr().out
            assert "No spec files found" in output

    def test_dry_run_no_write(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        from canon.sync.models import SyncResult

        mock_adapter = AsyncMock()

        with (
            patch(
                "canon.cli.sync_cmd.create_adapter_local",
                return_value=(mock_adapter, _DEFAULT_MAPPING),
            ),
            patch("canon.sync.engine.forward_sync", return_value=(SAMPLE_SPEC, SyncResult())),
        ):
            run_sync(dry_run=True, root=tmp_path)
            output = capsys.readouterr().out
            assert "No changes" in output
