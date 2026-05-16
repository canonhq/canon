"""Guided onboarding wizard — replaces canon setup with a progressive multi-step flow.

Steps:
1. Repository detection
2. Authentication
3. Integration connection
4. Configuration
5. Environment setup (MCP, agent configs, skills)
6. Validation (doctor checks)
7. Summary & next steps
"""

from __future__ import annotations

import glob as globmod
from dataclasses import dataclass, field
from pathlib import Path

from ._output import prompt as _prompt
from ._output import prompt_confirm as _prompt_confirm


@dataclass
class WizardState:
    root: Path = field(default_factory=Path.cwd)
    repo_owner: str = ""
    repo_name: str = ""
    project_key: str = ""
    authenticated: bool = False
    org: str = ""
    email: str = ""
    ticket_system: str = ""
    integration_connected: bool = False
    team: str = ""
    config_written: bool = False
    skip_config_write: bool = False
    mcp_written: bool = False
    skills_installed: bool = False
    spec_count: int = 0
    doctor_passed: int = 0
    doctor_warns: int = 0
    doctor_fails: int = 0
    skipped_steps: list[str] = field(default_factory=list)
    non_interactive: bool = False


def run_wizard(
    *,
    team: str | None = None,
    ticket_system: str | None = None,
    non_interactive: bool = False,
    target_dir: Path | None = None,
) -> None:
    """Run the guided onboarding wizard."""
    state = WizardState(
        root=target_dir or Path.cwd(),
        non_interactive=non_interactive,
    )

    # Pre-set values from flags
    if team:
        state.team = team
    if ticket_system:
        state.ticket_system = ticket_system

    print("\n  Canon Setup\n")

    # Step 1: Repo detection
    _step_repo_detection(state)

    # Step 2: Authentication
    _step_authentication(state)

    # Step 3: Integration
    _step_integration(state)

    # Step 4: Configuration
    _step_configuration(state)

    # Step 5: Environment
    _step_environment(state)

    # Step 6: Validation
    _step_validation(state)

    # Step 7: Summary
    _step_summary(state)


# ── Step 1: Repository Detection ────────────────────────


def _step_repo_detection(state: WizardState) -> None:
    print("  Step 1: Repository\n")

    # Detect git remote
    try:
        from ._local import resolve_github_remote

        remote = resolve_github_remote(root=state.root)
        if remote:
            state.repo_owner, state.repo_name = remote
            state.project_key = f"{state.repo_owner}/{state.repo_name}"
            print(f"    Detected: {state.project_key}")
    except Exception:
        print("    Could not auto-detect git remote")

    if not state.project_key:
        if state.non_interactive:
            print("    Warning: Could not detect git remote")
        else:
            raw = _prompt("Repository (owner/repo)", default="")
            if raw and "/" in raw:
                parts = raw.split("/", 1)
                state.repo_owner, state.repo_name = parts[0], parts[1]
                state.project_key = raw

    # Check existing config
    config_path = state.root / "CANON.yaml"
    if config_path.exists():
        print("    Existing CANON.yaml found")
        # Load existing values as defaults for both reconfigure and skip paths
        _load_existing_config(state)
        if state.non_interactive:
            # Non-interactive: preserve existing config to avoid silent data loss
            print("    Keeping existing configuration (use interactive mode to reconfigure)")
            state.skip_config_write = True
            print()
            return
        if not _prompt_confirm("Reconfigure?"):
            print("    Keeping existing configuration")
            state.skip_config_write = True
            print()
            return
        print()
    else:
        print()

    # Detect spec files
    for pattern in ["docs/specs/*.md", "docs/*.md", "specs/*.md"]:
        matches = [
            p
            for p in globmod.glob(str(state.root / pattern))
            if not Path(p).name.startswith("_") and Path(p).name != "CLAUDE.md"
        ]
        state.spec_count += len(matches)

    if state.spec_count:
        print(
            f"    Found {state.spec_count} existing spec file{'s' if state.spec_count != 1 else ''}"
        )
        print()


# ── Step 2: Authentication ──────────────────────────────


def _step_authentication(state: WizardState) -> None:
    print("  Step 2: Authentication\n")

    from ._credentials import is_token_expired, load_credentials

    cred = load_credentials()

    if cred and cred.get("method") == "oauth" and not is_token_expired(cred):
        state.authenticated = True
        state.org = cred.get("org", "")
        state.email = cred.get("email", "")
        print(f"    Authenticated as {state.email} (org: {state.org})")
        print()
        return

    if cred and cred.get("method") == "api_key":
        state.authenticated = True
        state.org = cred.get("org", "")
        print(f"    API key configured (org: {state.org})")
        print()
        return

    if cred and cred.get("method") == "token":
        state.authenticated = True
        state.org = cred.get("org", "")
        print("    Token credential stored")
        print()
        return

    # Not authenticated
    if state.non_interactive:
        print("    Not logged in — skipping (backend features unavailable)")
        state.skipped_steps.append("login")
        print()
        return

    print("    Not logged in.")
    print("    Login unlocks: OAuth integrations, org metrics, ticket sync via backend")
    print()

    if _prompt_confirm("Log in now?"):
        try:
            from .login import run_login

            run_login()

            # Re-check credentials
            cred = load_credentials()
            if cred:
                state.authenticated = True
                state.org = cred.get("org", "")
                state.email = cred.get("email", cred.get("org", ""))
                print(f"\n    Authenticated as {state.email}")
        except SystemExit:
            print("    Login skipped")
            state.skipped_steps.append("login")
        except Exception as e:
            print(f"    Login failed: {e}")
            state.skipped_steps.append("login")
    else:
        print("    Skipped — you can run `canon login` later")
        state.skipped_steps.append("login")

    print()


# ── Step 3: Integration ─────────────────────────────────


def _step_integration(state: WizardState) -> None:
    print("  Step 3: Integration\n")

    if state.ticket_system:
        # Pre-set from flag
        pass
    elif state.non_interactive:
        state.ticket_system = "github"
    else:
        systems = ["github", "jira", "linear", "none"]
        print("    Which ticket system?")
        for i, s in enumerate(systems, 1):
            label = {
                "github": "GitHub Issues",
                "jira": "Jira",
                "linear": "Linear",
                "none": "Skip (no ticket sync)",
            }.get(s, s)
            default_marker = " (default)" if s == "github" else ""
            print(f"      {i}. {label}{default_marker}")
        raw = input("    Choice [1]: ").strip()
        if raw == "" or raw == "1":
            state.ticket_system = "github"
        elif raw == "2":
            state.ticket_system = "jira"
        elif raw == "3":
            state.ticket_system = "linear"
        elif raw == "4":
            state.ticket_system = ""
        else:
            try:
                idx = int(raw)
                if 1 <= idx <= len(systems):
                    state.ticket_system = systems[idx - 1]
                    if state.ticket_system == "none":
                        state.ticket_system = ""
            except ValueError:
                if raw in systems:
                    state.ticket_system = raw if raw != "none" else ""

    if not state.ticket_system:
        print("    Skipped — spec management works without ticket sync")
        state.skipped_steps.append("integration")
        print()
        return

    print(f"    Selected: {state.ticket_system}")

    # Try to connect
    from .integration_manager import IntegrationManager

    manager = IntegrationManager(root=state.root)
    integrations = manager.list_all(org=state.org or None)
    already = [
        i
        for i in integrations
        if i.provider == state.ticket_system and i.status in ("connected", "configured")
    ]

    if already:
        print(f"    Already connected: {already[0].details}")
        state.integration_connected = True
        print()
        return

    if state.non_interactive:
        print("    Not connected (run `canon integrations add` after setup)")
        state.skipped_steps.append("integration_connect")
        print()
        return

    print()
    if _prompt_confirm(f"Connect {state.ticket_system} now?"):
        from .integrations_cmd import _run_add

        try:
            _run_add(provider=state.ticket_system, token="", non_interactive=False)
            state.integration_connected = True
        except SystemExit:
            print("    Connection skipped")
            state.skipped_steps.append("integration_connect")
    else:
        print("    Skipped — run `canon integrations add` later")
        state.skipped_steps.append("integration_connect")

    print()


# ── Step 4: Configuration ───────────────────────────────


def _step_configuration(state: WizardState) -> None:
    print("  Step 4: Configuration\n")

    if state.skip_config_write:
        print("    Using existing CANON.yaml (skipped)")
        print()
        return

    # Gather values
    if not state.team:
        default_team = state.org or state.repo_owner or ""
        if state.non_interactive:
            state.team = default_team
        else:
            state.team = _prompt("Team name", default=default_team)

    # Detect doc paths
    doc_paths: list[str] | None = None
    for pattern in ["docs/specs/*.md", "docs/*.md", "specs/*.md"]:
        matches = [
            p for p in globmod.glob(str(state.root / pattern)) if not Path(p).name.startswith("_")
        ]
        if matches:
            if doc_paths is None:
                doc_paths = []
            doc_paths.append(pattern)

    # Write CANON.yaml
    from ..setup import create_canon_yaml

    yaml_content = create_canon_yaml(
        team=state.team,
        ticket_system=state.ticket_system or "github",
        project_key=state.project_key,
        doc_paths=doc_paths,
    )

    config_path = state.root / "CANON.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existed = config_path.exists()
    config_path.write_text(yaml_content)
    state.config_written = True

    print(f"\n    {'Updated' if existed else 'Created'}: CANON.yaml")

    # Create template if needed
    template_path = state.root / "docs" / "specs" / "_template.md"
    if not template_path.exists():
        from ..setup import list_setup_files

        files = list_setup_files(has_config=True)
        for f in files:
            path = state.root / f.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f.content)
            print(f"    Created: {f.path}")

    print()


# ── Step 5: Environment Setup ───────────────────────────


def _step_environment(state: WizardState) -> None:
    print("  Step 5: Environment\n")

    # MCP server
    from ..setup import cleanup_stale_skills, create_mcp_json

    mcp_result = create_mcp_json(state.root)
    if mcp_result == "created":
        print("    Created: .mcp.json")
        state.mcp_written = True
    elif mcp_result == "updated":
        print("    Updated: .mcp.json")
        state.mcp_written = True
    else:
        print("    .mcp.json: already up to date")

    # Clean up stale skills
    if cleanup_stale_skills(state.root):
        print("    Cleaned up stale skills (now provided by canon plugin)")

    # Plugin hint
    from .setup_cmd import _hint_claude_plugin

    _hint_claude_plugin(state.root)

    # MCP validation
    _validate_mcp(state)

    print()


def _validate_mcp(state: WizardState) -> None:
    """Quick MCP server startup validation."""
    import subprocess

    try:
        result = subprocess.run(
            ["uvx", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            print("    MCP runtime: uvx available")
        else:
            print("    MCP runtime: uvx not working")
    except FileNotFoundError:
        print("    MCP runtime: uvx not installed (install uv for MCP support)")
    except (subprocess.SubprocessError, OSError):
        print("    MCP runtime: could not verify")


# ── Step 6: Validation ──────────────────────────────────


def _step_validation(state: WizardState) -> None:
    print("  Step 6: Validation\n")

    from .doctor_cmd import run_doctor

    # Capture doctor output (it prints directly)
    exit_code = run_doctor(json_output=False, fix=False)
    state.doctor_fails = 1 if exit_code == 1 else 0
    state.doctor_warns = 1 if exit_code == 2 else 0
    state.doctor_passed = 1 if exit_code == 0 else 0


# ── Step 7: Summary ─────────────────────────────────────


def _step_summary(state: WizardState) -> None:
    print("  Setup Complete\n")

    # What was done
    actions = []
    if state.config_written:
        actions.append("CANON.yaml configured")
    if state.mcp_written:
        actions.append(".mcp.json configured")
    if state.authenticated:
        actions.append(f"Authenticated as {state.email or state.org}")
    if state.integration_connected:
        actions.append(f"{state.ticket_system} integration connected")

    if actions:
        for a in actions:
            print(f"    {a}")
        print()

    # Next steps (prioritized by what was skipped)
    next_steps = []

    if "login" in state.skipped_steps:
        next_steps.append(("canon login", "Enable ticket sync and org features"))

    if "integration" in state.skipped_steps or "integration_connect" in state.skipped_steps:
        provider = state.ticket_system or "<provider>"
        next_steps.append((f"canon integrations add {provider}", "Enable ticket sync"))

    if state.spec_count > 0:
        next_steps.append(("canon sync --dry-run", "Preview ticket creation from existing specs"))
    else:
        next_steps.append(("canon new", "Create your first spec"))

    next_steps.append(("canon doctor", "Check health anytime"))

    if next_steps:
        print("  Next steps:\n")
        for i, (cmd, desc) in enumerate(next_steps, 1):
            print(f"    {i}. `{cmd}` — {desc}")
        print()


# ── Helpers ────���─────────────────────────────────────────


def _load_existing_config(state: WizardState) -> None:
    """Load values from existing CANON.yaml into state."""
    config_path = state.root / "CANON.yaml"
    if not config_path.exists():
        return

    try:
        from canon.config.parse import parse_canon_yaml

        result = parse_canon_yaml(config_path.read_text())
        config = result.config
        if config.team:
            state.team = config.team
        if config.ticket_system:
            state.ticket_system = config.ticket_system
        if config.project_key:
            state.project_key = config.project_key
    except Exception:
        print("    Warning: could not load existing CANON.yaml values")
