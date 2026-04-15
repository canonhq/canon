"""canon extension — manage Canon extensions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the ``extension`` subcommand and its sub-subcommands."""
    parser = subparsers.add_parser(
        "extension",
        help="Manage Canon extensions",
        description="Install, remove, list, create, and validate Canon extensions.",
    )
    ext_sub = parser.add_subparsers(dest="ext_command")

    # canon extension add <source> [--dev]
    add_p = ext_sub.add_parser("add", help="Install an extension from a local directory")
    add_p.add_argument("source", help="Path to extension directory")
    add_p.add_argument(
        "--dev",
        action="store_true",
        help="Symlink instead of copy (dev mode — edits propagate instantly)",
    )

    # canon extension remove <ext_id>
    rm_p = ext_sub.add_parser("remove", help="Remove an installed extension")
    rm_p.add_argument("ext_id", help="Extension ID to remove")

    # canon extension list
    ext_sub.add_parser("list", help="List installed extensions")

    # canon extension create <ext_id> [--skill] [--command] [--hook] [--adapter] [--author] [-o]
    create_p = ext_sub.add_parser("create", help="Scaffold a new extension")
    create_p.add_argument("ext_id", help="Extension ID (lowercase, hyphens)")
    create_p.add_argument("--skill", action="store_true", help="Include skill template")
    create_p.add_argument("--command", action="store_true", help="Include command template")
    create_p.add_argument("--hook", action="store_true", help="Include hook template")
    create_p.add_argument("--adapter", action="store_true", help="Include adapter skeleton")
    create_p.add_argument("--author", default="", help="Author name")
    create_p.add_argument(
        "--output", "-o", default=None, help="Output directory (default: ./<ext_id>)"
    )

    # canon extension validate <source>
    val_p = ext_sub.add_parser("validate", help="Validate an extension manifest")
    val_p.add_argument("source", help="Path to extension directory")


def run_extension(args: argparse.Namespace) -> None:
    """Dispatch to the correct extension subcommand."""
    cmd = getattr(args, "ext_command", None)
    if cmd == "add":
        _run_add(args)
    elif cmd == "remove":
        _run_remove(args)
    elif cmd == "list":
        _run_list(args)
    elif cmd == "create":
        _run_create(args)
    elif cmd == "validate":
        _run_validate(args)
    else:
        # No subcommand — print help
        print("Usage: canon extension {add,remove,list,create,validate} ...")
        print("Run 'canon extension --help' for details.")
        sys.exit(1)


def _run_add(args: argparse.Namespace) -> None:
    from canon.extensions.installer import install_extension

    source = Path(args.source).resolve()
    project_root = Path.cwd()

    try:
        result = install_extension(project_root, source, dev_mode=args.dev)
    except (FileNotFoundError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    mode = "dev mode (symlinked)" if args.dev else "copied"
    print(f"Installed extension {result.ext_id!r} v{result.version} ({mode})")
    if result.installed_files:
        print(f"  Placed {len(result.installed_files)} file(s):")
        for f in result.installed_files:
            print(f"    {f}")
    for w in result.warnings:
        print(f"  Warning: {w}")


def _run_remove(args: argparse.Namespace) -> None:
    from canon.extensions.installer import uninstall_extension

    project_root = Path.cwd()

    try:
        removed = uninstall_extension(project_root, args.ext_id)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Removed extension {args.ext_id!r}")
    if removed:
        print(f"  Cleaned up {len(removed)} file(s)")


def _run_list(args: argparse.Namespace) -> None:
    from canon.extensions.registry import load_registry

    project_root = Path.cwd()
    registry = load_registry(project_root)

    if not registry.extensions:
        print("No extensions installed.")
        return

    for ext_id, entry in sorted(registry.extensions.items()):
        status = "enabled" if entry.enabled else "disabled"
        mode = " (dev)" if entry.dev_mode else ""
        file_count = len(entry.installed_files)
        print(f"  {ext_id} v{entry.version} [{status}]{mode} — {file_count} file(s)")
        if entry.dev_mode:
            print(f"    Source: {entry.source_path}")


def _run_create(args: argparse.Namespace) -> None:
    from canon.extensions.template import scaffold_extension

    output_dir = Path(args.output) if args.output else Path.cwd() / args.ext_id

    try:
        created = scaffold_extension(
            output_dir,
            args.ext_id,
            with_skill=args.skill,
            with_command=args.command,
            with_hook=args.hook,
            with_adapter=args.adapter,
            author=args.author,
        )
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Created extension {args.ext_id!r} at {output_dir}")
    print(f"  {len(created)} file(s) created:")
    for f in created:
        print(f"    {f}")
    print()
    print("Next steps:")
    print(f"  1. Edit {output_dir / 'canon-extension.yml'}")
    print(f"  2. canon extension validate {output_dir}")
    print(f"  3. canon extension add --dev {output_dir}")


def _run_validate(args: argparse.Namespace) -> None:
    from pydantic import ValidationError

    from canon.extensions.installer import get_canon_version
    from canon.extensions.manifest import (
        check_canon_version_compat,
        load_manifest,
        validate_file_references,
    )

    source = Path(args.source).resolve()
    errors: list[str] = []

    # Load manifest
    try:
        manifest = load_manifest(source)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except (ValidationError, ValueError) as e:
        print(f"Manifest validation failed:\n{e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Extension: {manifest.extension.name} ({manifest.extension.id}) v{manifest.extension.version}"
    )

    # Check file references
    file_errors = validate_file_references(manifest, source)
    errors.extend(file_errors)

    # Check version compatibility
    canon_version = get_canon_version()
    if not check_canon_version_compat(manifest.requires.canon_version, canon_version):
        errors.append(
            f"Requires canon {manifest.requires.canon_version}, current is {canon_version}"
        )

    # Summary
    component_counts = []
    if manifest.provides.skills:
        component_counts.append(f"{len(manifest.provides.skills)} skill(s)")
    if manifest.provides.commands:
        component_counts.append(f"{len(manifest.provides.commands)} command(s)")
    if manifest.provides.adapters:
        component_counts.append(f"{len(manifest.provides.adapters)} adapter(s)")
    if manifest.provides.hooks:
        component_counts.append(f"{len(manifest.provides.hooks)} hook(s)")
    if manifest.provides.mcp_tools:
        component_counts.append(f"{len(manifest.provides.mcp_tools)} MCP tool(s)")
    if manifest.provides.agents:
        component_counts.append(f"{len(manifest.provides.agents)} agent(s)")

    if component_counts:
        print(f"Provides: {', '.join(component_counts)}")

    if errors:
        print(f"\n{len(errors)} error(s) found:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    else:
        print("Validation passed.")
