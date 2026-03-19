"""Template rendering for ticket summary and description.

Supports a simple Mustache-style syntax:

- ``{{var}}`` — variable interpolation
- ``{{#each var}}...{{this}}...{{/each}}`` — list iteration

Nesting of ``{{#each}}`` blocks is not supported and will produce
incorrect output — the inner ``{{/each}}`` closes the outer block.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from canon.parser.models import SpecDocument, SpecSection
from canon.sync.mapping import TemplateConfig

# Matches canon/specwright HTML comments (ticket, status, delta, realized-in)
_CANON_COMMENT_RE = re.compile(r"<!--\s*(?:specwright|canon):\S.*?-->\n?")


def _clean_content(content: str) -> str:
    """Strip canon/specwright HTML comments from section content.

    Removes ticket links, status comments, delta annotations, and
    realization refs so they don't appear in ticket descriptions.
    """
    return _CANON_COMMENT_RE.sub("", content).strip()


def _build_context(
    section: SpecSection,
    doc: SpecDocument,
    spec_url: str = "",
) -> dict[str, Any]:
    """Build the template variable context."""
    fingerprint = make_fingerprint(doc, section) if section.section_number else ""
    return {
        "section.title": section.title,
        "section.content": section.content,
        "section.clean_content": _clean_content(section.content),
        "section.section_number": section.section_number or "",
        "section.depth": str(section.depth),
        "section.id": section.id,
        "section.acceptance_criteria": [ac.text for ac in section.acceptance_criteria],
        "section.ac_count": str(len(section.acceptance_criteria)),
        "spec.title": doc.frontmatter.title,
        "spec.owner": doc.frontmatter.owner,
        "spec.team": doc.frontmatter.team,
        "spec.tags": doc.frontmatter.tags,
        "spec.file_path": doc.file_path,
        "spec_url": spec_url,
        "fingerprint": fingerprint,
    }


def _substitute_vars(text: str, context: dict[str, Any]) -> str:
    """Positional substitution of ``{{var}}`` tokens.

    Walks the text left-to-right, replacing each ``{{var}}`` with its
    context value. Values are inserted literally (never re-scanned),
    which prevents injection from user content.
    """
    parts: list[str] = []
    last_end = 0
    for m in re.finditer(r"\{\{([^#/].*?)\}\}", text):
        parts.append(text[last_end : m.start()])
        var_name = m.group(1).strip()
        value = context.get(var_name, "")
        if isinstance(value, list):
            parts.append(", ".join(str(v) for v in value))
        else:
            parts.append(str(value))
        last_end = m.end()
    parts.append(text[last_end:])
    return "".join(parts)


def _render(template: str, context: dict[str, Any]) -> str:
    """Render a template with the given context.

    Uses positional substitution: template tokens are replaced left-to-right
    with context values. Values are never re-scanned for template syntax,
    preventing injection from spec content.
    """

    # ── Phase 1: expand {{#each}} blocks ─────────────────
    # Each block's body is rendered per-item with {{this}} replaced
    # positionally (not via string replace, to prevent re-scanning).
    parts: list[str] = []
    last_end = 0

    for m in re.finditer(r"\{\{#each\s+(.+?)\}\}(.*?)\{\{/each\}\}", template, flags=re.DOTALL):
        # Add text before this block (may contain {{var}} tokens)
        parts.append(_substitute_vars(template[last_end : m.start()], context))

        var_name = m.group(1).strip()
        body = m.group(2)
        items = context.get(var_name, [])
        if isinstance(items, list):
            for item in items:
                # Replace {{this}} positionally within the body
                item_context = {**context, "this": str(item)}
                parts.append(_substitute_vars(body, item_context))
        last_end = m.end()

    # Add remaining text after last block
    parts.append(_substitute_vars(template[last_end:], context))

    return "".join(parts)


# ─── Fingerprints ────────────────────────────────────────


def make_fingerprint(doc: SpecDocument, section: SpecSection) -> str:
    """Generate a deterministic section fingerprint.

    Format: ``<!-- canon:section:{spec_slug}:{section_number} -->``

    The slug is derived from the spec file path (without extension),
    so fingerprints are stable across section title renames.
    """
    path = doc.file_path
    if path:
        p = PurePosixPath(path)
        slug = str(p.with_suffix("")) if p.name else path
    else:
        slug = "unknown"
    return f"<!-- canon:section:{slug}:{section.section_number} -->"


# ─── Public API ──────────────────────────────────────────


DEFAULT_SUMMARY_TEMPLATE = "[{{spec.title}} §{{section.section_number}}] {{section.title}}"
DEFAULT_DESCRIPTION_TEMPLATE = """\
> **Spec:** [{{spec.title}}]({{spec_url}}) | **Section:** {{section.section_number}}

{{section.clean_content}}

{{#each section.acceptance_criteria}}- [ ] {{this}}
{{/each}}
---
<sub>Managed by <a href="https://canonhq.co">Canon</a>\
 · <b>Team:</b> {{spec.team}} · <b>Owner:</b> {{spec.owner}}</sub>"""


def render_summary(
    section: SpecSection,
    doc: SpecDocument,
    config: TemplateConfig | None = None,
    spec_url: str = "",
) -> str:
    """Render ticket summary from template or default."""
    template = (config.summary if config else None) or DEFAULT_SUMMARY_TEMPLATE
    context = _build_context(section, doc, spec_url)
    return _render(template, context)


def render_description(
    section: SpecSection,
    doc: SpecDocument,
    config: TemplateConfig | None = None,
    spec_url: str = "",
) -> str:
    """Render ticket description from template or default.

    Uses the structured default template which includes a spec link,
    clean content (without canon/specwright HTML comments), acceptance criteria
    checkboxes, and a Canon footer. A section fingerprint is appended for
    dedup unless the rendered body already contains it (e.g. via a custom
    template that uses ``{{fingerprint}}``).
    """
    template = (config.description if config else None) or DEFAULT_DESCRIPTION_TEMPLATE
    context = _build_context(section, doc, spec_url)
    body = _render(template, context)

    # Append fingerprint for dedup — skip if template already included it
    if section.section_number:
        fingerprint = make_fingerprint(doc, section)
        if fingerprint not in body:
            body = body + "\n\n" + fingerprint

    return body
