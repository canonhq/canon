"""CLI command: canon dedup — find and resolve duplicate tickets."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from canon.cli._local import create_adapter_local, discover_spec_files, load_local_config
from canon.parser.models import ParseOptions
from canon.parser.parse import parse_spec
from canon.sync.dedup import find_duplicates, rewrite_unknown_systems
from canon.sync.mapping import TicketMappingConfig


def register(subparsers) -> None:
    p = subparsers.add_parser("dedup", help="Find and resolve duplicate tickets")
    p.add_argument("--dry-run", action="store_true", help="Preview changes without acting")
    p.add_argument("--spec", type=str, help="Path to specific spec file")


def _resolve_project_key(mapping: TicketMappingConfig) -> str:
    """Extract a project key from mapping config."""
    single = mapping.single_system()
    if single and single.project:
        return single.project
    return ""


def run_dedup(*, dry_run: bool = False, spec: str | None = None) -> None:
    """Find and resolve duplicate tickets for spec sections."""
    config = load_local_config()
    adapter, mapping = create_adapter_local(config)
    if adapter is None:
        print("Error: no ticket adapter configured")
        sys.exit(1)

    project_key = _resolve_project_key(mapping)

    spec_files = [Path(spec)] if spec else discover_spec_files(config=config)

    total_unknown = 0
    total_groups = 0

    for spec_path in spec_files:
        if not spec_path.exists():
            print(f"Warning: {spec_path} not found, skipping")
            continue

        raw = spec_path.read_text()

        # Step 1: Rewrite ticket:unknown → ticket:github
        updated, unknown_count = rewrite_unknown_systems(raw)
        if unknown_count > 0:
            total_unknown += unknown_count
            if dry_run:
                print(
                    f"  [dry-run] Would rewrite {unknown_count} "
                    f"ticket:unknown → ticket:github in {spec_path.name}"
                )
            else:
                spec_path.write_text(updated)
                print(
                    f"  Rewrote {unknown_count} ticket:unknown → ticket:github in {spec_path.name}"
                )
            raw = updated

        # Step 2: Search for duplicate tickets
        result = parse_spec(raw, ParseOptions(file_path=str(spec_path)))

        # Resolve project key from spec frontmatter or config
        doc_project = result.document.frontmatter.ticket_project or project_key
        if not doc_project:
            continue

        dedup_result = asyncio.run(find_duplicates(result.document, adapter, doc_project))

        for group in dedup_result.groups:
            total_groups += 1
            keep = group.keep
            dupes = [t for t in group.tickets if t.ticket_id != keep.ticket_id]
            print(f"\n  Section: {group.section_title}")
            print(f"    Keep: #{keep.ticket_id} ({keep.state})")
            for dupe in dupes:
                if dry_run:
                    print(f"    [dry-run] Would close: #{dupe.ticket_id} ({dupe.state})")
                else:
                    print(f"    Close: #{dupe.ticket_id} ({dupe.state})")

        for error in dedup_result.errors:
            print(f"  Error: {error}")

    print(
        f"\nSummary: {total_unknown} unknown links rewritten, {total_groups} duplicate groups found"
    )
