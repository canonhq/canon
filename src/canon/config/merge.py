"""Deep merge for org-level config defaults."""

from __future__ import annotations

from typing import Any


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``overlay`` on top of ``base``.

    Rules:
    - Dicts are merged recursively key-by-key
    - Lists in overlay replace base lists (no appending)
    - Scalars in overlay override base scalars
    - Explicit ``None`` in overlay deletes the key from the result
    - Keys only in base are preserved
    """
    result: dict[str, Any] = {}

    # Start with all base keys
    for key in base:
        if key in overlay:
            overlay_val = overlay[key]
            base_val = base[key]

            if overlay_val is None:
                # Explicit null deletes the key
                continue
            elif isinstance(base_val, dict) and isinstance(overlay_val, dict):
                result[key] = deep_merge(base_val, overlay_val)
            else:
                # Lists, scalars: overlay wins
                result[key] = overlay_val
        else:
            result[key] = base[key]

    # Add keys only in overlay
    for key in overlay:
        if key not in base and overlay[key] is not None:
            result[key] = overlay[key]

    return result
