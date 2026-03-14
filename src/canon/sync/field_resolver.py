"""Resolve field mappings from spec metadata to ticket fields."""

from __future__ import annotations

import re
from typing import Any

from canon.parser.models import SpecDocument, SpecSection
from canon.sync.mapping import FieldMapConfig


def _get_source_value(
    source: str,
    section: SpecSection,
    doc: SpecDocument,
) -> Any:
    """Extract a value from the spec model given a source path.

    Supports:
    - "frontmatter.<field>" — reads from doc.frontmatter
    - "section.<field>" — reads from the section
    - "literal:<value>" — returns the literal string
    - Indexed access like "frontmatter.tags[0]"
    """
    if source.startswith("literal:"):
        return source[len("literal:") :]

    # Check for indexed access: "frontmatter.tags[0]"
    index_match = re.match(r"^(.+)\[(\d+)\]$", source)
    base_source = index_match.group(1) if index_match else source
    index = int(index_match.group(2)) if index_match else None

    parts = base_source.split(".", 1)
    if len(parts) != 2:
        return None

    namespace, field = parts

    if namespace == "frontmatter":
        value = getattr(doc.frontmatter, field, None)
    elif namespace == "section":
        if field == "acceptance_criteria":
            value = [ac.text for ac in section.acceptance_criteria]
        else:
            value = getattr(section, field, None)
    else:
        return None

    if index is not None and isinstance(value, list):
        if 0 <= index < len(value):
            return value[index]
        return None

    return value


def resolve_standard_fields(
    section: SpecSection,
    doc: SpecDocument,
    field_map: FieldMapConfig,
) -> dict[str, Any]:
    """Resolve standard field mappings to a dict of ticket_field → value."""
    result: dict[str, Any] = {}
    for source, ticket_field in field_map.standard.items():
        value = _get_source_value(source, section, doc)
        if value is not None:
            result[ticket_field] = value
    return result


def resolve_custom_fields(
    section: SpecSection,
    doc: SpecDocument,
    field_map: FieldMapConfig,
) -> dict[str, Any]:
    """Resolve custom field mappings (e.g. Jira custom field IDs)."""
    result: dict[str, Any] = {}
    for field_id, source in field_map.custom.items():
        value = _get_source_value(source, section, doc)
        if value is not None:
            result[field_id] = value
    return result


def resolve_fields(
    section: SpecSection,
    doc: SpecDocument,
    field_map: FieldMapConfig | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve all field mappings for a section.

    Returns (standard_fields, custom_fields).
    """
    if field_map is None or (not field_map.standard and not field_map.custom):
        return {}, {}

    standard = resolve_standard_fields(section, doc, field_map)
    custom = resolve_custom_fields(section, doc, field_map)
    return standard, custom
