"""canon doctor — diagnostic health check for Canon installations."""

from __future__ import annotations

import argparse
import glob as globmod
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    category: str  # config, auth, integrations, mcp
    status: str  # pass, warn, fail
    message: str
    fix_hint: str | None = None
    fix_action: Callable[[], bool] | None = field(default=None, repr=False)


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "doctor",
        help="Check the health of your Canon installation",
        description="Run diagnostic checks on config, auth, integrations, and MCP server.",
    )
    parser.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to auto-fix issues where possible",
    )


def run_doctor(*, json_output: bool = False, fix: bool = False) -> int:
    """Run all checks and report results. Returns exit code."""
    root = Path.cwd()
    results: list[CheckResult] = []

    # Run all checks
    results.extend(_config_checks(root))
    results.extend(_auth_checks())
    results.extend(_integration_checks(root))
    results.extend(_mcp_checks(root))

    # Auto-fix if requested
    if fix:
        fixable = [r for r in results if r.status == "fail" and r.fix_action is not None]
        if fixable:
            for r in fixable:
                if r.fix_action():
                    r.status = "pass"
                    r.message += " (fixed)"
        else:
            failed = [r for r in results if r.status == "fail"]
            if failed:
                print("No auto-fix available for current failures. See hints below.\n")

    # Output
    if json_output:
        data = [
            {
                "name": r.name,
                "category": r.category,
                "status": r.status,
                "message": r.message,
                "fix_hint": r.fix_hint,
            }
            for r in results
        ]
        print(json.dumps(data, indent=2))
    else:
        _print_results(results)

    # Exit code
    has_fail = any(r.status == "fail" for r in results)
    has_warn = any(r.status == "warn" for r in results)
    if has_fail:
        return 1
    if has_warn:
        return 2
    return 0


# ── Config Checks ───────��────────────────────────────────


def _config_checks(root: Path) -> list[CheckResult]:
    results = []

    # CANON.yaml
    config_path = root / "CANON.yaml"
    if config_path.exists():
        try:
            from canon.config.parse import parse_canon_yaml

            parsed = parse_canon_yaml(config_path.read_text())
            errors = [d for d in parsed.diagnostics if d.severity == "error"]
            warnings = [d for d in parsed.diagnostics if d.severity == "warning"]
            if errors:
                results.append(
                    CheckResult(
                        name="CANON.yaml",
                        category="config",
                        status="fail",
                        message=f"Parse errors: {errors[0].message}",
                        fix_hint="Fix the CANON.yaml syntax errors",
                    )
                )
            elif warnings:
                results.append(
                    CheckResult(
                        name="CANON.yaml",
                        category="config",
                        status="warn",
                        message=f"Warnings: {warnings[0].message}",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="CANON.yaml",
                        category="config",
                        status="pass",
                        message="Valid configuration",
                    )
                )
        except Exception as e:
            results.append(
                CheckResult(
                    name="CANON.yaml",
                    category="config",
                    status="fail",
                    message=f"Failed to parse: {e}",
                    fix_hint="Run `canon setup` to regenerate",
                )
            )
    else:
        results.append(
            CheckResult(
                name="CANON.yaml",
                category="config",
                status="fail",
                message="Not found",
                fix_hint="Run `canon setup` to create",
            )
        )

    # .mcp.json
    mcp_path = root / ".mcp.json"
    if mcp_path.exists():
        try:
            import json as json_mod

            data = json_mod.loads(mcp_path.read_text())
            servers = data.get("mcpServers", {})
            has_canon = "canon" in servers or "specwright" in servers
            if has_canon:
                results.append(
                    CheckResult(
                        name=".mcp.json",
                        category="config",
                        status="pass",
                        message="Canon MCP server configured",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name=".mcp.json",
                        category="config",
                        status="warn",
                        message="No canon server entry",
                        fix_hint="Run `canon setup` to regenerate",
                    )
                )
        except json.JSONDecodeError:
            results.append(
                CheckResult(
                    name=".mcp.json",
                    category="config",
                    status="fail",
                    message="Invalid JSON",
                    fix_hint="Run `canon setup` to regenerate",
                )
            )
        except Exception as e:
            results.append(
                CheckResult(
                    name=".mcp.json",
                    category="config",
                    status="fail",
                    message=f"Cannot read: {e}",
                    fix_hint="Check file permissions",
                )
            )
    else:
        results.append(
            CheckResult(
                name=".mcp.json",
                category="config",
                status="warn",
                message="Not found (MCP features unavailable)",
                fix_hint="Run `canon setup` to create",
            )
        )

    # Spec files
    spec_patterns = ["docs/specs/*.md", "docs/*.md", "specs/*.md"]
    spec_count = 0
    for pattern in spec_patterns:
        matches = [
            p
            for p in globmod.glob(str(root / pattern))
            if not Path(p).name.startswith("_") and Path(p).name != "CLAUDE.md"
        ]
        spec_count += len(matches)

    if spec_count > 0:
        results.append(
            CheckResult(
                name="Spec files",
                category="config",
                status="pass",
                message=f"Found {spec_count} spec file{'s' if spec_count != 1 else ''}",
            )
        )
    else:
        results.append(
            CheckResult(
                name="Spec files",
                category="config",
                status="warn",
                message="No spec files found",
                fix_hint="Create your first spec: `canon new`",
            )
        )

    # Project key vs git remote consistency
    if config_path.exists():
        try:
            from canon.config.parse import parse_canon_yaml

            from ._local import resolve_github_remote

            cfg = parse_canon_yaml(config_path.read_text()).config
            remote = resolve_github_remote(root=root)
            if cfg.project_key and remote:
                git_project = f"{remote[0]}/{remote[1]}"
                if cfg.project_key != git_project:
                    results.append(
                        CheckResult(
                            name="Project key",
                            category="config",
                            status="warn",
                            message=f"CANON.yaml project_key '{cfg.project_key}' differs from git remote '{git_project}'",
                            fix_hint="Update project_key in CANON.yaml or check your git remote",
                        )
                    )
        except Exception:
            pass  # Non-critical, skip silently

    return results


# ── Auth Checks ──────────────────────────────────────────


def _check_jwt_org_scope(token: str, *, auth_method: str = "") -> CheckResult | None:
    """Decode JWT and check if org_id claim is present.

    Returns a CheckResult if there's a problem, None if OK or unable to check.
    """
    if not token or token.count(".") != 2:
        return None

    import base64

    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None

    org_id = claims.get("org_id", "")
    if org_id:
        return CheckResult(
            name="Token org scope",
            category="auth",
            status="pass",
            message="JWT has org_id claim",
        )

    # Auth0's device authorization grant does not propagate the organization
    # parameter into the access token — this is a known Auth0 limitation, not
    # a misconfiguration. The backend already handles unscoped tokens via
    # registry-based org resolution, so this is not actionable for the user.
    if auth_method == "oauth":
        return None

    # Non-device-flow tokens (e.g. web login) should have org_id when an org
    # is configured — warn only for those.
    try:
        from .integrations_cmd import _get_org

        detected_org = _get_org()
    except Exception:
        return None

    if detected_org:
        return CheckResult(
            name="Token org scope",
            category="auth",
            status="warn",
            message=f"JWT lacks org_id claim — backend may reject requests for org '{detected_org}'",
            fix_hint=f"Run `canon login --org {detected_org}` to get an org-scoped token",
        )

    return None


def _auth_checks() -> list[CheckResult]:
    results = []

    # Canon credentials
    from ._credentials import is_token_expired, load_credentials

    cred = load_credentials()
    if cred is None:
        results.append(
            CheckResult(
                name="Canon auth",
                category="auth",
                status="warn",
                message="Not logged in (backend features unavailable)",
                fix_hint="Run `canon login`",
            )
        )
    elif cred.get("method") == "oauth":
        if is_token_expired(cred):
            results.append(
                CheckResult(
                    name="Canon auth",
                    category="auth",
                    status="warn",
                    message=f"Token expired for {cred.get('email', 'unknown')}",
                    fix_hint="Run `canon login` to refresh",
                )
            )
        else:
            org = cred.get("org", "unknown")
            email = cred.get("email", "unknown")
            results.append(
                CheckResult(
                    name="Canon auth",
                    category="auth",
                    status="pass",
                    message=f"Authenticated as {email} (org: {org})",
                )
            )

            # Check JWT org scope
            token = cred.get("access_token", "")
            org_scope = _check_jwt_org_scope(token, auth_method=cred.get("method", ""))
            if org_scope:
                results.append(org_scope)
    elif cred.get("method") == "api_key":
        results.append(
            CheckResult(
                name="Canon auth",
                category="auth",
                status="pass",
                message=f"API key configured (org: {cred.get('org', 'unknown')})",
            )
        )
    elif cred.get("method") == "token":
        results.append(
            CheckResult(
                name="Canon auth",
                category="auth",
                status="pass",
                message="Token credential stored",
            )
        )

    # GitHub CLI
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            results.append(
                CheckResult(
                    name="GitHub CLI",
                    category="auth",
                    status="pass",
                    message="Authenticated",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="GitHub CLI",
                    category="auth",
                    status="warn",
                    message="Not authenticated",
                    fix_hint="Run `gh auth login`",
                )
            )
    except FileNotFoundError:
        results.append(
            CheckResult(
                name="GitHub CLI",
                category="auth",
                status="warn",
                message="Not installed",
                fix_hint="Install from https://cli.github.com",
            )
        )
    except (subprocess.SubprocessError, OSError):
        results.append(
            CheckResult(
                name="GitHub CLI",
                category="auth",
                status="warn",
                message="Could not verify status",
            )
        )

    return results


# ─��� Integration Checks ───────────────────────────────────


def _integration_checks(root: Path) -> list[CheckResult]:
    results = []

    from .integration_manager import IntegrationManager

    manager = IntegrationManager(root=root)

    from .integrations_cmd import _get_org

    org = _get_org()

    integrations = manager.list_all(org=org)
    configured = [i for i in integrations if i.status != "not_configured"]

    if not configured:
        hint = "Run `canon integrations add <provider>`"
        # Check if backend is reachable but returning auth errors
        import re as _re

        if org and _re.match(r"^[a-zA-Z0-9_\-\.]+$", org):
            try:
                from ._platform import PlatformClient

                client = PlatformClient()
                resp = client.request(
                    "GET",
                    f"/app/{org}/api/settings/integrations",
                    headers={"Accept": "application/json"},
                )
                client.close()
                if resp.status_code in (401, 403):
                    hint = (
                        f"Backend returned {resp.status_code} for org '{org}'. "
                        "Integrations may be configured on the web but your CLI "
                        "token lacks org scope. Check Settings > Integrations at "
                        f"https://canonhq.co/app/{org}/settings/integrations"
                    )
            except Exception as e:
                hint = f"Backend check failed: {e}. {hint}"

        results.append(
            CheckResult(
                name="Integrations",
                category="integrations",
                status="warn",
                message="No integrations configured locally",
                fix_hint=hint,
            )
        )
        return results

    for info in configured:
        from .integrations_cmd import _format_provider

        name = _format_provider(info.provider)

        if info.status == "needs_reauth":
            results.append(
                CheckResult(
                    name=name,
                    category="integrations",
                    status="fail",
                    message="Needs re-authentication",
                    fix_hint=f"Run `canon integrations add {info.provider}` to reconnect",
                )
            )
        elif info.status == "error":
            results.append(
                CheckResult(
                    name=name,
                    category="integrations",
                    status="fail",
                    message="Connection error",
                    fix_hint=f"Run `canon integrations test {info.provider}` for details",
                )
            )
        else:
            # Run a lightweight connection test for backend integrations.
            # Skip for canon_yaml-sourced integrations without local
            # credentials (e.g. GitHub App — tested via the GitHub App,
            # not a local token).
            if info.source == "backend":
                test_result = manager.test_connection(info.provider, org=org)
                if test_result.ok:
                    latency = f" ({test_result.latency_ms:.0f}ms)" if test_result.latency_ms else ""
                    results.append(
                        CheckResult(
                            name=name,
                            category="integrations",
                            status="pass",
                            message=f"{info.source}: {info.details}{latency}",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            name=name,
                            category="integrations",
                            status="warn",
                            message=f"Configured but test failed: {test_result.message}",
                            fix_hint=f"Run `canon integrations test {info.provider}`",
                        )
                    )
            else:
                results.append(
                    CheckResult(
                        name=name,
                        category="integrations",
                        status="pass",
                        message=f"{info.source}: {info.details}",
                    )
                )

    return results


# ── MCP Checks ───────────────────────────────────────────


def _mcp_checks(root: Path) -> list[CheckResult]:
    results = []

    mcp_path = root / ".mcp.json"
    if not mcp_path.exists():
        return results  # Already reported in config checks

    # Check if uvx is available
    try:
        result = subprocess.run(
            ["uvx", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            results.append(
                CheckResult(
                    name="MCP runtime",
                    category="mcp",
                    status="warn",
                    message="uvx not available",
                    fix_hint="Install uv: https://docs.astral.sh/uv/",
                )
            )
            return results
    except FileNotFoundError:
        results.append(
            CheckResult(
                name="MCP runtime",
                category="mcp",
                status="warn",
                message="uvx not installed",
                fix_hint="Install uv: https://docs.astral.sh/uv/",
            )
        )
        return results
    except (subprocess.SubprocessError, OSError):
        results.append(
            CheckResult(
                name="MCP runtime",
                category="mcp",
                status="warn",
                message="Could not verify uvx",
            )
        )
        return results

    results.append(
        CheckResult(
            name="MCP runtime",
            category="mcp",
            status="pass",
            message="uvx available",
        )
    )

    return results


# ── Output Formatting ──────────��─────────────────────────


def _print_results(results: list[CheckResult]) -> None:
    categories = ["config", "auth", "integrations", "mcp"]
    category_labels = {
        "config": "Configuration",
        "auth": "Authentication",
        "integrations": "Integrations",
        "mcp": "MCP Server",
    }

    print("\nCanon Doctor\n")

    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        if not cat_results:
            continue

        print(f"  {category_labels.get(cat, cat)}")
        for r in cat_results:
            icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[r.status]
            print(f"    {icon}  {r.name}: {r.message}")
            if r.fix_hint and r.status != "pass":
                print(f"           {r.fix_hint}")
        print()

    # Summary
    passed = sum(1 for r in results if r.status == "pass")
    warns = sum(1 for r in results if r.status == "warn")
    fails = sum(1 for r in results if r.status == "fail")
    print(f"  {passed} passed, {warns} warnings, {fails} failures\n")
