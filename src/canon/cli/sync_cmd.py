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
from ._output import get_stdout, print_error, print_warning, progress_bar


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
            get_stdout().print(f"[muted]Using Canon server proxy for {system}[/muted]")
            return result
        log.warning("Server proxy unavailable for %s; falling back to local adapter", system)
        print_warning(
            f"Canon server proxy unavailable for {system}.",
            hint="Run 'canon login' or set local credentials.",
        )
        return create_adapter_local(config, root)

    # For GitHub, prefer local credentials (faster, no server round-trip).
    if _has_local_credentials():
        log.debug("Local GitHub credentials detected, using local adapter")
        return create_adapter_local(config, root)

    result = _try_remote_adapter(config, root)
    if result is not None:
        log.debug("No local credentials, using Canon server proxy")
        get_stdout().print(
            "[muted]Using Canon server proxy (no local GITHUB_TOKEN detected)[/muted]"
        )
        return result

    log.warning("No credentials found, falling back to local adapter (will likely fail)")
    print_warning(
        "No GitHub credentials detected.",
        hint="Set GITHUB_TOKEN, install gh CLI, or run 'canon login'.",
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
            get_stdout().print("[muted]Using Canon server proxy (--remote)[/muted]")
        else:
            print_error("--remote specified but server proxy is not available.")
            sys.exit(1)
    elif local:
        adapter, mapping = create_adapter_local(config, root)
    else:
        # Auto-detect: prefer local credentials, fall back to server proxy
        adapter, mapping = _try_local_or_remote(config, root)

    if not adapter and mapping.is_empty():
        print_error(
            "No ticket system configured and no GitHub token available.",
            hint="Set GITHUB_TOKEN, install gh CLI, or configure ticket_systems in CANON.yaml.",
        )
        sys.exit(1)

    docs = parse_all_local_specs(root, config)
    if spec:
        docs = [d for d in docs if spec in d.file_path]

    if not docs:
        get_stdout().print("[muted]No spec files found.[/muted]")
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
        total_created = 0
        total_updated = 0
        total_skipped = 0
        total_errors = 0

        if dry_run:
            get_stdout().print("[bold]DRY RUN[/bold] — no changes will be written\n")

        use_progress = not dry_run and len(docs) > 1
        ctx = progress_bar(len(docs), "Syncing specs") if use_progress else None

        async def _process_doc(doc, bar):
            nonlocal total_created, total_updated, total_skipped, total_errors

            get_stdout().print(
                f"\n[bold]{doc.frontmatter.title}[/bold] [muted]({doc.file_path})[/muted]"
            )

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
                get_stdout().print("  [muted]Skipped: no adapter resolved for this spec[/muted]")
                total_skipped += 1
                if bar:
                    bar.advance()
                return

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
                    get_stdout().print("  [muted]Skipped: no project key configured[/muted]")
                    total_skipped += 1
                    if bar:
                        bar.advance()
                    return

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
            n_created = len(result.created) if result.created else 0
            n_updated_items = len(result.updated) if result.updated else 0
            n_skipped_items = len(result.skipped) if result.skipped else 0
            n_errors = len(result.errors) if result.errors else 0

            if result.created:
                for c in result.created:
                    get_stdout().print(
                        f"  [green]Created:[/green] {c.section_id} -> {c.ticket_id} ({c.ticket_url})"
                    )
            if result.updated:
                for u in result.updated:
                    get_stdout().print(
                        f"  [muted]Existing:[/muted] {u.section_id} -> {u.ticket_id}"
                    )
            if result.status_changed:
                for sc in result.status_changed:
                    get_stdout().print(
                        f"  [yellow]Updated:[/yellow] {sc.section_id} "
                        f"[dim]{sc.old_state}[/dim] [yellow]->[/yellow] [green]{sc.new_state}[/green]"
                    )
            if result.closed:
                for cl in result.closed:
                    get_stdout().print(
                        f"  [muted]Closed:[/muted] {cl.section_id} -> {cl.ticket_id}"
                    )
            if result.reopened:
                for ro in result.reopened:
                    get_stdout().print(
                        f"  [yellow]Reopened:[/yellow] {ro.section_id} -> {ro.ticket_id}"
                    )
            if result.skipped:
                for sk in result.skipped:
                    get_stdout().print(f"  [muted]Skipped:[/muted] {sk.section_id} — {sk.reason}")
            if result.errors:
                for e in result.errors:
                    get_stdout().print(
                        f"  [error]Error:[/error] [bold]{e.section_id}[/bold]: {e.error}"
                    )
            has_changes = (
                result.created
                or result.status_changed
                or result.closed
                or result.reopened
                or result.errors
            )
            if not has_changes:
                get_stdout().print("  [muted]No changes.[/muted]")

            # Write back unless dry run
            if not dry_run and updated_md != doc.raw:
                spec_path = root / doc.file_path
                spec_path.write_text(updated_md)
                get_stdout().print(f"  [success]Written:[/success] {doc.file_path}")
            elif dry_run and updated_md != doc.raw:
                get_stdout().print("  [muted](dry run — changes not written)[/muted]")

            total_created += n_created
            total_updated += n_updated_items
            total_skipped += n_skipped_items
            total_errors += n_errors

            if bar:
                bar.advance()

        if use_progress:
            with ctx as bar:
                for doc in docs:
                    await _process_doc(doc, bar)
        else:
            for doc in docs:
                await _process_doc(doc, None)

        # Summary line
        get_stdout().print()
        parts = []
        if total_created:
            parts.append(f"[green]Created {total_created}[/green]")
        else:
            parts.append(f"Created {total_created}")
        if total_updated:
            parts.append(f"updated {total_updated}")
        else:
            parts.append(f"updated {total_updated}")
        if total_skipped:
            parts.append(f"[muted]skipped {total_skipped}[/muted]")
        else:
            parts.append(f"skipped {total_skipped}")
        if total_errors:
            parts.append(f"[error]errors {total_errors}[/error]")
        else:
            parts.append(f"errors {total_errors}")
        get_stdout().print(f"Sync complete: {', '.join(parts)}")

    asyncio.run(_sync_all())
