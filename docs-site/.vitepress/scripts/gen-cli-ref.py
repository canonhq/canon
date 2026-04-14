#!/usr/bin/env python3
"""Generate CLI reference markdown from `canon --help` output.

Runs each subcommand with --help, parses the output, and writes
docs-site/reference/cli.md with structured documentation.
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

DOCS_SITE = Path(__file__).resolve().parent.parent.parent
OUTPUT = DOCS_SITE / "reference" / "cli.md"

SUBCOMMANDS = [
    "setup",
    "login",
    "logout",
    "auth",
    "tasks",
    "status",
    "start",
    "done",
    "sync",
    "lint",
    "verify",
    "audit",
    "plan",
]

# Hand-written descriptions to supplement --help output
DESCRIPTIONS: dict[str, str] = {
    "setup": "Initialize a repository for Canon. Creates `CANON.yaml`, the spec directory, and a starter template.",
    "login": "Authenticate with the Canon platform using device authorization flow or API key.",
    "logout": "Log out and revoke the current session.",
    "auth": "Authentication utilities. Use `auth status` to check current authentication state.",
    "tasks": "List actionable work items from specs. Shows sections with `todo` or `in_progress` status and their acceptance criteria.",
    "status": "Show spec coverage dashboard. Displays per-spec and aggregate coverage metrics. Supports `--json` for machine-readable output consumed by the coverage-report GitHub Action.",
    "start": "Mark a spec section as `in_progress`. Optionally creates or updates a linked GitHub Issue.",
    "done": "Mark a spec section as `done`. Optionally closes the linked GitHub Issue.",
    "sync": "Sync spec sections with the configured ticket system (GitHub Issues, Jira, or Linear). Supports forward sync (spec → tickets) and reverse sync (tickets → spec).",
    "lint": "Static structural validation of spec files — frontmatter schema, section numbering, AC format, status comment syntax, and `depends_on` resolvability. Pure parser, no Claude spend, no network. The cheapest layer of the lint → verify → audit ladder; safe to run on every PR.",
    "verify": "Static verification of acceptance criteria against the codebase. Greps source paths for keywords from each unchecked AC and classifies it as likely realized, not started, or unknown. No Claude spend. Supports `--json` for the verify GitHub Action.",
    "audit": "Audit spec statuses against the codebase using Claude. Checks off realized ACs, inserts evidence comments, and optionally runs ticket sync.",
    "plan": "Generate a task plan from a spec. Outputs a structured implementation plan based on unchecked acceptance criteria.",
}


def run_help(args: list[str]) -> str:
    """Run a canon command with --help and return stdout."""
    result = subprocess.run(
        ["uv", "run", "canon", *args, "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip()


def parse_help(text: str) -> dict:
    """Parse argparse --help output into structured sections."""
    lines = text.split("\n")
    sections: dict[str, list[str]] = {}
    current = "usage"
    sections[current] = []

    for line in lines:
        stripped = line.rstrip()
        if stripped.endswith(":") and not stripped.startswith(" "):
            current = stripped[:-1].lower()
            sections[current] = []
        else:
            sections.setdefault(current, []).append(stripped)

    return sections


def format_options(lines: list[str]) -> str:
    """Format argparse options as a markdown table."""
    rows: list[tuple[str, str]] = []
    current_opt = ""
    current_desc = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("-"):
            if current_opt:
                rows.append((current_opt, current_desc))
            parts = stripped.split("  ", 1)
            current_opt = parts[0].strip()
            current_desc = parts[1].strip() if len(parts) > 1 else ""
        elif current_opt and stripped:
            current_desc = (current_desc + " " + stripped).strip()

    if current_opt:
        rows.append((current_opt, current_desc))

    if not rows:
        return ""

    out = "| Option | Description |\n|--------|-------------|\n"
    for opt, desc in rows:
        out += f"| `{opt}` | {desc} |\n"
    return out


def format_positional(lines: list[str]) -> str:
    """Format positional arguments as a markdown table."""
    rows: list[tuple[str, str]] = []
    current_arg = ""
    current_desc = ""

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("{"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2 and not parts[0].startswith("-"):
            if current_arg:
                rows.append((current_arg, current_desc))
            current_arg = parts[0]
            current_desc = parts[1].strip()
        elif current_arg and stripped:
            current_desc = (current_desc + " " + stripped).strip()

    if current_arg:
        rows.append((current_arg, current_desc))

    if not rows:
        return ""

    out = "| Argument | Description |\n|----------|-------------|\n"
    for arg, desc in rows:
        out += f"| `{arg}` | {desc} |\n"
    return out


def generate() -> str:
    """Generate the full CLI reference markdown."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    parts = [
        "---",
        "# This file is auto-generated. Do not edit manually.",
        f"# Generated: {now}",
        "---",
        "",
        "# CLI Reference",
        "",
        "::: tip Auto-Generated",
        f"This page was auto-generated from `canon --help` on {now}.",
        "See [source script](https://github.com/canonhq/canon/blob/main/docs-site/.vitepress/scripts/gen-cli-ref.py).",
        ":::",
        "",
        "The Canon CLI provides local spec management commands.",
        "",
        "## Installation",
        "",
        "```bash",
        "# With uv (recommended)",
        "uv tool install canonhq",
        "",
        "# With pip",
        "pip install canonhq",
        "",
        "# Run without installing",
        "uvx --from canonhq canon --help",
        "```",
        "",
        "## Commands",
        "",
    ]

    # Get top-level help for the usage line
    top_help = run_help([])
    parts.append("```")
    parts.append(top_help.split("\n")[0] if top_help else "canon [-h] COMMAND ...")
    parts.append("```")
    parts.append("")

    for cmd in SUBCOMMANDS:
        help_text = run_help([cmd])
        parsed = parse_help(help_text)

        parts.append(f"### `canon {cmd}`")
        parts.append("")
        parts.append(DESCRIPTIONS.get(cmd, ""))
        parts.append("")

        # Usage
        usage_lines = parsed.get("usage", [])
        usage = " ".join(line.strip() for line in usage_lines if line.strip())
        if usage:
            parts.append("```bash")
            parts.append(usage)
            parts.append("```")
            parts.append("")

        # Positional arguments
        pos_lines = parsed.get("positional arguments", [])
        pos_table = format_positional(pos_lines)
        if pos_table:
            parts.append("**Arguments:**")
            parts.append("")
            parts.append(pos_table)
            parts.append("")

        # Options
        opt_lines = parsed.get("options", [])
        opt_table = format_options(opt_lines)
        if opt_table:
            parts.append("**Options:**")
            parts.append("")
            parts.append(opt_table)
            parts.append("")

        # Subcommands (e.g., auth status)
        sub_lines = parsed.get("positional arguments", [])
        for line in sub_lines:
            stripped = line.strip()
            if stripped.startswith("{") and "}" in stripped:
                subcmds = stripped.strip("{}").split(",")
                for subcmd in subcmds:
                    subcmd = subcmd.strip()
                    if subcmd:
                        sub_help = run_help([cmd, subcmd])
                        if sub_help:
                            sub_parsed = parse_help(sub_help)
                            sub_usage = " ".join(
                                line.strip() for line in sub_parsed.get("usage", []) if line.strip()
                            )
                            parts.append(f"#### `canon {cmd} {subcmd}`")
                            parts.append("")
                            if sub_usage:
                                parts.append("```bash")
                                parts.append(sub_usage)
                                parts.append("```")
                                parts.append("")
                            sub_opts = format_options(sub_parsed.get("options", []))
                            if sub_opts:
                                parts.append("**Options:**")
                                parts.append("")
                                parts.append(sub_opts)
                                parts.append("")

        parts.append("---")
        parts.append("")

    return "\n".join(parts)


def main():
    content = generate()
    OUTPUT.write_text(content)
    print(f"Generated {OUTPUT} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
