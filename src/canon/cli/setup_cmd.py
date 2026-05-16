"""canon setup — interactive configuration for Canon."""

from __future__ import annotations

import argparse
import glob as globmod
import subprocess
from pathlib import Path

from ..setup import cleanup_stale_skills, create_canon_yaml, create_mcp_json, list_setup_files
from ._output import prompt as _prompt
from ._output import prompt_choice as _prompt_choice
from ._output import prompt_confirm as _prompt_confirm


def _add_setup_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared arguments for setup/init commands."""
    parser.add_argument("--team", default=None, help="Team name for CANON.yaml")
    parser.add_argument(
        "--ticket-system",
        default=None,
        choices=["github", "jira", "linear"],
        help="Ticket system (default: github)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip prompts (for CI/Actions)",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="Generate agent config file (claude, cursor, copilot, codex, gemini, or all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing non-Canon agent config files",
    )


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "setup", help="Set up or reconfigure Canon in the current directory"
    )
    _add_setup_arguments(parser)


# ─── Helpers ──────────────────────────────────────────────


def _detect_existing_specs(root: Path) -> list[str]:
    """Look for existing markdown files in common spec locations.

    Returns a list of suggested doc_paths glob patterns.
    """
    candidates = [
        ("docs/specs/*.md", "docs/specs"),
        ("docs/*.md", "docs"),
        ("specs/*.md", "specs"),
    ]

    found: list[str] = []
    for pattern, _directory in candidates:
        matches = [p for p in globmod.glob(str(root / pattern)) if not Path(p).name.startswith("_")]
        if matches:
            found.append(pattern)

    return found


def _check_github_connection() -> tuple[str, str]:
    """Verify GitHub CLI authentication.

    Returns (status, message) where status is "ok", "warning", or "none".
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            output = result.stdout + result.stderr
            for line in output.splitlines():
                if "Logged in to" in line or "account" in line.lower():
                    return "ok", line.strip()
            return "ok", "Authenticated with GitHub CLI"
        return "warning", "GitHub CLI not authenticated — run `gh auth login`"
    except FileNotFoundError:
        return "none", "GitHub CLI (gh) not installed — install from https://cli.github.com"
    except (subprocess.SubprocessError, OSError):
        return "warning", "Could not verify GitHub CLI status"


def _detect_project_key(root: Path) -> str:
    """Extract owner/repo from git remote origin URL."""
    from ._local import resolve_github_remote

    result = resolve_github_remote(root=root)
    if result:
        return f"{result[0]}/{result[1]}"
    return ""


def _hint_claude_plugin(root: Path) -> None:
    """Print a hint about installing the Claude Code plugin if not detected."""
    installed_plugins = root / ".claude" / "plugins" / "installed_plugins.json"
    if installed_plugins.exists():
        try:
            import json

            data = json.loads(installed_plugins.read_text())
            plugins = data.get("plugins", {})
            for key in plugins:
                if key.startswith("canon@"):
                    return  # Plugin already installed
        except (ValueError, KeyError):
            pass

    # Also check user-level plugins
    user_plugins = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    if user_plugins.exists():
        try:
            import json

            data = json.loads(user_plugins.read_text())
            plugins = data.get("plugins", {})
            for key in plugins:
                if key.startswith("canon@"):
                    # Check if it's installed for this project
                    for entry in plugins[key]:
                        if entry.get("scope") == "user" or entry.get("projectPath") == str(root):
                            return
        except (ValueError, KeyError):
            pass

    print()
    print("  Tip: Install the Canon plugin for Claude Code skills (/canon:verify, etc.):")
    print("    claude plugin marketplace add canonhq/canon")
    print("    claude plugin install canon")


# ─── Main command ─────────────────────────────────────────


def run_setup(
    *,
    team: str | None = None,
    ticket_system: str | None = None,
    non_interactive: bool = False,
    target_dir: Path | None = None,
) -> None:
    """Set up or reconfigure Canon in the target directory.

    In interactive mode, prompts the user through configuration choices.
    In non-interactive mode (``--non-interactive``), uses defaults or
    provided flag values.
    """
    root = target_dir or Path.cwd()
    config_path = root / "CANON.yaml"
    config_exists = config_path.exists()

    # ── Reconfigure check ────────────────────────────────
    if config_exists and not non_interactive:
        print("Existing CANON.yaml found.")
        print()
        existing = config_path.read_text()
        # Show a compact summary (first 10 non-blank lines)
        lines = [ln for ln in existing.splitlines() if ln.strip() and not ln.startswith("#")]
        for ln in lines[:10]:
            print(f"  {ln}")
        print()
        if not _prompt_confirm("Reconfigure?"):
            print("Setup cancelled.")
            return

    # ── Auto-detect values ───────────────────────────────
    detected_project = _detect_project_key(root)
    detected_specs = _detect_existing_specs(root)

    # ── Gather config values ─────────────────────────────
    if non_interactive:
        final_team = team or ""
        final_system = ticket_system or "github"
        final_project = detected_project
        host_override: str | None = None
    else:
        # Team
        default_team = team or ""
        final_team = _prompt("Team name", default=default_team)

        # Ticket system
        systems = ["github", "jira", "linear"]
        default_system = ticket_system or "github"
        final_system = _prompt_choice("Ticket system:", systems, default=default_system)

        # Project key
        default_project = detected_project
        final_project = _prompt("Project key (owner/repo)", default=default_project)

        # Jira host
        host_override = None
        if final_system == "jira":
            host_override = _prompt("Jira host (e.g. acme.atlassian.net)")
            if not host_override:
                host_override = None

        # GitHub connection check
        if final_system == "github":
            gh_status, gh_message = _check_github_connection()
            if gh_status == "ok":
                print(f"  GitHub: {gh_message}")
            elif gh_status == "warning":
                print(f"  Warning: {gh_message}")
            else:
                print(f"  Note: {gh_message}")

    doc_paths = detected_specs if detected_specs else None

    # ── Show summary & confirm ───────────────────────────
    if not non_interactive:
        print()
        print("Configuration summary:")
        print(f"  Team:          {final_team or '(none)'}")
        print(f"  Ticket system: {final_system}")
        print(f"  Project:       {final_project or '(none)'}")
        if host_override:
            print(f"  Jira host:     {host_override}")
        if doc_paths:
            print(f"  Doc paths:     {', '.join(doc_paths)}")
        print()
        if not _prompt_confirm("Write configuration?"):
            print("Setup cancelled.")
            return

    # ── Write files ──────────────────────────────────────
    # Always regenerate CANON.yaml on setup
    yaml_content = create_canon_yaml(
        team=final_team,
        ticket_system=final_system,
        project_key=final_project,
        doc_paths=doc_paths,
        host_override=host_override,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml_content)

    if config_exists:
        print("  Updated: CANON.yaml")
    else:
        print("  Created: CANON.yaml")

    # Create template if missing
    template_path = root / "docs" / "specs" / "_template.md"
    if not template_path.exists():
        files = list_setup_files(has_config=True)
        for f in files:
            path = root / f.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f.content)
            print(f"  Created: {f.path}")

    # ── Claude Code integration ──────────────────────────
    mcp_result = create_mcp_json(root)
    if mcp_result == "created":
        print("  Created: .mcp.json")
    elif mcp_result == "updated":
        print("  Updated: .mcp.json")

    if cleanup_stale_skills(root):
        print("  Cleaned up stale .claude/skills/ (skills now come from the canon plugin)")

    # ── Plugin hint ────────────────────────────────────
    _hint_claude_plugin(root)

    # ── Post-setup hints ─────────────────────────────────
    if detected_project:
        print(f"\n  Detected project: {detected_project}")

    if detected_specs:
        count = 0
        for pattern in detected_specs:
            matches = [
                p for p in globmod.glob(str(root / pattern)) if not Path(p).name.startswith("_")
            ]
            count += len(matches)
        print(
            f"  Found {count} existing spec file{'s' if count != 1 else ''}: "
            f"{', '.join(detected_specs)}"
        )

    if not config_exists and not template_path.exists():
        print()
        print("Next steps:")
        print("  1. Copy docs/specs/_template.md to create your first spec")
        print("  2. Push and Canon will start tracking it")
