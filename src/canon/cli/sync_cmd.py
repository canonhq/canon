"""canon sync — forward/reverse ticket sync."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
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
    parser.add_argument(
        "--backfill-fingerprints",
        action="store_true",
        help="Add section fingerprints to existing issue bodies (one-time migration)",
    )
    parser.add_argument(
        "--close-stale",
        action="store_true",
        help="Close tickets for all done/deprecated sections (one-shot cleanup)",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Force server proxy mode (overrides auto-detection)",
    )


def _try_remote_adapter(
    config: CanonConfig, root: Path
) -> tuple[object, TicketMappingConfig] | None:
    """Try to create a server-proxied adapter for logged-in users.

    Returns (adapter, mapping) if credentials exist and the Canon server
    can handle the configured ticket system, otherwise None.

    Supported systems: github (default), jira, linear.
    """
    from canon.sync.adapters.api_proxy import CanonApiAdapter

    from ._credentials import load_credentials
    from ._local import resolve_github_remote
    from ._platform import PlatformClient

    log = logging.getLogger(__name__)

    cred = load_credentials()
    if cred is None:
        log.debug("No Canon credentials found; run 'canon login' to enable server proxy")
        return None

    system = config.ticket_system or "github"

    if system == "github":
        remote = resolve_github_remote(config, root)
        if not remote:
            log.debug("Could not resolve GitHub remote for server proxy")
            return None
        owner, repo = remote
        org = cred.get("org_login", "") or cred.get("org", "") or owner
        if not org:
            log.debug("No org resolved from credentials or GitHub remote")
            return None
        client = PlatformClient()
        adapter = CanonApiAdapter(client, org, owner, repo, ticket_system="github")
        mapping = TicketMappingConfig(
            ticket_systems={"primary": TSC(system="github", project=f"{owner}/{repo}")}
        )
        return adapter, mapping

    if system in ("jira", "linear"):
        org = cred.get("org_login", "") or cred.get("org", "")
        if not org:
            log.debug("No org in Canon credentials; cannot use server proxy for %s", system)
            return None
        project_key = config.project_key or ""
        client = PlatformClient()
        adapter = CanonApiAdapter(
            client, org, "", "", ticket_system=system, project_key=project_key
        )
        mapping = TicketMappingConfig(
            ticket_systems={"primary": TSC(system=system, project=project_key)}
        )
        return adapter, mapping

    log.warning(
        "Unsupported ticket system '%s' for server proxy; supported: github, jira, linear",
        system,
    )
    return None


def _has_local_credentials() -> bool:
    """Check if local GitHub credentials are available via GITHUB_TOKEN or gh CLI."""
    if os.environ.get("GITHUB_TOKEN"):
        return True
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _try_local_or_remote(config: CanonConfig, root: Path) -> tuple[object, TicketMappingConfig]:
    """Auto-detect: prefer local credentials for GitHub, server proxy for Jira/Linear."""
    log = logging.getLogger(__name__)

    system = config.ticket_system or "github"

    # For Jira/Linear, always prefer server proxy — local credentials
    # require managing API tokens, which is what we're trying to avoid.
    if system in ("jira", "linear"):
        result = _try_remote_adapter(config, root)
        if result is not None:
            log.debug("Using Canon server proxy for %s", system)
            print(f"Using Canon server proxy for {system}")
            return result
        log.warning("Server proxy unavailable for %s; falling back to local adapter", system)
        print(
            f"Warning: Canon server proxy unavailable for {system}. "
            "Run 'canon login' or set local credentials.",
            file=sys.stderr,
        )
        return create_adapter_local(config, root)

    # For GitHub, prefer local credentials (faster, no server round-trip).
    if _has_local_credentials():
        log.debug("Local GitHub credentials detected, using local adapter")
        return create_adapter_local(config, root)

    result = _try_remote_adapter(config, root)
    if result is not None:
        log.debug("No local credentials, using Canon server proxy")
        print("Using Canon server proxy (no local GITHUB_TOKEN detected)")
        return result

    log.warning("No credentials found, falling back to local adapter (will likely fail)")
    print(
        "Warning: No GitHub credentials detected. "
        "Set GITHUB_TOKEN, install gh CLI, or run 'canon login'.",
        file=sys.stderr,
    )
    return create_adapter_local(config, root)


def run_sync(
    *,
    reverse: bool = False,
    spec: str | None = None,
    dry_run: bool = False,
    local: bool = False,
    remote: bool = False,
    backfill_fingerprints: bool = False,
    close_stale: bool = False,
    root: Path | None = None,
) -> None:
    root = root or Path.cwd()
    config = load_local_config(root)

    if remote:
        result = _try_remote_adapter(config, root)
        if result is not None:
            adapter, mapping = result
            print("Using Canon server proxy (--remote)")
        else:
            print("Error: --remote specified but server proxy is not available.")
            sys.exit(1)
    elif local:
        adapter, mapping = create_adapter_local(config, root)
    else:
        # Auto-detect: prefer local credentials, fall back to server proxy
        adapter, mapping = _try_local_or_remote(config, root)

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
    from canon.sync.engine import (
        backfill_fingerprints as engine_backfill,
    )
    from canon.sync.engine import (
        forward_sync,
        reverse_sync,
    )

    async def _sync_all() -> None:
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
                    doc_adapter = from_config(
                        target_name, sys_config, mapping.auth_profiles or None
                    )
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

            if backfill_fingerprints:
                result = await engine_backfill(doc, doc_adapter, dry_run=dry_run)
                updated_md = doc.raw  # backfill doesn't modify spec markdown
            elif reverse:
                updated_md, result = await reverse_sync(doc, doc_adapter, system_config=sys_config)
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

                # Resolve lifecycle_sync config
                lifecycle_sync_cfg = config.specs.lifecycle_sync
                # --close-stale forces close_only (never reopens)
                effective_lifecycle = "close_only" if close_stale else lifecycle_sync_cfg

                updated_md, result = await forward_sync(
                    doc,
                    doc_adapter,
                    project_key,
                    require_review=config.specs.require_review,
                    dry_run=dry_run,
                    system_config=sys_config,
                    lifecycle_sync=effective_lifecycle,
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
            if result.closed:
                for cl in result.closed:
                    print(f"  Closed: {cl.section_id} → {cl.ticket_id}")
            if result.reopened:
                for ro in result.reopened:
                    print(f"  Reopened: {ro.section_id} → {ro.ticket_id}")
            if result.skipped:
                for sk in result.skipped:
                    print(f"  Skipped: {sk.section_id} — {sk.reason}")
            if result.errors:
                for e in result.errors:
                    print(f"  Error: {e.section_id}: {e.error}")
            has_changes = (
                result.created
                or result.status_changed
                or result.closed
                or result.reopened
                or result.errors
            )
            if not has_changes:
                print("  No changes.")

            # Write back unless dry run
            if not dry_run and updated_md != doc.raw:
                spec_path = root / doc.file_path
                spec_path.write_text(updated_md)
                print(f"  Written: {doc.file_path}")
            elif dry_run and updated_md != doc.raw:
                print("  (dry run — changes not written)")

    asyncio.run(_sync_all())
