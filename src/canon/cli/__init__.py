"""Canon CLI — repo initialization and management."""

from __future__ import annotations

import argparse
import sys


class CanonCLIError(Exception):
    """Base exception for user-facing CLI errors."""

    def __init__(self, message: str, *, hint: str | None = None, exit_code: int = 1):
        super().__init__(message)
        self.hint = hint
        self.exit_code = exit_code


class AuthRequiredError(CanonCLIError):
    """Raised when a command needs authentication."""

    def __init__(self, message: str = "Not logged in", *, hint: str | None = None):
        super().__init__(message, hint=hint or "Run `canon login` to authenticate", exit_code=1)


class ConfigError(CanonCLIError):
    """Raised for configuration issues."""

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(
            message, hint=hint or "Run `canon setup` to fix configuration", exit_code=1
        )


class SpecNotFoundError(CanonCLIError):
    """Raised when a spec file can't be found."""

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message, hint=hint, exit_code=2)


class NetworkError(CanonCLIError):
    """Raised for network/API failures."""

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message, hint=hint or "Check your network connection", exit_code=1)


# ── Command Registry ───────────────────────────────────────

COMMAND_GROUPS = {
    "Getting Started": ["setup", "login", "logout", "doctor"],
    "Spec Workflow": ["new", "status", "tasks", "plan", "start", "done"],
    "Validation": ["lint", "verify", "audit"],
    "Sync": ["sync", "dedup", "integrations"],
    "Reporting": ["stale", "export", "release-notes"],
    "Tools": [
        "search",
        "dashboard",
        "triage",
        "evidence",
        "extension",
        "auth",
        "db",
        "ide-config",
    ],
}


def _print_grouped_help(parser: argparse.ArgumentParser) -> None:
    """Print help with commands grouped by category."""
    from ._output import get_stdout

    out = get_stdout()

    # Extract help texts from the subparser choice actions
    help_texts: dict[str, str] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for choice_action in action._choices_actions:
                help_texts[choice_action.dest] = choice_action.help or ""

    out.print("\n[heading]Canon[/heading] — Spec-driven development platform\n")

    for group_name, commands in COMMAND_GROUPS.items():
        group_cmds = [(cmd, help_texts.get(cmd, "")) for cmd in commands if cmd in help_texts]
        if not group_cmds:
            continue
        out.print(f"[heading]{group_name}:[/heading]")
        for cmd, help_text in group_cmds:
            out.print(f"  [key]{cmd:<20}[/key]{help_text}")
        out.print()

    out.print("[muted]Global options: --no-color, --quiet, --verbose[/muted]")
    out.print("[muted]Run `canon <command> --help` for command-specific options[/muted]\n")


def _register_all(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Import and register all command modules."""
    from .audit import register as audit_register
    from .auth_cmd import register as auth_register
    from .dashboard import register as dashboard_register
    from .db import register as db_register
    from .dedup import register as dedup_register
    from .doctor_cmd import register as doctor_register
    from .done import register as done_register
    from .evidence import register as evidence_register
    from .export import register as export_register
    from .extension_cmd import register as extension_register
    from .ide_config import register as ide_config_register
    from .integrations_cmd import register as integrations_register
    from .lint import register as lint_register
    from .login import register as login_register
    from .logout import register as logout_register
    from .new_spec import register as new_register
    from .plan import register as plan_register
    from .release_notes import register as release_notes_register
    from .search import register as search_register
    from .setup_cmd import register as setup_register_cmd
    from .stale import register as stale_register
    from .start import register as start_register
    from .status_cmd import register as status_register
    from .sync_cmd import register as sync_register
    from .tasks import register as tasks_register
    from .triage import register as triage_register
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
    lint_register(subparsers)
    verify_register(subparsers)
    audit_register(subparsers)
    plan_register(subparsers)
    new_register(subparsers)
    release_notes_register(subparsers)
    stale_register(subparsers)
    export_register(subparsers)
    ide_config_register(subparsers)
    evidence_register(subparsers)
    extension_register(subparsers)
    integrations_register(subparsers)
    triage_register(subparsers)
    doctor_register(subparsers)
    search_register(subparsers)
    dashboard_register(subparsers)

    # Alias: canon init -> canon setup
    from .setup_cmd import _add_setup_arguments

    init_parser = subparsers.add_parser("init", help="Alias for 'setup'")
    _add_setup_arguments(init_parser)


def _dispatch(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate command handler."""
    cmd = args.command

    if cmd == "db":
        from .db import run_db

        run_db(args)
    elif cmd in ("setup", "init"):
        if getattr(args, "agent", None):
            from .agent_setup import SUPPORTED_PLATFORMS, run_agent_setup

            platforms = list(SUPPORTED_PLATFORMS) if args.agent == "all" else [args.agent]
            run_agent_setup(platforms=platforms, force=args.force)
        else:
            from .wizard import run_wizard

            run_wizard(
                team=getattr(args, "team", None),
                ticket_system=getattr(args, "ticket_system", None),
                non_interactive=getattr(args, "non_interactive", False),
            )
    elif cmd == "login":
        from .login import run_login

        run_login(
            api_key=args.api_key,
            token=args.token,
            api_url=args.api_url,
            server=args.server,
            org=args.org,
        )
    elif cmd == "logout":
        from .logout import run_logout

        run_logout()
    elif cmd == "auth":
        if getattr(args, "auth_command", None) == "status":
            from .auth_cmd import run_auth_status

            run_auth_status()
        else:
            raise CanonCLIError("No auth subcommand specified", hint="Try `canon auth status`")
    elif cmd == "tasks":
        from .tasks import run_tasks

        run_tasks(status=args.status, spec=args.spec, show_all=args.show_all)
    elif cmd == "status":
        from .status_cmd import run_status

        exit_code = run_status(spec=args.spec, json_output=getattr(args, "json", False))
        if exit_code:
            sys.exit(exit_code)
    elif cmd == "start":
        from .start import run_start

        run_start(section_id=args.section_id, issue=args.issue)
    elif cmd == "done":
        from .done import run_done

        run_done(section_id=args.section_id, issue=args.issue)
    elif cmd == "sync":
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
    elif cmd == "dedup":
        from .dedup import run_dedup

        run_dedup(dry_run=args.dry_run, spec=args.spec)
    elif cmd == "lint":
        from .lint import run_lint

        exit_code = run_lint(
            spec=args.spec,
            json_output=getattr(args, "json", False),
            warnings_as_errors=args.warnings_as_errors,
        )
        sys.exit(exit_code)
    elif cmd == "verify":
        from .verify import run_verify

        exit_code = run_verify(
            section=args.section, gate=args.gate, json_output=getattr(args, "json", False)
        )
        if exit_code:
            sys.exit(exit_code)
    elif cmd == "audit":
        from .audit import run_audit

        run_audit(
            dry_run=args.dry_run,
            do_sync=args.sync,
            spec=args.spec,
            no_ac_updates=args.no_ac_updates,
            json_output=getattr(args, "json", False),
        )
    elif cmd == "plan":
        from .plan import run_plan

        run_plan(spec_file=args.spec_file, output=args.output)
    elif cmd == "new":
        from .new_spec import run_new

        exit_code = run_new(
            title=args.title,
            doc_type=args.doc_type,
            owner=args.owner,
            team=args.team,
            output=args.output,
            force=args.force,
        )
        if exit_code:
            sys.exit(exit_code)
    elif cmd == "release-notes":
        from .release_notes import run_release_notes

        exit_code = run_release_notes(
            from_ref=args.from_ref,
            to_ref=args.to_ref,
            json_output=getattr(args, "json", False),
            output=args.output,
        )
        if exit_code:
            sys.exit(exit_code)
    elif cmd == "stale":
        from .stale import run_stale

        exit_code = run_stale(
            stale_days=args.stale_days,
            code_churn_threshold=args.code_churn_threshold,
            json_output=getattr(args, "json", False),
        )
        if exit_code:
            sys.exit(exit_code)
    elif cmd == "export":
        from .export import run_export

        exit_code = run_export(
            export_format=args.export_format,
            output=args.output,
            spec=args.spec,
        )
        if exit_code:
            sys.exit(exit_code)
    elif cmd == "ide-config":
        from .ide_config import run_ide_config

        run_ide_config()
    elif cmd == "evidence":
        from .evidence import run_evidence

        run_evidence(args)
    elif cmd == "extension":
        from .extension_cmd import run_extension

        run_extension(args)
    elif cmd in ("integrations", "int"):
        from .integrations_cmd import run_integrations

        run_integrations(args)
    elif cmd == "triage":
        from .triage import run_triage

        exit_code = run_triage(
            issue=args.issue,
            repo=args.repo,
            specs=args.specs,
            apply=args.apply,
            create_spec=args.create_spec,
            dry_run=args.dry_run,
            json_output=args.json_output,
            confidence_threshold=args.confidence_threshold,
        )
        if exit_code:
            sys.exit(exit_code)
    elif cmd == "doctor":
        from .doctor_cmd import run_doctor

        exit_code = run_doctor(json_output=args.json_output, fix=args.fix)
        if exit_code:
            sys.exit(exit_code)
    elif cmd == "search":
        from .search import run_search

        exit_code = run_search(
            query=args.query,
            status=args.status,
            spec=args.spec,
            json_output=getattr(args, "json", False),
        )
        if exit_code:
            sys.exit(exit_code)
    elif cmd == "dashboard":
        from .dashboard import run_dashboard

        exit_code = run_dashboard(json_output=getattr(args, "json", False))
        if exit_code:
            sys.exit(exit_code)
    else:
        raise CanonCLIError(
            f"Unknown command: {cmd}", hint="Run `canon --help` to see all commands"
        )


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="canon",
        description="Canon — Spec-driven development platform",
    )

    # Global flags
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable colored output",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress non-essential output",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose/debug output",
    )

    subparsers = parser.add_subparsers(dest="command")
    _register_all(subparsers)

    # Override print_help so both `canon` and `canon --help` show grouped output
    parser.print_help = lambda file=None: _print_grouped_help(parser)  # type: ignore[assignment]

    args = parser.parse_args(argv)

    # Configure output module with global flags
    from ._output import configure

    configure(no_color=args.no_color, quiet=args.quiet, verbose=args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        _dispatch(args)
    except CanonCLIError as e:
        from ._output import print_error

        print_error(str(e), hint=e.hint)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        from ._output import print_error

        print_error(
            f"Unexpected error: {e}",
            hint="This may be a bug. Please report at https://github.com/canonhq/canon/issues",
        )
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)
