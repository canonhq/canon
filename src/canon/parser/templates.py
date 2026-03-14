"""Doc-type templates for creating new spec documents."""

from __future__ import annotations

from pathlib import Path

from .models import VALID_DOC_TYPES

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def get_template(doc_type: str) -> str:
    """Load a template by document type.

    Raises ValueError if the type is not recognized or the template file is missing.
    """
    if doc_type not in VALID_DOC_TYPES:
        raise ValueError(
            f'Unknown template type: "{doc_type}". '
            f"Valid types: {', '.join(sorted(VALID_DOC_TYPES))}"
        )
    path = _TEMPLATES_DIR / f"{doc_type}.md"
    try:
        return path.read_text()
    except FileNotFoundError:
        raise ValueError(f'Template file missing for type "{doc_type}": {path}') from None


def list_template_types() -> list[str]:
    """Return available template type names.

    Returns types from VALID_DOC_TYPES, not the filesystem. A missing template
    file will only surface when ``get_template()`` is called for that type.
    """
    return sorted(VALID_DOC_TYPES)
