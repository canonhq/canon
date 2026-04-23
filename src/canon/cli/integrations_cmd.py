"""canon integrations — manage ticket system and service connections."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import webbrowser
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

from .integration_manager import (
    SUPPORTED_PROVIDERS,
    IntegrationManager,
    TestResult,
)


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the ``integrations`` subcommand and sub-subcommands."""
    parser = subparsers.add_parser(
        "integrations",
        help="Manage ticket system and service connections",
        description="List, add, remove, and test integration connections.",
        aliases=["int"],
    )
    int_sub = parser.add_subparsers(dest="int_command")

    # canon integrations list
    list_p = int_sub.add_parser("list", help="List configured integrations")
    list_p.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    list_p.add_argument(
        "--source",
        choices=["backend", "local", "env"],
        default=None,
        help="Filter by credential source",
    )

    # canon integrations add <provider>
    add_p = int_sub.add_parser("add", help="Connect a ticket system or service")
    add_p.add_argument("provider", choices=list(SUPPORTED_PROVIDERS), help="Provider to connect")
    add_p.add_argument("--token", default="", help="API token (skip interactive prompt)")
    add_p.add_argument("--non-interactive", action="store_true", help="Fail if prompts needed")

    # canon integrations remove <provider>
    rm_p = int_sub.add_parser("remove", help="Disconnect an integration")
    rm_p.add_argument("provider", choices=list(SUPPORTED_PROVIDERS), help="Provider to disconnect")
    rm_p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    # canon integrations test [provider]
    test_p = int_sub.add_parser("test", help="Health check integration connections")
    test_p.add_argument(
        "provider",
        nargs="?",
        default=None,
        choices=list(SUPPORTED_PROVIDERS),
        help="Provider to test (default: all configured)",
    )
    test_p.add_argument("--json", dest="json_output", action="store_true", help="JSON output")


def run_integrations(args: argparse.Namespace) -> None:
    """Dispatch to the correct integrations subcommand."""
    cmd = getattr(args, "int_command", None)
    if cmd == "list":
        _run_list(json_output=args.json_output, source_filter=args.source)
    elif cmd == "add":
        _run_add(
            provider=args.provider,
            token=args.token,
            non_interactive=args.non_interactive,
        )
    elif cmd == "remove":
        _run_remove(provider=args.provider, yes=args.yes)
    elif cmd == "test":
        _run_test(provider=args.provider, json_output=args.json_output)
    else:
        # No subcommand — show help
        print("Usage: canon integrations <list|add|remove|test>")
        print("Run `canon integrations --help` for details.")
        sys.exit(1)


# ── List ─────────────────────────────────────────────────


def _run_list(*, json_output: bool = False, source_filter: str | None = None) -> None:
    org = _get_org()
    manager = IntegrationManager()
    integrations = manager.list_all(org=org)

    # Apply source filter (exclude not_configured stubs — they have no real source)
    if source_filter:
        source_map = {"backend": "backend", "local": "canon_yaml", "env": "env_var"}
        target_source = source_map.get(source_filter, source_filter)
        integrations = [
            i for i in integrations if i.source == target_source and i.status != "not_configured"
        ]

    if json_output:
        data = [
            {
                "provider": i.provider,
                "source": i.source,
                "status": i.status,
                "details": i.details,
                "metadata": i.metadata,
            }
            for i in integrations
        ]
        print(json.dumps(data, indent=2))
        return

    # Table output
    configured = [i for i in integrations if i.status != "not_configured"]
    not_configured = [i for i in integrations if i.status == "not_configured"]

    if not configured and not not_configured:
        print("No integrations found.")
        return

    project = _get_project_display()
    print(f"\nIntegrations{f' for {project}' if project else ''}\n")

    # Header
    print(f"  {'Provider':<18}{'Source':<14}{'Status':<16}{'Details'}")
    print(f"  {'─' * 65}")

    for info in integrations:
        status_display = _format_status(info.status)
        source_display = _format_source(info.source) if info.status != "not_configured" else ""
        details = info.details if info.status != "not_configured" else ""
        provider_display = _format_provider(info.provider)
        print(f"  {provider_display:<18}{source_display:<14}{status_display:<16}{details}")

    # Summary
    connected = sum(1 for i in integrations if i.status in ("connected", "configured"))
    not_conf = len(not_configured)
    print(f"\n  {connected} connected, {not_conf} not configured")

    if not_configured:
        providers = ", ".join(i.provider for i in not_configured)
        print(f"  Run `canon integrations add <{providers}>` to connect.")

    if not org:
        print("\n  Hint: Run `canon login` to see backend-managed integrations.")
    elif not any(i.source == "backend" for i in integrations if i.status != "not_configured"):
        # Authenticated but no backend integrations — likely org scope issue
        from ._credentials import load_credentials

        cred = load_credentials()
        if cred and not cred.get("org"):
            print(f"\n  Hint: Run `canon login --org {org}` to link your credentials to this org.")

    print()


# ── Add ──────────────────────────────────────────────────


def _run_add(*, provider: str, token: str = "", non_interactive: bool = False) -> None:
    manager = IntegrationManager()
    org = _get_org()

    # Check if already connected
    existing = [i for i in manager.list_all(org=org) if i.provider == provider]
    if existing and existing[0].status in ("connected", "configured"):
        info = existing[0]
        print(f"\n{_format_provider(provider)} is already connected:")
        print(f"  Source: {_format_source(info.source)}")
        print(f"  Status: {_format_status(info.status)}")
        if info.details:
            print(f"  Details: {info.details}")
        print()
        if non_interactive:
            print("Already connected. Use --token to reconfigure.")
            return
        if not _prompt_confirm("Replace existing connection?", default=False):
            print("Cancelled.")
            return

    # Try OAuth via backend if authenticated
    if org and not token and _try_oauth_flow(provider, org, non_interactive=non_interactive):
        return

    # Local flow — API token
    _run_add_local(provider, manager, token=token, non_interactive=non_interactive)


def _try_oauth_flow(provider: str, org: str, *, non_interactive: bool = False) -> bool:
    """Attempt OAuth browser flow via Canon backend.

    Returns True if successful, False to fall back to local flow.
    """
    if provider == "github":
        # GitHub Issues uses GitHub App installation, not OAuth
        return False

    try:
        from ._platform import PlatformClient

        client = PlatformClient()
    except Exception:
        return False

    try:
        # Get the OAuth URL
        resp = client.get(f"/app/{org}/api/settings/integrations/{provider}/connect?cli=true")
        if resp.status_code != 200:
            return False

        data = resp.json()
        auth_url = data.get("authorize_url", "")
        if not auth_url:
            return False

        if non_interactive:
            print(f"OAuth flow requires a browser. URL: {auth_url}")
            print("Run without --non-interactive to open the browser automatically.")
            return False

        print(f"\nOpening browser to connect {_format_provider(provider)}...")
        print(f"  URL: {auth_url}\n")

        parsed = urlparse(auth_url)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            with suppress(Exception):
                webbrowser.open(auth_url)

        # Poll for completion
        print("Waiting for authorization...", end="", flush=True)
        deadline = time.time() + 120
        while time.time() < deadline:
            time.sleep(2)
            resp = client.get(f"/app/{org}/api/settings/integrations")
            if resp.status_code == 200:
                data = resp.json()
                entries = data.get("integrations", data) if isinstance(data, dict) else data
                for entry in entries:
                    if entry.get("provider") == provider and entry.get("status") == "active":
                        raw_meta = entry.get("provider_metadata", {}) or {}
                        if isinstance(raw_meta, str):
                            import json as _json

                            try:
                                meta = _json.loads(raw_meta)
                            except (ValueError, TypeError):
                                meta = {}
                        else:
                            meta = raw_meta
                        name = (
                            meta.get("site_name", "") or meta.get("workspace_name", "") or provider
                        )
                        print(f"\n\nConnected {_format_provider(provider)}: {name}")
                        return True
            print(".", end="", flush=True)

        print("\n\nTimed out waiting for OAuth completion.")
        print("You can complete the flow in your browser and try again.")
        return False
    except Exception as e:
        logger.debug("OAuth flow failed: %s", e, exc_info=True)
        print(f"\n  Could not complete OAuth flow: {e}")
        print("  Falling back to API token configuration.")
        return False
    finally:
        client.close()


def _run_add_local(
    provider: str,
    manager: IntegrationManager,
    *,
    token: str = "",
    non_interactive: bool = False,
) -> None:
    """Local flow — configure integration via API token + CANON.yaml."""
    print(f"\nConfiguring {_format_provider(provider)} locally\n")

    project_key = manager._get_project_key()

    if provider == "jira":
        _add_jira_local(manager, project_key, token=token, non_interactive=non_interactive)
    elif provider == "linear":
        _add_linear_local(manager, project_key, token=token, non_interactive=non_interactive)
    elif provider == "github":
        _add_github_local(manager, project_key, token=token, non_interactive=non_interactive)


def _add_jira_local(
    manager: IntegrationManager,
    project_key: str,
    *,
    token: str = "",
    non_interactive: bool = False,
) -> None:
    if non_interactive and not token:
        print("Error: --token required in non-interactive mode for Jira")
        sys.exit(1)

    host = ""
    email = ""
    api_token = token

    if not non_interactive:
        host = _prompt("Jira host (e.g. acme.atlassian.net)")
        if not host:
            print("Error: Jira host is required")
            sys.exit(1)
        email = _prompt("Jira email")
        if not email:
            print("Error: Jira email is required")
            sys.exit(1)
        if not api_token:
            api_token = _prompt("Jira API token")
        if not api_token:
            print("Error: API token is required")
            sys.exit(1)
        jira_project = _prompt(
            "Jira project key",
            default=project_key.split("/")[-1] if "/" in project_key else project_key,
        )
    else:
        host = _env_or_fail("JIRA_HOST", "Jira host")
        email = _env_or_fail("JIRA_EMAIL", "Jira email")
        jira_project = project_key

    # Set env var hints
    print()
    print("Set these environment variables (or add to .env):")
    print(f"  JIRA_HOST={host}")
    print(f"  JIRA_EMAIL={email}")
    print("  JIRA_API_TOKEN=<your-token>")
    print()

    # Test connection
    import os

    os.environ["JIRA_HOST"] = host
    os.environ["JIRA_EMAIL"] = email
    os.environ["JIRA_API_TOKEN"] = api_token

    result = manager.test_connection("jira")
    if result.ok:
        print(f"Connection successful ({result.latency_ms:.0f}ms)")
        manager.add_local_integration("jira", project_key=jira_project, host_override=host)
        print("Updated CANON.yaml")
        print("\n  Important: Set JIRA_HOST, JIRA_EMAIL, and JIRA_API_TOKEN")
        print("  permanently in your shell profile or .env file for canon sync to work.")
    else:
        print(f"Connection failed: {result.message}")
        if not non_interactive and _prompt_confirm("Save config anyway?", default=False):
            manager.add_local_integration("jira", project_key=jira_project, host_override=host)
            print("Updated CANON.yaml (connection not verified)")
        else:
            print("Aborted.")
            sys.exit(1)


def _add_linear_local(
    manager: IntegrationManager,
    project_key: str,
    *,
    token: str = "",
    non_interactive: bool = False,
) -> None:
    if non_interactive and not token:
        print("Error: --token required in non-interactive mode for Linear")
        sys.exit(1)

    api_key = token
    team_key = ""

    if not non_interactive:
        if not api_key:
            api_key = _prompt("Linear API key")
        if not api_key:
            print("Error: API key is required")
            sys.exit(1)
        team_key = _prompt(
            "Linear team key",
            default=project_key.split("/")[-1] if "/" in project_key else project_key,
        )
    else:
        team_key = project_key

    print()
    print("Set this environment variable (or add to .env):")
    print("  LINEAR_API_KEY=<your-key>")
    print()

    import os

    os.environ["LINEAR_API_KEY"] = api_key

    result = manager.test_connection("linear")
    if result.ok:
        print(f"Connection successful ({result.latency_ms:.0f}ms)")
        manager.add_local_integration("linear", project_key=team_key)
        print("Updated CANON.yaml")
        print("\n  Important: Set LINEAR_API_KEY permanently in your")
        print("  shell profile or .env file for canon sync to work.")
    else:
        print(f"Connection failed: {result.message}")
        if not non_interactive and _prompt_confirm("Save config anyway?", default=False):
            manager.add_local_integration("linear", project_key=team_key)
            print("Updated CANON.yaml (connection not verified)")
        else:
            print("Aborted.")
            sys.exit(1)


def _add_github_local(
    manager: IntegrationManager,
    project_key: str,
    *,
    token: str = "",
    non_interactive: bool = False,
) -> None:
    gh_token = token or ""
    repo = project_key

    if not non_interactive:
        if not gh_token:
            # Check gh CLI first
            import subprocess

            try:
                result = subprocess.run(
                    ["gh", "auth", "token"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    gh_token = result.stdout.strip()
                    print("Using token from GitHub CLI (gh)")
            except (FileNotFoundError, subprocess.SubprocessError):
                pass

        if not gh_token:
            gh_token = _prompt("GitHub token (or run `gh auth login` first)")
        if not gh_token:
            print("Error: GitHub token is required")
            sys.exit(1)

        repo = _prompt("Repository (owner/repo)", default=project_key)
        if not repo or "/" not in repo:
            print("Error: Repository must be in owner/repo format")
            sys.exit(1)
    else:
        if not gh_token:
            gh_token = _env_or_fail("GITHUB_TOKEN", "GitHub token")

    if not repo or "/" not in repo:
        print("Error: Repository must be in owner/repo format")
        sys.exit(1)

    import os

    os.environ["GITHUB_TOKEN"] = gh_token
    parts = repo.split("/", 1)
    os.environ["GITHUB_OWNER"] = parts[0]
    os.environ["GITHUB_REPO"] = parts[1]

    result = manager.test_connection("github")
    if result.ok:
        print(f"Connection successful ({result.latency_ms:.0f}ms)")
        manager.add_local_integration("github", project_key=repo)
        print("Updated CANON.yaml")
    else:
        print(f"Connection failed: {result.message}")
        if not non_interactive and _prompt_confirm("Save config anyway?", default=False):
            manager.add_local_integration("github", project_key=repo)
            print("Updated CANON.yaml (connection not verified)")
        else:
            print("Aborted.")
            sys.exit(1)


# ── Remove ───────────────────────────────────────────────


def _run_remove(*, provider: str, yes: bool = False) -> None:
    manager = IntegrationManager()
    org = _get_org()
    integrations = [i for i in manager.list_all(org=org) if i.provider == provider]

    if not integrations or integrations[0].status == "not_configured":
        print(f"{_format_provider(provider)} is not configured.")
        return

    info = integrations[0]
    print(f"\n{_format_provider(provider)} connection:")
    print(f"  Source: {_format_source(info.source)}")
    print(f"  Status: {_format_status(info.status)}")
    if info.details:
        print(f"  Details: {info.details}")
    print(f"\n  Warning: Ticket sync for {provider} will stop working.\n")

    if not yes and not _prompt_confirm(f"Disconnect {_format_provider(provider)}?", default=False):
        print("Cancelled.")
        return

    removed = False

    # Remove from backend if that's the source
    if info.source == "backend" and org:
        try:
            from ._platform import PlatformClient

            client = PlatformClient()
            resp = client.request("DELETE", f"/app/{org}/api/settings/integrations/{provider}")
            client.close()
            if resp.status_code in (200, 204):
                removed = True
                print(f"Removed {_format_provider(provider)} from Canon backend.")
            else:
                print(f"Warning: Backend removal returned HTTP {resp.status_code}")
        except Exception as e:
            print(f"Warning: Could not remove from backend: {e}")

    # Remove from CANON.yaml
    if manager.remove_local_integration(provider):
        removed = True
        print(f"Removed {_format_provider(provider)} from CANON.yaml.")

    # Env var hint
    if info.source == "env_var":
        env_hints = {
            "jira": ["JIRA_HOST", "JIRA_EMAIL", "JIRA_API_TOKEN"],
            "linear": ["LINEAR_API_KEY"],
            "github": ["GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO"],
        }
        vars_to_clear = env_hints.get(provider, [])
        if vars_to_clear:
            print("\nAlso unset these environment variables:")
            for var in vars_to_clear:
                print(f"  unset {var}")

    if not removed:
        print(f"No local configuration found for {_format_provider(provider)}.")


# ── Test ─────────────────────────────────────────────────


def _run_test(*, provider: str | None = None, json_output: bool = False) -> None:
    manager = IntegrationManager()
    org = _get_org()

    if provider:
        providers_to_test = [provider]
    else:
        integrations = manager.list_all(org=org)
        providers_to_test = [
            i.provider for i in integrations if i.status in ("connected", "configured")
        ]

    if not providers_to_test:
        print("No configured integrations to test.")
        print("Run `canon integrations add <provider>` to connect one.")
        sys.exit(1)

    results: list[TestResult] = []
    for p in providers_to_test:
        result = manager.test_connection(p, org=org)
        results.append(result)

    if json_output:
        data = [
            {
                "provider": r.provider,
                "ok": r.ok,
                "message": r.message,
                "latency_ms": round(r.latency_ms, 1),
            }
            for r in results
        ]
        print(json.dumps(data, indent=2))
    else:
        print()
        for r in results:
            icon = "PASS" if r.ok else "FAIL"
            latency = f" ({r.latency_ms:.0f}ms)" if r.latency_ms > 0 else ""
            print(f"  {icon}  {_format_provider(r.provider)}: {r.message}{latency}")
        print()

    any_failed = any(not r.ok for r in results)
    if any_failed:
        sys.exit(1)


# ── Helpers ──────────────────────────────────────────────

logger = logging.getLogger(__name__)


def _get_org() -> str | None:
    """Get the org from credentials, CANON.yaml, or git remote.

    Resolution order:
    1. Saved credentials ``org`` field
    2. CANON.yaml ``team`` field
    3. Git remote owner (GitHub owner = Canon org)

    Returns None if no org found or if the resolved value fails slug validation.
    """
    import re

    from ._credentials import load_credentials

    org: str | None = None

    cred = load_credentials()
    if cred:
        org = cred.get("org") or None

    # CANON.yaml team field
    if not org:
        root = Path.cwd()
        config_path = root / "CANON.yaml"
        if config_path.exists():
            try:
                from canon.config.parse import parse_canon_yaml

                result = parse_canon_yaml(config_path.read_text())
                if result.config.team:
                    org = result.config.team
            except Exception:
                logger.debug("Failed to read org from CANON.yaml", exc_info=True)

    # Git remote owner
    if not org:
        try:
            from ._local import resolve_github_remote

            remote = resolve_github_remote(root=Path.cwd())
            if remote:
                org = remote[0]
        except Exception:
            logger.debug("Failed to detect org from git remote", exc_info=True)

    # Validate slug to prevent path traversal
    if org and not re.match(r"^[a-zA-Z0-9_\-\.]+$", org):
        logger.warning("Invalid org slug %r — ignoring", org)
        return None

    return org


def _get_project_display() -> str:
    """Get a display string for the current project."""
    try:
        from ._local import resolve_github_remote

        remote = resolve_github_remote(root=Path.cwd())
        if remote:
            return f"{remote[0]}/{remote[1]}"
    except Exception:
        pass
    return ""


def _format_provider(provider: str) -> str:
    names = {"jira": "Jira", "linear": "Linear", "github": "GitHub Issues"}
    return names.get(provider, provider)


def _format_status(status: str) -> str:
    return {
        "connected": "connected",
        "configured": "configured",
        "needs_reauth": "needs reauth",
        "error": "error",
        "not_configured": "not configured",
    }.get(status, status)


def _format_source(source: str) -> str:
    return {
        "backend": "backend",
        "env_var": "env var",
        "canon_yaml": "canon.yaml",
    }.get(source, source)


def _prompt(message: str, default: str = "") -> str:
    if default:
        raw = input(f"  {message} [{default}]: ").strip()
        return raw or default
    return input(f"  {message}: ").strip()


def _prompt_confirm(message: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"  {message} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _env_or_fail(var: str, label: str) -> str:
    import os

    val = os.environ.get(var, "")
    if not val:
        print(f"Error: {label} required — set {var} environment variable")
        sys.exit(1)
    return val
