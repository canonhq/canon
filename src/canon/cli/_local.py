"""Shared local operations for CLI commands.

All CLI commands build on these helpers for discovering, parsing, and
modifying spec files on the local filesystem.
"""

from __future__ import annotations

import glob as globmod
import logging
import subprocess
import warnings
from pathlib import Path

from canon.config.parse import DEFAULT_CONFIG, CanonConfig, parse_canon_yaml
from canon.parser.models import ParseOptions, SpecDocument, SpecSection
from canon.parser.parse import parse_spec
from canon.sync.adapters.base import TicketAdapter
from canon.sync.adapters.factory import from_config
from canon.sync.adapters.github_issues import GitHubAdapter
from canon.sync.mapping import (
    TicketMappingConfig,
    synthesize_mapping_config,
)
from canon.sync.mapping import (
    TicketSystemConfig as TSC,
)
from canon.sync.models import GitHubConfig


def load_local_config(root: Path | None = None) -> CanonConfig:
    """Read CANON.yaml (or legacy SPECWRIGHT.yaml) from repo root, falling back to DEFAULT_CONFIG."""
    root = root or Path.cwd()
    config_path = root / "CANON.yaml"
    if not config_path.exists():
        legacy = root / "SPECWRIGHT.yaml"
        if legacy.exists():
            import sys

            print(
                "WARNING: SPECWRIGHT.yaml is deprecated. Rename to CANON.yaml.",
                file=sys.stderr,
            )
            config_path = legacy
    if not config_path.exists():
        return DEFAULT_CONFIG
    raw = config_path.read_text()
    result = parse_canon_yaml(raw)
    return result.config


def discover_spec_files(root: Path | None = None, config: CanonConfig | None = None) -> list[Path]:
    """Glob local filesystem using config.specs.doc_paths patterns.

    Skips files prefixed with ``_`` (e.g. ``_template.md``).
    """
    root = root or Path.cwd()
    config = config or load_local_config(root)

    found: list[Path] = []
    for pattern in config.specs.doc_paths:
        for match in sorted(globmod.glob(str(root / pattern))):
            path = Path(match)
            if path.name.startswith("_"):
                continue
            if path.is_file():
                found.append(path)
    return found


def parse_all_local_specs(
    root: Path | None = None, config: CanonConfig | None = None
) -> list[SpecDocument]:
    """Discover and parse all spec files."""
    root = root or Path.cwd()
    config = config or load_local_config(root)
    spec_files = discover_spec_files(root, config)

    docs: list[SpecDocument] = []
    for path in spec_files:
        raw = path.read_text()
        rel = str(path.relative_to(root))
        result = parse_spec(raw, ParseOptions(file_path=rel, include_content=True))
        docs.append(result.document)
    return docs


def _flatten_sections(sections: list[SpecSection]) -> list[SpecSection]:
    """Recursively flatten sections and their children."""
    result: list[SpecSection] = []
    for section in sections:
        result.append(section)
        result.extend(_flatten_sections(section.children))
    return result


def find_section_by_id(
    docs: list[SpecDocument], query: str
) -> tuple[SpecDocument, SpecSection] | None:
    """Find a section by exact ID, section number, or partial slug.

    Supports:
    - Exact ID: ``5-live-search``
    - Section number: ``5`` or ``5.1``
    - Partial slug: ``live-search``
    """
    query_lower = query.lower()

    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        # Exact ID match
        for section in all_sections:
            if section.id == query_lower:
                return doc, section

        # Section number match
        for section in all_sections:
            if section.section_number and section.section_number == query:
                return doc, section

        # Partial slug match
        for section in all_sections:
            if query_lower in section.id:
                return doc, section

    return None


def resolve_github_remote(
    config: CanonConfig | None = None, root: Path | None = None
) -> tuple[str, str] | None:
    """Extract owner/repo from CANON.yaml project_key or git remote.

    Returns (owner, repo) or None if unresolvable.
    """
    # Try config project_key first (format: owner/repo)
    if config and config.project_key:
        parts = config.project_key.split("/")
        if len(parts) == 2:
            return parts[0], parts[1]

    # Fall back to git remote
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # SSH: git@github.com:owner/repo.git
            if ":" in url and "@" in url:
                path = url.split(":")[-1].removesuffix(".git")
                parts = path.split("/")
                if len(parts) == 2:
                    return parts[0], parts[1]
            # HTTPS: https://github.com/owner/repo.git
            elif "github.com" in url:
                path = url.split("github.com/")[-1].removesuffix(".git")
                parts = path.split("/")
                if len(parts) == 2:
                    return parts[0], parts[1]
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    return None


def resolve_github_token() -> str | None:
    """Check GITHUB_TOKEN env var then ``gh auth token`` subprocess."""
    import os

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    return None


def create_github_adapter_local(
    config: CanonConfig | None = None, root: Path | None = None
) -> GitHubAdapter | None:
    """Wire token + owner/repo into a GitHubAdapter for local use.

    .. deprecated:: Use :func:`create_adapter_local` instead.
    """
    token = resolve_github_token()
    if not token:
        return None

    remote = resolve_github_remote(config, root)
    if not remote:
        return None

    owner, repo = remote
    return GitHubAdapter(GitHubConfig(token=token, default_owner=owner, default_repo=repo))


def create_adapter_local(
    config: CanonConfig | None = None,
    root: Path | None = None,
    system_name: str | None = None,
) -> tuple[TicketAdapter | None, TicketMappingConfig]:
    """Create a ticket adapter using the new mapping config model.

    Resolves config via ``synthesize_mapping_config`` — works with both legacy
    (ticket_system + project_key) and new (ticket_systems) config formats.

    When *system_name* is given, returns the adapter for that named system.
    Otherwise returns the single system (when only one is configured) or None.

    Returns (adapter, mapping_config) so callers can use routing/hierarchy/etc.
    """
    config = config or load_local_config(root)
    mapping, is_deprecated = synthesize_mapping_config(
        ticket_system=config.ticket_system,
        project_key=config.project_key,
        ticket_mapping=config.ticket_mapping,
    )

    if is_deprecated:
        warnings.warn(
            "Both legacy (ticket_system/project_key) and new (ticket_systems) config found. "
            "Remove the legacy fields — ticket_systems takes precedence.",
            DeprecationWarning,
            stacklevel=2,
        )

    if mapping.is_empty():
        # No ticket config at all — try GitHub adapter fallback for local CLI use
        remote = resolve_github_remote(config, root)
        token = resolve_github_token()
        if token and remote:
            owner, repo_name = remote
            gh_adapter = GitHubAdapter(
                GitHubConfig(token=token, default_owner=owner, default_repo=repo_name)
            )
            fallback_mapping = TicketMappingConfig(
                ticket_systems={"primary": TSC(system="github", project=f"{owner}/{repo_name}")}
            )
            return gh_adapter, fallback_mapping
        return None, mapping

    # Pick which system to create
    if system_name:
        sys_config = mapping.ticket_systems.get(system_name)
        if not sys_config:
            logging.getLogger(__name__).warning("Ticket system %r not found in config", system_name)
            return None, mapping
    else:
        sys_config = mapping.single_system()
        if not sys_config:
            # Multiple systems, no name specified — caller should use routing
            return None, mapping
        system_name = next(iter(mapping.ticket_systems.keys()))

    # Pass None when auth_profiles is empty so from_config uses default env var detection
    adapter = from_config(system_name, sys_config, mapping.auth_profiles or None)
    return adapter, mapping
