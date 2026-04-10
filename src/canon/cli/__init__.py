"""Canon CLI — repo initialization and management."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="canon",
        description="Canon — Spec-driven development platform",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Register subcommands
    from .audit import register as audit_register
    from .auth_cmd import register as auth_register
    from .db import register as db_register
    from .dedup import register as dedup_register
    from .done import register as done_register
    from .login import register as login_register
    from .logout import register as logout_register
    from .plan import register as plan_register
    from .setup_cmd import register as setup_register_cmd
    from .start import register as start_register
    from .status_cmd import register as status_register
    from .sync_cmd import register as sync_register
    from .tasks import register as tasks_register
    from .verify import register as verify_register

    db_register(subparsers)
    setup_register_cmd(subparsers)
    login_register(subparsers)
    logout_register(subparsers)
    auth_register(subparsers)
    tasks_register(subparsers)
    status_register(subparsers)
    start_register(subparsers)
    done_register(subparsers)
    sync_register(subparsers)
    dedup_register(subparsers)
    verify_register(subparsers)
    audit_register(subparsers)
    plan_register(subparsers)

    args = parser.parse_args(argv)

    if args.command == "db":
        from .db import run_db

        run_db(args)
    elif args.command == "setup":
        if args.agent:
            from .agent_setup import SUPPORTED_PLATFORMS, run_agent_setup

            platforms = list(SUPPORTED_PLATFORMS) if args.agent == "all" else [args.agent]
            run_agent_setup(platforms=platforms, force=args.force)
        else:
            from .setup_cmd import run_setup

            run_setup(
                team=args.team,
                ticket_system=args.ticket_system,
                non_interactive=args.non_interactive,
            )
    elif args.command == "login":
        from .login import run_login

        run_login(api_key=args.api_key, server=args.server, org=args.org)
    elif args.command == "logout":
        from .logout import run_logout

        run_logout()
    elif args.command == "auth":
        if getattr(args, "auth_command", None) == "status":
            from .auth_cmd import run_auth_status

            run_auth_status()
        else:
            # Print auth subcommand help
            parser.parse_args(["auth", "--help"])
    elif args.command == "tasks":
        from .tasks import run_tasks

        run_tasks(status=args.status, spec=args.spec, show_all=args.show_all)
    elif args.command == "status":
        from .status_cmd import run_status

        run_status(spec=args.spec)
    elif args.command == "start":
        from .start import run_start

        run_start(section_id=args.section_id, issue=args.issue)
    elif args.command == "done":
        from .done import run_done

        run_done(section_id=args.section_id, issue=args.issue)
    elif args.command == "sync":
        from .sync_cmd import run_sync

        run_sync(
            reverse=args.reverse,
            spec=args.spec,
            dry_run=args.dry_run,
            local=args.local,
            remote=args.remote,
            backfill_fingerprints=args.backfill_fingerprints,
            close_stale=args.close_stale,
        )
    elif args.command == "dedup":
        from .dedup import run_dedup

        run_dedup(dry_run=args.dry_run, spec=args.spec)
    elif args.command == "verify":
        from .verify import run_verify

        run_verify(section=args.section)
    elif args.command == "audit":
        from .audit import run_audit

        run_audit(
            dry_run=args.dry_run,
            do_sync=args.sync,
            spec=args.spec,
            no_ac_updates=args.no_ac_updates,
        )
    elif args.command == "plan":
        from .plan import run_plan

        run_plan(spec_file=args.spec_file, output=args.output)
    else:
        parser.print_help()
        sys.exit(1)
