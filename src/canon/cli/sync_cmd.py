"""canon sync — forward/reverse ticket sync."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from canon.config.parse import CanonConfig
from canon.sync.mapping import TicketMappingConfig
from canon.sync.mapping import TicketSystemConfig as TSC
from canon.sync.router import resolve_target

from ._local import (
    create_adapter_local,
    load_local_config,
    parse_all_local_specs,
)


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("sync", help="Sync spec sections with ticket system")
    parser.add_argument(
        "--reverse", action="store_true", help="Pull ticket statuses into spec markdown"
    )
    parser.add_argument("--spec", help="Filter to a single spec file")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Bypass server proxy and use GITHUB_TOKEN / gh CLI directly",
    )


def _try_remote_adapter(
    config: CanonConfig, root: Path
) -> tuple[object, TicketMappingConfig] | None:
    """Try to create a server-proxied adapter for logged-in users.

    Returns (adapter, mapping) if credentials exist and the ticket system is
    GitHub (the only system the proxy supports), otherwise None.
    """
    from canon.sync.adapters.api_proxy import CanonApiAdapter

    from ._credentials import load_credentials
    from ._local import resolve_github_remote
    from ._platform import PlatformClient

    cred = load_credentials()
    if cred is None:
        return None

    # API proxy only supports GitHub for now.
    # When ticket_system is None (unconfigured), we assume GitHub as the default.
    if config.ticket_system and config.ticket_system != "github":
        return None

    remote = resolve_github_remote(config, root)
    if not remote:
        return None

    owner, repo = remote

    # Resolve org from credentials, falling back to repo owner
    org = cred.get("org_login", "") or cred.get("org", "") or owner
    if not org:
        return None

    client = PlatformClient()
    adapter = CanonApiAdapter(client, org, owner, repo)
    mapping = TicketMappingConfig(
        ticket_systems={"primary": TSC(system="github", project=f"{owner}/{repo}")}
    )
    return adapter, mapping


def run_sync(
    *,
    reverse: bool = False,
    spec: str | None = None,
    dry_run: bool = False,
    local: bool = False,
    root: Path | None = None,
) -> None:
    root = root or Path.cwd()
    config = load_local_config(root)

    if local:
        adapter, mapping = create_adapter_local(config, root)
    else:
        result = _try_remote_adapter(config, root)
        if result is not None:
            adapter, mapping = result
            print("Using Canon server proxy (no local GITHUB_TOKEN needed)")
        else:
            adapter, mapping = create_adapter_local(config, root)

    if not adapter and mapping.is_empty():
        print("Error: No ticket system configured and no GitHub token available.")
        print("Set GITHUB_TOKEN, install gh CLI, or configure ticket_systems in CANON.yaml.")
        sys.exit(1)

    docs = parse_all_local_specs(root, config)
    if spec:
        docs = [d for d in docs if spec in d.file_path]

    if not docs:
        print("No spec files found.")
        return

    from canon.sync.adapters.factory import from_config
    from canon.sync.engine import forward_sync, reverse_sync

    for doc in docs:
        print(f"\n{doc.frontmatter.title} ({doc.file_path})")
        print("-" * 50)

        # Resolve adapter per-doc via routing (when multiple systems exist).
        # Note: when an external adapter is provided, routing is skipped and
        # sys_config stays None. Multi-system configs with an external adapter
        # won't get custom templates/hierarchy/status_map — this matches the
        # webhook path where _resolve_adapter handles routing centrally.
        doc_adapter = adapter
        project_key = ""
        sys_config = None
        if not doc_adapter and not mapping.is_empty():
            # Route per-doc for now; per-section routing is Phase 3
            target_name = resolve_target(
                doc.sections[0] if doc.sections else None,
                doc,
                mapping.routing,
                mapping.ticket_systems,
            )
            if target_name:
                sys_config = mapping.ticket_systems[target_name]
                doc_adapter = from_config(target_name, sys_config, mapping.auth_profiles or None)
                project_key = sys_config.project or ""

        if not doc_adapter:
            print("  Skipped: no adapter resolved for this spec")
            continue

        # Resolve single-system config before the forward/reverse split so
        # both directions get the sys_config (not just forward).
        if not sys_config:
            single = mapping.single_system()
            if single:
                sys_config = single

        if reverse:
            updated_md, result = asyncio.run(
                reverse_sync(doc, doc_adapter, system_config=sys_config)
            )
        else:
            # Resolve project key from mapping config or legacy config
            if not project_key:
                project_key = (
                    doc.frontmatter.ticket_project
                    or (sys_config.project if sys_config else None)
                    or config.project_key
                    or ""
                )
            if not project_key:
                print("  Skipped: no project key configured")
                continue
            updated_md, result = asyncio.run(
                forward_sync(
                    doc,
                    doc_adapter,
                    project_key,
                    require_review=config.specs.require_review,
                    dry_run=dry_run,
                    system_config=sys_config,
                )
            )

        # Report results
        if result.created:
            for c in result.created:
                print(f"  Created: {c.section_id} → {c.ticket_id} ({c.ticket_url})")
        if result.updated:
            for u in result.updated:
                print(f"  Existing: {u.section_id} → {u.ticket_id}")
        if result.status_changed:
            for sc in result.status_changed:
                print(f"  Updated: {sc.section_id} {sc.old_state} → {sc.new_state}")
        if result.skipped:
            print(f"  Skipped: {len(result.skipped)} sections (not todo/in_progress)")
        if result.errors:
            for e in result.errors:
                print(f"  Error: {e.section_id}: {e.error}")
        if not result.created and not result.status_changed and not result.errors:
            print("  No changes.")

        # Write back unless dry run
        if not dry_run and updated_md != doc.raw:
            spec_path = root / doc.file_path
            spec_path.write_text(updated_md)
            print(f"  Written: {doc.file_path}")
        elif dry_run and updated_md != doc.raw:
            print("  (dry run — changes not written)")
