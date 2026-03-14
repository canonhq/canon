"""Shared document type classifier for spec files."""

from __future__ import annotations


def classify_doc_type(path: str, spec_patterns: list[str] | None = None) -> str:
    """Classify a document type from its file path.

    Args:
        path: File path to classify.
        spec_patterns: Optional glob patterns identifying spec files.  When
            provided, ``matches_doc_patterns`` is used instead of the
            hard-coded ``docs/specs/`` prefix check.

    Returns one of: spec, adr, readme, changelog, contributing, runbook, plugin, skill, doc.
    """
    lower = path.lower()
    if spec_patterns is not None:
        from ..github.spec_utils import matches_doc_patterns

        if matches_doc_patterns(path, spec_patterns):
            return "spec"
    elif lower.startswith("docs/specs/"):
        return "spec"
    if lower.startswith("docs/adrs/") or "/adr" in lower:
        return "adr"
    if lower.startswith("plugin/skills/") and lower.endswith("skill.md"):
        return "skill"
    if lower.startswith("plugin/") and lower.endswith("readme.md"):
        return "plugin"
    if "readme" in lower:
        return "readme"
    if "changelog" in lower:
        return "changelog"
    if "contributing" in lower:
        return "contributing"
    if "runbook" in lower or "playbook" in lower:
        return "runbook"
    return "doc"
