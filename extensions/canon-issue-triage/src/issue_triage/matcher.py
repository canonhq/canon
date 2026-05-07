"""Spec matching — parse specs and build summaries for the classifier."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_spec_summaries(specs_dir: Path, glob_pattern: str = "**/*.md") -> list[dict]:
    """Load spec files and extract summaries for the classifier.

    Returns a list of dicts with keys: path, title, status, sections.
    """
    summaries = []

    for spec_path in sorted(specs_dir.glob(glob_pattern)):
        if spec_path.name.startswith("_"):
            continue  # Skip templates

        try:
            summary = _parse_spec_summary(spec_path)
            if summary:
                # Store relative path to avoid exposing absolute filesystem paths
                summary["path"] = str(spec_path.relative_to(specs_dir))
                summaries.append(summary)
        except Exception as e:
            logger.warning("Failed to parse spec %s: %s", spec_path, e)

    return summaries


def _parse_spec_summary(spec_path: Path) -> dict | None:
    """Extract a lightweight summary from a spec file.

    Uses simple parsing to avoid importing the full canon parser
    (which may not be available in extension-only installs).
    """
    content = spec_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Parse YAML frontmatter
    title = ""
    status = "unknown"
    if lines and lines[0].strip() == "---":
        for _i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                break
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip("\"'")
            elif line.startswith("status:"):
                status = line.split(":", 1)[1].strip().strip("\"'")

    if not title:
        # Try to get title from first H1
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break

    if not title:
        return None

    # Extract section headings (## and ###)
    sections = []
    for line in lines:
        if line.startswith("## ") or line.startswith("### "):
            heading = line.lstrip("#").strip()
            # Skip generic headings
            if heading.lower() not in (
                "acceptance criteria",
                "open questions",
                "references",
            ):
                sections.append(heading)

    return {
        "path": "",  # Set by caller with relative path
        "title": title,
        "status": status,
        "sections": sections[:15],  # Cap to keep prompt manageable
    }
