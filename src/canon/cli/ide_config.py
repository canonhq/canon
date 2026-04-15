"""canon ide-config — emit IDE config as JSON for hook scripts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._local import load_local_config


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "ide-config",
        help="Emit IDE config (auto_context, auto_verify, ai_exposure) as JSON for hooks",
    )
    # `--json` is the only output mode today; the flag is reserved so that
    # future formats (e.g. `--toml`, `--yaml`) can be added without breaking
    # existing callers that already pass `--json` explicitly.
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON to stdout (currently the only output mode)",
    )


def run_ide_config(*, root: Path | None = None) -> None:
    """Emit the resolved ide: section from CANON.yaml as JSON.

    Always exits 0 — missing CANON.yaml, missing ide: section, AND truly
    malformed YAML all degrade to a JSON document with default values, so
    hook scripts never need to handle error cases. Malformed YAML emits a
    one-line warning to stderr in addition to the defaults on stdout.
    """
    try:
        config = load_local_config(root or Path.cwd())
    except Exception as err:
        print(f"warning: failed to load CANON.yaml ({err}); using defaults", file=sys.stderr)
        from canon.config.parse import DEFAULT_CONFIG

        config = DEFAULT_CONFIG

    payload = config.ide.model_dump()
    print(json.dumps(payload, indent=2))
