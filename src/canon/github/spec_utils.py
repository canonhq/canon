"""Spec file detection and loading utilities."""

from __future__ import annotations

import logging
import re

from ..config.parse import DEFAULT_CONFIG, parse_canon_yaml
from ..parser.models import ParseOptions
from ..parser.parse import parse_spec

logger = logging.getLogger(__name__)

SPEC_FILE_RE = re.compile(r"^docs/specs/[^/]+\.md$")

# Files that are config/CI-only and unlikely to relate to any spec
CONFIG_ONLY_RE = re.compile(r"^(\.(github|vscode|husky)/|.*\.(ya?ml|json|lock|toml)$)")

# Default doc patterns when no CANON.yaml doc_paths is configured
DEFAULT_DOC_PATTERNS = ["docs/specs/*.md"]


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a glob pattern to a regex that treats ``/`` as a path separator.

    - ``*`` matches anything except ``/``
    - ``**`` matches anything including ``/`` (recursive)
    - ``?`` matches any single character except ``/``
    """
    i, n = 0, len(pattern)
    parts: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # ** — match any path segments
                parts.append(".*")
                i += 2
                # skip trailing /
                if i < n and pattern[i] == "/":
                    i += 1
            else:
                # * — match within one path segment
                parts.append("[^/]*")
                i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        elif c == ".":
            parts.append(r"\.")
            i += 1
        else:
            parts.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def is_spec_file(path: str, patterns: list[str] | None = None) -> bool:
    """Check if a path is a spec file.

    When *patterns* is provided, delegates to :func:`matches_doc_patterns`.
    Otherwise falls back to the built-in ``SPEC_FILE_RE`` for backwards
    compatibility with callers that don't have config available.
    """
    if patterns is not None:
        return matches_doc_patterns(path, patterns)
    return bool(SPEC_FILE_RE.match(path))


def filter_spec_files(paths: list[str], patterns: list[str] | None = None) -> list[str]:
    """Filter a list of paths to only spec files."""
    return [p for p in paths if is_spec_file(p, patterns=patterns)]


def matches_doc_patterns(path: str, patterns: list[str]) -> bool:
    """Check if a path matches any of the given glob patterns.

    Supports both single-level globs (e.g. ``docs/specs/*.md``) and
    recursive globs (e.g. ``docs/rfcs/**/*.md``).  Treats ``/`` as a
    path separator so ``*`` does not cross directory boundaries.
    """
    return any(_glob_to_regex(pattern).match(path) for pattern in patterns)


def extract_directories(patterns: list[str]) -> list[tuple[str, bool]]:
    """Derive directory prefixes and recursion flag from glob patterns.

    Returns a list of (directory, is_recursive) tuples.
    For ``docs/specs/*.md`` → ``("docs/specs", False)``
    For ``docs/rfcs/**/*.md`` → ``("docs/rfcs", True)``
    For ``*.md`` → ``("", False)``
    """
    dirs: list[tuple[str, bool]] = []
    for pattern in patterns:
        is_recursive = "**" in pattern
        # Strip the glob portion to find the directory prefix
        # e.g. "docs/specs/*.md" → "docs/specs"
        # e.g. "docs/rfcs/**/*.md" → "docs/rfcs"
        parts = pattern.split("/")
        dir_parts = []
        for part in parts:
            if "*" in part or "?" in part:
                break
            dir_parts.append(part)
        directory = "/".join(dir_parts)
        dirs.append((directory, is_recursive))
    return dirs


async def load_repo_config(
    client,  # GitHubClient
    owner: str,
    repo: str,
    ref: str | None = None,
    cache=None,
):
    """Load CANON.yaml (or legacy SPECWRIGHT.yaml) config for a repo, with optional cache and fallback.

    Args:
        client: GitHubClient instance.
        owner: Repository owner.
        repo: Repository name.
        ref: Git ref to use.
        cache: Optional TTLCache instance for config caching.

    Returns the parsed SpecwrightConfig, or DEFAULT_CONFIG on failure.
    """
    if cache is not None:
        cached = cache.get(f"config:{owner}/{repo}")
        if cached is not None:
            return cached

    try:
        try:
            content, _sha = await client.get_file_content(owner, repo, "CANON.yaml", ref=ref)
        except Exception:
            content, _sha = await client.get_file_content(owner, repo, "SPECWRIGHT.yaml", ref=ref)
        result = parse_canon_yaml(content)
        if result.config:
            return result.config
    except Exception:
        pass

    return DEFAULT_CONFIG


async def load_repo_docs(
    client,  # GitHubClient
    owner: str,
    repo: str,
    patterns: list[str] | None = None,
    ref: str | None = None,
) -> list[dict]:
    """Load and parse all docs matching the given glob patterns.

    Args:
        client: GitHubClient instance.
        owner: Repository owner.
        repo: Repository name.
        patterns: List of glob patterns. Defaults to DEFAULT_DOC_PATTERNS.
        ref: Git ref to use.

    Returns a list of dicts with 'file_path', 'document', and 'raw' keys.
    """
    if patterns is None:
        patterns = DEFAULT_DOC_PATTERNS

    directories = extract_directories(patterns)
    seen_paths: set[str] = set()
    all_entries: list[dict] = []

    for directory, is_recursive in directories:
        if is_recursive:
            # Use Git Trees API for recursive listing
            entries = await _list_tree_recursive(client, owner, repo, directory, ref=ref)
        else:
            entries = await client.list_directory(owner, repo, directory, ref=ref)

        for entry in entries:
            path = entry.get("path", "")
            if (
                path not in seen_paths
                and entry.get("type") in ("file", "blob")
                and path.endswith(".md")
                and not entry.get("name", path.rsplit("/", 1)[-1]).startswith("_")
                and matches_doc_patterns(path, patterns)
            ):
                seen_paths.add(path)
                all_entries.append(entry)

    docs = []
    for entry in all_entries:
        file_path = entry["path"]
        try:
            content, _sha = await client.get_file_content(owner, repo, file_path, ref=ref)
            result = parse_spec(content, ParseOptions(file_path=file_path))
            docs.append({"file_path": file_path, "document": result.document, "raw": content})
        except Exception:
            logger.warning("Failed to load/parse doc file: %s", file_path)

    return docs


async def _list_tree_recursive(
    client,  # GitHubClient
    owner: str,
    repo: str,
    prefix: str,
    ref: str | None = None,
) -> list[dict]:
    """List all files under a prefix using the Git Trees API (recursive).

    Falls back to Contents API listing if Trees API fails.
    """
    try:
        tree_ref = ref or "HEAD"
        data = await client._get(
            f"/repos/{owner}/{repo}/git/trees/{tree_ref}",
            recursive="true",
        )
        tree = data.get("tree", [])
        return [
            {"path": item["path"], "type": item["type"], "name": item["path"].rsplit("/", 1)[-1]}
            for item in tree
            if item["type"] == "blob"
            and (item["path"].startswith(prefix + "/") if prefix else True)
        ]
    except Exception:
        logger.warning("Git Trees API failed for %s/%s, falling back to Contents API", owner, repo)
        return await client.list_directory(owner, repo, prefix, ref=ref)


async def load_repo_specs(
    client,  # GitHubClient
    owner: str,
    repo: str,
    ref: str | None = None,
    patterns: list[str] | None = None,
) -> list[dict]:
    """Load and parse all spec documents from a repository.

    Args:
        client: GitHubClient instance.
        owner: Repository owner.
        repo: Repository name.
        ref: Git ref to use.
        patterns: Glob patterns for spec files.  Defaults to
            :data:`DEFAULT_DOC_PATTERNS` (``docs/specs/*.md``).

    Returns a list of dicts with 'file_path', 'document', and 'raw' keys.
    Returns empty list if no matching directories exist.
    """
    if patterns is None:
        patterns = DEFAULT_DOC_PATTERNS

    directories = extract_directories(patterns)
    seen_paths: set[str] = set()
    all_entries: list[dict] = []

    for directory, is_recursive in directories:
        if is_recursive:
            entries = await _list_tree_recursive(client, owner, repo, directory, ref=ref)
        else:
            entries = await client.list_directory(owner, repo, directory, ref=ref)

        for entry in entries:
            path = entry.get("path", "")
            if (
                path not in seen_paths
                and entry.get("type") in ("file", "blob")
                and path.endswith(".md")
                and not entry.get("name", path.rsplit("/", 1)[-1]).startswith("_")
                and matches_doc_patterns(path, patterns)
            ):
                seen_paths.add(path)
                all_entries.append(entry)

    specs = []
    for entry in all_entries:
        file_path = entry["path"]
        try:
            content, file_sha = await client.get_file_content(owner, repo, file_path, ref=ref)
            result = parse_spec(content, ParseOptions(file_path=file_path))
            specs.append(
                {
                    "file_path": file_path,
                    "document": result.document,
                    "raw": content,
                    "sha": file_sha,
                }
            )
        except Exception:
            logger.warning("Failed to load/parse spec file: %s", file_path)

    return specs
