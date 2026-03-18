"""``canon db`` — database management commands."""

from __future__ import annotations

import argparse
import os
import sys


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("db", help="Database management")
    sub = p.add_subparsers(dest="db_command")
    upgrade_p = sub.add_parser("upgrade", help="Run database migrations to latest")
    upgrade_p.add_argument(
        "--revision",
        default="head",
        help="Target revision (default: head)",
    )


def run_db(args: argparse.Namespace) -> None:
    if args.db_command == "upgrade":
        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url:
            print("ERROR: DATABASE_URL environment variable is not set", file=sys.stderr)
            sys.exit(1)

        try:
            from ..db.migrate import run_upgrade
        except ImportError:
            print("ERROR: Database module not available (cloud-only feature)", file=sys.stderr)
            sys.exit(1)

        run_upgrade(database_url, revision=args.revision)
        print("Migrations applied successfully.")
    else:
        print("Usage: canon db upgrade [--revision REV]", file=sys.stderr)
        sys.exit(1)
