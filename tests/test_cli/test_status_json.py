"""Tests for `canon status --json` aggregate output."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_status_json(cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "canon", "status", "--json"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestStatusJson:
    def test_empty_project_returns_zero_metrics(self, tmp_path: Path):
        rc, out, _ = run_status_json(tmp_path)
        assert rc == 0
        data = json.loads(out)
        assert "summary" in data
        assert data["summary"]["specs"] == 0
        assert data["summary"]["coverage_pct"] == 0.0

    def test_canon_repo_returns_real_metrics(self, tmp_path: Path):
        # Create a tiny Canon project with one spec.
        (tmp_path / "CANON.yaml").write_text("specs:\n  doc_paths:\n    - docs/specs/*.md\n")
        specs_dir = tmp_path / "docs" / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "example.md").write_text(
            "---\n"
            "title: Example\n"
            "status: in_progress\n"
            "---\n"
            "# Example\n"
            "## 1. Background\n"
            "<!-- canon:system:1 status:done -->\n"
            "### Acceptance Criteria\n"
            "- [x] First AC\n"
            "- [ ] Second AC\n"
        )
        rc, out, _ = run_status_json(tmp_path)
        assert rc == 0
        data = json.loads(out)
        assert data["summary"]["specs"] == 1
        assert data["summary"]["ac_total"] == 2
        assert data["summary"]["ac_done"] == 1
        assert data["summary"]["coverage_pct"] == 50.0
        # Per-spec detail
        assert len(data["specs"]) == 1
        assert data["specs"][0]["title"] == "Example"
