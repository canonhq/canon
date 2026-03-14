"""Shared test fixtures for Canon tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the docs/examples/ directory containing test fixtures."""
    return Path(__file__).resolve().parent.parent / "docs" / "examples"


@pytest.fixture
def payments_spec(fixtures_dir: Path) -> str:
    """Raw markdown content of payments-overhaul.md."""
    return (fixtures_dir / "payments-overhaul.md").read_text()


@pytest.fixture
def auth_spec(fixtures_dir: Path) -> str:
    """Raw markdown content of auth-migration.md."""
    return (fixtures_dir / "auth-migration.md").read_text()
