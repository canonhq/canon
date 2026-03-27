"""Cross-system drift detection for multi-target ticket sync.

Compares ticket statuses between primary and shadow systems to identify
divergence. Drift is informational (warning-level) — no auto-healing.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel

from canon.parser.models import SpecSection

logger = logging.getLogger(__name__)

# Status progression order for drift direction detection
# Only strictly ordered states participate in ordinal comparison.
# Orthogonal states (blocked, deprecated) fall through to status_mismatch.
_STATUS_ORDER = ["draft", "todo", "in_progress", "done"]

DivergenceType = Literal["status_behind", "status_ahead", "status_mismatch"]


class DriftEntry(BaseModel):
    """A single drift observation between primary and shadow."""

    section_id: str
    primary_system: str
    primary_status: str
    shadow_system: str
    shadow_status: str
    divergence_type: DivergenceType


class DriftReport(BaseModel):
    """Drift detection results for a spec document."""

    entries: list[DriftEntry] = []

    @property
    def has_drift(self) -> bool:
        return len(self.entries) > 0


def detect_drift(
    *,
    section: SpecSection,
    primary_status: str,
    shadow_statuses: dict[str, str],
) -> DriftReport:
    """Compare primary status against shadow statuses for a section.

    Returns a DriftReport with entries for each divergent shadow.
    """
    entries: list[DriftEntry] = []
    primary_system = section.ticket_link.system if section.ticket_link else "unknown"

    primary_idx = _STATUS_ORDER.index(primary_status) if primary_status in _STATUS_ORDER else -1

    for shadow_system, shadow_status in shadow_statuses.items():
        if shadow_status == primary_status:
            continue

        shadow_idx = _STATUS_ORDER.index(shadow_status) if shadow_status in _STATUS_ORDER else -1

        if primary_idx >= 0 and shadow_idx >= 0:
            divergence = "status_behind" if shadow_idx < primary_idx else "status_ahead"
        else:
            divergence = "status_mismatch"

        entries.append(
            DriftEntry(
                section_id=section.id,
                primary_system=primary_system,
                primary_status=primary_status,
                shadow_system=shadow_system,
                shadow_status=shadow_status,
                divergence_type=divergence,
            )
        )

    return DriftReport(entries=entries)
