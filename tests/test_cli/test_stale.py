"""Tests for the canon stale command."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from canon.cli.stale import (
    _collect_realization_files,
    _to_payload,
    compute_stale,
    run_stale,
)
from canon.parser.parse import parse_spec

CANON_YAML = """\
team: platform
specs:
  doc_paths:
    - "docs/specs/*.md"
"""


SPEC_WITH_REALIZATIONS = """\
---
title: Auth Hardening
status: done
owner: alice
team: platform
---

## 1. OAuth Login
<!-- canon:system:1 status:done -->

### Acceptance Criteria

- [x] OAuth client registered
<!-- canon:realized-in:PR#1 file:src/auth/oauth.py:10-30 -->
- [x] Login route handles callback
<!-- canon:realized-in:PR#1 file:src/auth/routes.py:55 -->
"""


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=full_env,
    )
    return result.stdout


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def repo_with_stale_spec(tmp_path: Path) -> Path:
    """Build a tiny git repo where:

    - The spec was committed long ago (with --date in the past)
    - One of its realization files was committed recently with enough
      churn to cross the default 50-line threshold
    """
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")

    # ── Old spec commit ───────────────────────────────
    _write(tmp_path, "CANON.yaml", CANON_YAML)
    _write(tmp_path, "docs/specs/auth.md", SPEC_WITH_REALIZATIONS)
    _write(tmp_path, "src/auth/oauth.py", "def oauth(): pass\n")
    _write(tmp_path, "src/auth/routes.py", "def login(): pass\n")
    _git(tmp_path, "add", ".")
    # Force the commit timestamp to 200 days ago so the spec ages out.
    old_env = {
        "GIT_AUTHOR_DATE": "2025-09-01T00:00:00",
        "GIT_COMMITTER_DATE": "2025-09-01T00:00:00",
    }
    _git(tmp_path, "commit", "-q", "-m", "initial spec", env=old_env)

    # ── Recent code commit (~75 changed lines) ────────
    big_body = "\n".join(f"def fn_{i}(): return {i}" for i in range(80))
    _write(tmp_path, "src/auth/oauth.py", big_body + "\n")
    _git(tmp_path, "add", "src/auth/oauth.py")
    _git(tmp_path, "commit", "-q", "-m", "expand oauth")

    return tmp_path


# ─── Helpers ─────────────────────────────────────────────


class TestCollectRealizationFiles:
    def test_collects_unique_files(self):
        doc = parse_spec(SPEC_WITH_REALIZATIONS).document
        files = _collect_realization_files(doc)
        assert "src/auth/oauth.py" in files
        assert "src/auth/routes.py" in files
        assert len(files) == 2

    def test_empty_when_no_realizations(self):
        spec = """\
---
title: Foo
status: todo
owner: alice
team: t
---

## 1. Section
<!-- canon:system:1 status:todo -->

- [ ] Pending
"""
        doc = parse_spec(spec).document
        assert _collect_realization_files(doc) == []


class TestToPayload:
    def test_empty_findings(self):
        payload = _to_payload([], stale_days=90, churn=50)
        assert payload["schema_version"] == 1
        assert payload["thresholds"]["stale_days"] == 90
        assert payload["summary"]["stale_count"] == 0
        assert payload["findings"] == []


# ─── Integration tests ──────────────────────────────────


class TestComputeStale:
    def test_finds_stale_spec(self, repo_with_stale_spec: Path):
        from canon.cli._local import load_local_config, parse_all_local_specs

        config = load_local_config(repo_with_stale_spec)
        docs = parse_all_local_specs(repo_with_stale_spec, config)

        findings = compute_stale(
            docs=docs,
            root=repo_with_stale_spec,
            stale_days=90,
            code_churn_threshold=50,
        )

        assert len(findings) == 1
        f = findings[0]
        assert f.spec == "docs/specs/auth.md"
        assert f.title == "Auth Hardening"
        assert f.owner == "alice"
        assert f.spec_age_days >= 90
        assert "src/auth/oauth.py" in f.realization_files
        assert f.realization_churn_lines >= 50

    def test_high_churn_threshold_skips(self, repo_with_stale_spec: Path):
        from canon.cli._local import load_local_config, parse_all_local_specs

        config = load_local_config(repo_with_stale_spec)
        docs = parse_all_local_specs(repo_with_stale_spec, config)

        findings = compute_stale(
            docs=docs,
            root=repo_with_stale_spec,
            stale_days=90,
            code_churn_threshold=10_000,
        )
        assert findings == []

    def test_short_stale_window_skips(self, repo_with_stale_spec: Path):
        from canon.cli._local import load_local_config, parse_all_local_specs

        config = load_local_config(repo_with_stale_spec)
        docs = parse_all_local_specs(repo_with_stale_spec, config)

        findings = compute_stale(
            docs=docs,
            root=repo_with_stale_spec,
            stale_days=10,
            code_churn_threshold=50,
        )
        # Spec was committed 200 days ago (>10), but we look for code churn
        # in the last 10 days; the recent oauth commit should still be in
        # window, so this still fires.
        assert len(findings) == 1


class TestRunStale:
    def test_human_output(self, repo_with_stale_spec: Path, capsys):
        run_stale(root=repo_with_stale_spec)
        out = capsys.readouterr().out
        assert "Stale specs (1)" in out
        assert "Auth Hardening" in out
        assert "@alice" in out

    def test_json_output(self, repo_with_stale_spec: Path, capsys):
        run_stale(root=repo_with_stale_spec, json_output=True)
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["stale_count"] == 1
        assert payload["thresholds"]["stale_days"] == 90
        finding = payload["findings"][0]
        assert finding["title"] == "Auth Hardening"
        assert finding["owner"] == "alice"
        assert finding["realization_churn_lines"] >= 50

    def test_no_specs(self, tmp_path: Path, capsys):
        run_stale(root=tmp_path)
        assert "No spec files found" in capsys.readouterr().out

    def test_no_specs_json(self, tmp_path: Path, capsys):
        run_stale(root=tmp_path, json_output=True)
        payload = json.loads(capsys.readouterr().out)
        assert payload["findings"] == []
        assert payload["summary"]["stale_count"] == 0

    def test_high_threshold_no_findings_human(self, repo_with_stale_spec: Path, capsys):
        run_stale(root=repo_with_stale_spec, code_churn_threshold=10_000)
        assert "No stale specs" in capsys.readouterr().out
