"""End-to-end test for the canon-implement workflow's CLI dependencies.

This test exercises the CLI plumbing that `canon-implement` orchestrates:
plan generation → gate verification (fail) → realization → gate verification
(pass) → status. It does NOT run a real Claude Code session — that would
require subprocess'ing Claude Code itself, which is not feasible in CI.

What this test catches:
- Regressions in `canon plan` output shape
- Regressions in `canon verify --gate` exit semantics
- Regressions in spec parsing / realization comment handling
- Regressions in `canon status --json` aggregate metrics
- Regressions in the workflow's overall plumbing (the four CLI commands
  that any canon-implement run depends on)

What this test does NOT catch:
- Regressions in the canon-implement *skill* prompt content (covered by
  test_skills_content.py assertions)
- Regressions in the canon-reviewer *agent* dispatch (requires Claude Code)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "toy_spec"


def run_canon(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "canon", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestImplementWorkflowE2E:
    def test_plan_then_gate_fail_then_realize_then_gate_pass(self, tmp_path: Path):
        # 1. Copy the toy fixture into a fresh tmp dir
        repo = tmp_path / "toy"
        shutil.copytree(FIXTURE_DIR, repo)

        # 2. Run `canon plan` against the toy spec — should produce task output
        plan = run_canon(["plan", "toy"], cwd=repo)
        assert plan.returncode == 0, f"canon plan failed: {plan.stderr}"
        assert "Greeter" in plan.stdout or "greeter" in plan.stdout.lower()
        assert "Echo" in plan.stdout or "echo" in plan.stdout.lower()

        # 3. `canon verify --gate` should FAIL with 4 unchecked ACs
        gate1 = run_canon(["verify", "--gate"], cwd=repo)
        assert gate1.returncode == 1, "gate should fail when ACs are unchecked"
        assert "FAIL" in gate1.stdout
        assert "4" in gate1.stdout, "gate should report 4 unchecked ACs"

        # 4. `canon status --json` should show 0% coverage
        status1 = run_canon(["status", "--json"], cwd=repo)
        assert status1.returncode == 0
        data1 = json.loads(status1.stdout)
        assert data1["summary"]["specs"] == 1
        assert data1["summary"]["ac_total"] == 4
        assert data1["summary"]["ac_done"] == 0
        assert data1["summary"]["coverage_pct"] == 0.0

        # 5. Edit src/toy.py to add the implementation
        (repo / "src" / "toy.py").write_text(
            '''"""Toy module — implemented for the e2e test."""


def greeter(name: str = "") -> str:
    """Return a greeting."""
    if not name:
        return "Hello, world"
    return f"Hello, {name}"


def echo(text: str) -> str:
    """Return the input string unchanged."""
    if not isinstance(text, str):
        raise TypeError("echo expects a string")
    return text
'''
        )

        # 6. Edit docs/specs/toy.md to mark all 4 ACs as checked + add realization comments
        (repo / "docs" / "specs" / "toy.md").write_text(
            """---
title: "Toy Feature for E2E Test"
status: in_progress
owner: test
team: canon
created: 2026-04-11
updated: 2026-04-11
tags: [test, fixture]
---

# Toy Feature for E2E Test

A fixture spec used by the plugin workflow integration test.

## 1. Greeter

<!-- canon:system:1 status:done -->

The toy module provides a greeter function.

### Acceptance Criteria

- [x] Greeter accepts a name argument and returns a greeting string
<!-- canon:realized-in:e2e-test file:src/toy.py:4-9 -->
- [x] Greeter returns "Hello, world" when name is empty
<!-- canon:realized-in:e2e-test file:src/toy.py:6-7 -->

## 2. Echo

<!-- canon:system:2 status:done -->

The toy module provides an echo function.

### Acceptance Criteria

- [x] Echo returns the input string unchanged
<!-- canon:realized-in:e2e-test file:src/toy.py:12-16 -->
- [x] Echo raises TypeError when input is not a string
<!-- canon:realized-in:e2e-test file:src/toy.py:14-15 -->
"""
        )

        # 7. `canon verify --gate` should now PASS
        gate2 = run_canon(["verify", "--gate"], cwd=repo)
        assert gate2.returncode == 0, f"gate should pass after realization: {gate2.stdout}"
        assert "PASS" in gate2.stdout

        # 8. `canon status --json` should now show 100% coverage
        status2 = run_canon(["status", "--json"], cwd=repo)
        assert status2.returncode == 0
        data2 = json.loads(status2.stdout)
        assert data2["summary"]["ac_done"] == 4
        assert data2["summary"]["coverage_pct"] == 100.0
        assert data2["summary"]["ac_total"] == data2["summary"]["ac_done"]
