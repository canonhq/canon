"""Tests for the canon new command."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from canon.cli.new_spec import (
    _fill_template,
    _resolve_output_path,
    run_new,
    slugify,
)
from canon.parser.parse import parse_spec
from canon.parser.templates import get_template

CANON_YAML = """\
team: platform
specs:
  doc_paths:
    - "docs/specs/*.md"
"""


# ─── Slugify ──────────────────────────────────────────────


class TestSlugify:
    def test_basic(self):
        assert slugify("Auth Hardening") == "auth-hardening"

    def test_punctuation_collapsed(self):
        assert slugify("OAuth 2.0 / OIDC") == "oauth-2-0-oidc"

    def test_strips_outer_dashes(self):
        assert slugify("---Title---") == "title"

    def test_unicode_falls_back(self):
        # Non-ASCII characters become hyphens, then collapse
        assert slugify("Café — Tøken") == "caf-t-ken"

    def test_empty_falls_back(self):
        assert slugify("") == "untitled"
        assert slugify("   ") == "untitled"

    def test_already_slug(self):
        assert slugify("auth-hardening") == "auth-hardening"


# ─── Template fill ────────────────────────────────────────


class TestFillTemplate:
    def test_substitutes_title(self):
        out = _fill_template(
            get_template("spec"), title="Auth Hardening", owner="alice", team="platform"
        )
        assert 'title: "Auth Hardening"' in out
        assert "# Auth Hardening" in out
        # Original placeholder should not survive
        assert "Untitled Spec" not in out

    def test_substitutes_owner_and_team(self):
        out = _fill_template(get_template("spec"), title="Foo", owner="alice", team="platform")
        assert 'owner: "alice"' in out
        assert 'team: "platform"' in out

    def test_substitutes_dates(self):
        out = _fill_template(get_template("spec"), title="Foo", owner="", team="")
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert f'created: "{today}"' in out
        assert f'updated: "{today}"' in out

    def test_escapes_yaml_quotes(self):
        out = _fill_template(get_template("spec"), title='Title with "quotes"', owner="", team="")
        assert 'title: "Title with \\"quotes\\""' in out

    def test_result_parses_as_valid_spec(self):
        out = _fill_template(
            get_template("spec"),
            title="Auth Hardening",
            owner="alice",
            team="platform",
        )
        # The output must round-trip through the parser without errors
        result = parse_spec(out)
        assert result.document.frontmatter.title == "Auth Hardening"
        assert result.document.frontmatter.owner == "alice"
        assert result.document.frontmatter.team == "platform"


# ─── Output path resolution ──────────────────────────────


class TestResolveOutputPath:
    def test_default_uses_canon_yaml_glob(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text(CANON_YAML)
        path = _resolve_output_path(tmp_path, "Auth Hardening", None)
        assert path == tmp_path / "docs" / "specs" / "auth-hardening.md"

    def test_explicit_relative_override(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text(CANON_YAML)
        path = _resolve_output_path(tmp_path, "Auth Hardening", "specs/x.md")
        assert path == tmp_path / "specs" / "x.md"

    def test_explicit_absolute_override(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text(CANON_YAML)
        absolute = tmp_path / "elsewhere" / "y.md"
        path = _resolve_output_path(tmp_path, "Auth Hardening", str(absolute))
        assert path == absolute

    def test_no_canon_yaml_falls_back(self, tmp_path: Path):
        # No CANON.yaml — should fall back to docs/specs/
        path = _resolve_output_path(tmp_path, "Auth Hardening", None)
        assert path == tmp_path / "docs" / "specs" / "auth-hardening.md"


# ─── Integration tests for run_new ───────────────────────


class TestRunNew:
    def test_creates_file_with_slug(self, tmp_path: Path, capsys):
        (tmp_path / "CANON.yaml").write_text(CANON_YAML)
        exit_code = run_new(
            title="Auth Hardening",
            owner="alice",
            team="platform",
            root=tmp_path,
        )
        assert exit_code == 0
        spec_file = tmp_path / "docs" / "specs" / "auth-hardening.md"
        assert spec_file.exists()
        # Stdout prints the relative path so the action layer can capture it
        out = capsys.readouterr().out
        assert "docs/specs/auth-hardening.md" in out

    def test_file_content_has_filled_frontmatter(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text(CANON_YAML)
        run_new(title="Foo", owner="bob", team="data", root=tmp_path)
        content = (tmp_path / "docs" / "specs" / "foo.md").read_text()
        assert 'title: "Foo"' in content
        assert 'owner: "bob"' in content
        assert 'team: "data"' in content

    def test_refuses_to_overwrite_without_force(self, tmp_path: Path, capsys):
        (tmp_path / "CANON.yaml").write_text(CANON_YAML)
        run_new(title="Foo", root=tmp_path)
        # Second run without --force should fail
        exit_code = run_new(title="Foo", root=tmp_path)
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "already exists" in captured.err

    def test_force_overwrites(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text(CANON_YAML)
        run_new(title="Foo", owner="alice", root=tmp_path)
        run_new(title="Foo", owner="bob", root=tmp_path, force=True)
        content = (tmp_path / "docs" / "specs" / "foo.md").read_text()
        assert 'owner: "bob"' in content

    def test_empty_title_returns_error(self, tmp_path: Path, capsys):
        exit_code = run_new(title="   ", root=tmp_path)
        assert exit_code == 2
        assert "cannot be empty" in capsys.readouterr().err

    def test_explicit_output_path(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text(CANON_YAML)
        target = tmp_path / "custom" / "place.md"
        run_new(title="Foo", output=str(target), root=tmp_path)
        assert target.exists()

    def test_proposal_type(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text(CANON_YAML)
        run_new(title="My Idea", doc_type="proposal", root=tmp_path)
        content = (tmp_path / "docs" / "specs" / "my-idea.md").read_text()
        # The proposal template should produce parseable output
        assert "title:" in content
