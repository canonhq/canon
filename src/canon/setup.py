"""Shared repo initialization logic — used by CLI, GitHub Action, and webhook onboarding.

All functions are pure/sync with no async dependencies, so they can be called
from any context (CLI, action runner, or async webhook handler).
"""

from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass
from pathlib import Path

from .parser.templates import get_template


@dataclass
class SetupFile:
    """A file to create during setup."""

    path: str
    content: str


def create_specwright_yaml(
    team: str = "",
    ticket_system: str = "github",
    project_key: str = "",
    doc_paths: list[str] | None = None,
    host_override: str | None = None,
) -> str:
    """Return a sensible default CANON.yaml.

    Uses the new ``ticket_systems:`` config format. Legacy fields
    (ticket_system, project_key) are included as comments for reference.

    Args:
        team: Optional team name to include.
        ticket_system: Ticket system (github, jira, linear).
        project_key: Optional owner/repo (e.g. "Org/repo") to include.
        doc_paths: Optional list of glob patterns for spec files.
        host_override: Optional host for Jira (e.g. "acme.atlassian.net").
    """
    team_line = f"team: {team}" if team else "# team: my-team"

    paths = doc_paths or ["docs/specs/*.md"]
    doc_paths_lines = "\n".join(f'    - "{p}"' for p in paths)

    # Build ticket_systems block
    project_line = f'    project: "{project_key}"' if project_key else '    # project: "Owner/repo"'
    host_line = f'    host: "{host_override}"' if host_override else ""
    system_name = "primary"

    # Assemble ticket system config lines
    ts_lines = f"    system: {ticket_system}\n{project_line}"
    if host_line:
        ts_lines += f"\n{host_line}"

    return f"""\
# Canon configuration — https://canonhq.co/docs/config
{team_line}

ticket_systems:
  {system_name}:
{ts_lines}
    # status_map:
    #   forward:
    #     draft: "Backlog"
    #     todo: "To Do"
    #     in_progress: "In Progress"
    #     done: "Done"
    #     blocked: "Blocked"
    #     deprecated: "Won't Do"

specs:
  auto_tickets: false
  require_review: true
  doc_paths:
{doc_paths_lines}

agents:
  doc_updates: true
  pr_analysis: true
  stale_detection: "30d"
  realization_check: true
"""


def create_spec_template(doc_type: str = "spec") -> str:
    """Load a spec template by document type.

    Raises ValueError if the type is not recognized.
    """
    return get_template(doc_type)


def list_setup_files(
    team: str = "",
    ticket_system: str = "github",
    project_key: str = "",
    doc_paths: list[str] | None = None,
    has_config: bool = False,
) -> list[SetupFile]:
    """Return the list of files to create for a new Canon setup.

    Args:
        team: Optional team name for CANON.yaml.
        ticket_system: Ticket system for CANON.yaml.
        project_key: Optional owner/repo for CANON.yaml.
        doc_paths: Optional glob patterns for spec file locations.
        has_config: If True, skip creating CANON.yaml (already exists).

    Returns:
        List of SetupFile objects with path and content.
    """
    files: list[SetupFile] = [
        SetupFile(path="docs/specs/_template.md", content=create_spec_template("spec")),
    ]

    if not has_config:
        files.append(
            SetupFile(
                path="CANON.yaml",
                content=create_specwright_yaml(
                    team=team,
                    ticket_system=ticket_system,
                    project_key=project_key,
                    doc_paths=doc_paths,
                ),
            )
        )

    return files


_MCP_CONFIG = {
    "mcpServers": {
        "canon": {
            "command": "uvx",
            "args": ["--from", "canonhq", "canon-mcp"],
        }
    }
}


def create_mcp_json(root: Path) -> str | None:
    """Create .mcp.json with the canon MCP server config.

    If the file already exists, merges the canon server entry into it
    without overwriting other servers.

    Returns ``"created"``, ``"updated"``, or ``None`` (already present).
    """
    mcp_path = root / ".mcp.json"

    if mcp_path.exists():
        raw = mcp_path.read_text(encoding="utf-8").strip()
        if raw:
            try:
                existing = json.loads(raw)
            except json.JSONDecodeError:
                print(f"  Warning: {mcp_path} contains invalid JSON — fix it manually and re-run")
                return None
            if not isinstance(existing, dict):
                print(f"  Warning: {mcp_path} is not a JSON object — fix it manually and re-run")
                return None
        else:
            existing = {}
        servers = existing.get("mcpServers", {})
        if "canon" in servers:
            return None
        servers["canon"] = _MCP_CONFIG["mcpServers"]["canon"]
        existing["mcpServers"] = servers
        mcp_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        return "updated"
    else:
        mcp_path.write_text(json.dumps(_MCP_CONFIG, indent=2) + "\n", encoding="utf-8")
        return "created"


def install_skills(root: Path) -> tuple[list[str], int]:
    """Copy bundled SKILL.md files to .claude/skills/ in the target directory.

    Existing skill files are skipped to preserve user customizations.
    Delete a skill directory and re-run ``canon setup`` to reinstall.

    Returns ``(installed, skipped)`` — list of newly installed skill names
    and count of skills that were skipped because they already existed.
    """
    installed: list[str] = []
    skipped = 0
    skills_pkg = importlib.resources.files("canon.plugin_data") / "skills"

    for skill_dir in sorted(skills_pkg.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue

        dest = root / ".claude" / "skills" / skill_dir.name / "SKILL.md"
        if dest.exists():
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(skill_file.read_text(encoding="utf-8"), encoding="utf-8")
        installed.append(skill_dir.name)

    return installed, skipped
