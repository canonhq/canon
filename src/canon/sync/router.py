"""Route spec sections to ticket systems based on metadata matching."""

from __future__ import annotations

import fnmatch

from canon.parser.models import SpecDocument, SpecSection
from canon.sync.mapping import RoutingRule, TicketSystemConfig


def resolve_target(
    section: SpecSection | None,
    doc: SpecDocument,
    routing: list[RoutingRule],
    systems: dict[str, TicketSystemConfig],
) -> str | None:
    """Resolve which ticket system a section should target.

    Evaluates routing rules in order (first match wins). When no routing
    rules are defined and exactly one system exists, returns that system's
    name. Returns None if no match is found.

    ``section`` may be None when routing at doc level — current routing
    criteria only inspect ``doc``, but future section-level criteria
    (e.g. depth) will require a non-None section.
    """
    if not routing:
        if len(systems) == 1:
            return next(iter(systems.keys()))
        return None

    for rule in routing:
        if _matches(rule, section, doc):
            return rule.target

    return None


def _matches(rule: RoutingRule, section: SpecSection | None, doc: SpecDocument) -> bool:
    """Check if a routing rule matches a section.

    Uses AND semantics: all specified criteria must match.
    """
    match = rule.match

    # "default: true" always matches
    if match.get("default") is True:
        return True

    # Each criterion must pass — collect results for non-default keys
    criteria = {k: v for k, v in match.items() if k != "default"}
    if not criteria:
        return False

    for key, value in criteria.items():
        if key == "tags":
            rule_tags = set(value) if isinstance(value, list) else set()
            spec_tags = set(doc.frontmatter.tags)
            if not (rule_tags & spec_tags):
                return False
        elif key == "team":
            if doc.frontmatter.team != value:
                return False
        elif key == "owner":
            if doc.frontmatter.owner != value:
                return False
        elif key == "path":
            if not fnmatch.fnmatch(doc.file_path, value):
                return False

    return True
