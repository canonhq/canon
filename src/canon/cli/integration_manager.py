"""Unified integration management across all credential sources.

Provides a single view of configured integrations from:
1. CANON.yaml auth_profiles (per-repo overrides) — highest priority
2. Backend org_integrations (per-org OAuth credentials) — when authenticated
3. Environment variables (self-hosted / env-var deployments) — fallback
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("jira", "linear", "github")

# Org slug must be a simple identifier — no path traversal characters.
_ORG_SLUG_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")

CredentialSource = Literal["backend", "env_var", "canon_yaml"]
ConnectionStatus = Literal["connected", "configured", "needs_reauth", "error", "not_configured"]


@dataclass
class IntegrationInfo:
    """A single integration from any credential source."""

    provider: str
    source: CredentialSource
    status: ConnectionStatus
    details: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    """Result of a connection health check."""

    provider: str
    ok: bool
    message: str
    latency_ms: float = 0.0


class IntegrationManager:
    """Unified view across all credential sources."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path.cwd()

    def list_all(self, org: str | None = None) -> list[IntegrationInfo]:
        """Merge backend + local + env var integrations.

        Returns one entry per provider, preferring the highest-priority source.
        Unauthenticated calls skip backend lookup.
        """
        results: dict[str, IntegrationInfo] = {}

        # 1. CANON.yaml (baseline — knows what's configured locally)
        for info in self._from_canon_yaml():
            results[info.provider] = info

        # 2. Backend (if authenticated) — overrides CANON.yaml for providers
        # where the backend has live OAuth connections with richer status info
        if org:
            for info in self._from_backend(org):
                results[info.provider] = info

        # 3. Environment variables (only for providers not yet seen)
        for info in self._from_env_vars():
            if info.provider not in results:
                results[info.provider] = info

        # Add "not configured" for providers with no source
        for provider in SUPPORTED_PROVIDERS:
            if provider not in results:
                results[provider] = IntegrationInfo(
                    provider=provider,
                    source="env_var",
                    status="not_configured",
                    details="",
                )

        return sorted(results.values(), key=lambda i: SUPPORTED_PROVIDERS.index(i.provider))

    def test_connection(self, provider: str, org: str | None = None) -> TestResult:
        """Health check a single integration.

        Uses backend API when authenticated, local adapter instantiation otherwise.
        """
        if org:
            result = self._test_via_backend(provider, org)
            if result is not None:
                return result

        return self._test_locally(provider)

    # ── Backend source ──────────────────────────────────────

    def _from_backend(self, org: str) -> list[IntegrationInfo]:
        """Query the Canon backend for org-level integrations."""
        if not _ORG_SLUG_RE.match(org):
            logger.warning("Invalid org slug %r — skipping backend query", org)
            return []

        try:
            from ._platform import AuthRequiredError, PlatformClient

            client = PlatformClient()
        except ImportError:
            return []
        except AuthRequiredError:
            logger.debug("Not authenticated — skipping backend query")
            return []
        except Exception:
            logger.warning("Failed to initialize platform client", exc_info=True)
            return []

        try:
            try:
                resp = client.request(
                    "GET",
                    f"/app/{org}/api/settings/integrations",
                    headers={"Accept": "application/json"},
                )
            except AuthRequiredError:
                logger.debug("Not authenticated for backend query")
                return []

            if resp.status_code in (307, 401, 403):
                logger.info(
                    "Backend integration query returned HTTP %d for org '%s'. "
                    "Your token may lack org scope — this can happen when the "
                    "Auth0 organization isn't linked. Backend integrations will "
                    "be unavailable until this is resolved.",
                    resp.status_code,
                    org,
                )
                return []
            if resp.status_code != 200:
                logger.debug("Backend returned HTTP %d", resp.status_code)
                return []

            data = resp.json()
            # API returns {"integrations": [...]} or a bare list
            integrations = data.get("integrations", data) if isinstance(data, dict) else data
            results = []
            for entry in integrations:
                provider = entry.get("provider", "")
                if provider not in SUPPORTED_PROVIDERS:
                    continue
                status = entry.get("status", "active")
                mapped_status: ConnectionStatus = (
                    "needs_reauth"
                    if status == "needs_reauth"
                    else "error"
                    if status == "error"
                    else "connected"
                )
                details_parts = []
                raw_meta = entry.get("provider_metadata", {}) or {}
                # provider_metadata may be a JSON string from the DB
                if isinstance(raw_meta, str):
                    import json as _json

                    try:
                        meta = _json.loads(raw_meta)
                    except (ValueError, TypeError):
                        meta = {}
                else:
                    meta = raw_meta
                if provider == "jira":
                    site = meta.get("site_url") or meta.get("site_name", "")
                    if site:
                        details_parts.append(site)
                    details_parts.append("OAuth")
                elif provider == "linear":
                    ws = meta.get("workspace_name", "")
                    if ws:
                        details_parts.append(f"{ws} workspace")
                    details_parts.append("OAuth")
                elif provider == "github":
                    repo = meta.get("default_repo", "")
                    owner = meta.get("default_owner", "")
                    if owner and repo:
                        details_parts.append(f"{owner}/{repo}")

                results.append(
                    IntegrationInfo(
                        provider=provider,
                        source="backend",
                        status=mapped_status,
                        details=" ".join(details_parts),
                        metadata=meta,
                    )
                )
            return results
        except Exception:
            logger.warning("Backend integration query failed", exc_info=True)
            return []
        finally:
            client.close()

    def _test_via_backend(self, provider: str, org: str) -> TestResult | None:
        """Test integration via backend API."""
        import time

        try:
            from ._platform import PlatformClient

            client = PlatformClient()
        except ImportError:
            return None
        except Exception:
            logger.debug("Platform client init failed for test", exc_info=True)
            return None

        try:
            start = time.monotonic()
            resp = client.post(f"/app/{org}/api/settings/integrations/{provider}/test")
            elapsed = (time.monotonic() - start) * 1000

            if resp.status_code == 404:
                return None  # Not configured on backend

            data = resp.json()
            return TestResult(
                provider=provider,
                ok=data.get("ok", False),
                message=data.get("message", ""),
                latency_ms=data.get("latency_ms", elapsed),
            )
        except Exception as e:
            logger.debug("Backend test failed for %s: %s", provider, e)
            return None
        finally:
            client.close()

    # ── CANON.yaml source ───────────────────────────────────

    def _from_canon_yaml(self) -> list[IntegrationInfo]:
        """Read integrations from CANON.yaml ticket_mapping config."""
        config_path = self._root / "CANON.yaml"
        if not config_path.exists():
            return []

        try:
            from canon.config.parse import parse_canon_yaml

            result = parse_canon_yaml(config_path.read_text())
            config = result.config
        except Exception:
            logger.debug("Failed to parse CANON.yaml", exc_info=True)
            return []

        results = []
        seen_providers: set[str] = set()

        # Check ticket_mapping.ticket_systems
        if config.ticket_mapping:
            for name, sys_config in config.ticket_mapping.ticket_systems.items():
                details_parts = []
                if sys_config.project:
                    details_parts.append(sys_config.project)
                if sys_config.auth_profile:
                    profile = config.ticket_mapping.auth_profiles.get(sys_config.auth_profile)
                    if profile:
                        details_parts.append(f"({profile.auth_method})")
                elif sys_config.system == "github":
                    details_parts.append("(GitHub App)")
                results.append(
                    IntegrationInfo(
                        provider=sys_config.system,
                        source="canon_yaml",
                        status="configured",
                        details=" ".join(details_parts),
                        metadata={
                            "auth_profile": sys_config.auth_profile or "",
                            "project": sys_config.project,
                            "system_name": name,
                        },
                    )
                )
                seen_providers.add(sys_config.system)

        # Check simple ticket_system field (e.g. ticket_system: github)
        # GitHub Issues uses the Canon GitHub App, not OAuth credentials,
        # so it won't appear in org_integrations or env vars.
        if config.ticket_system and config.ticket_system not in seen_providers:
            details = config.project_key or ""
            if config.ticket_system == "github" and details:
                details += " (GitHub App)"
            results.append(
                IntegrationInfo(
                    provider=config.ticket_system,
                    source="canon_yaml",
                    status="configured",
                    details=details,
                    metadata={"project_key": config.project_key or ""},
                )
            )

        return results

    # ── Environment variable source ─────────────────────────

    def _from_env_vars(self) -> list[IntegrationInfo]:
        """Detect integrations from environment variables."""
        results = []

        # Jira
        jira_host = os.environ.get("JIRA_HOST", "")
        jira_email = os.environ.get("JIRA_EMAIL", "")
        jira_token = os.environ.get("JIRA_API_TOKEN", "")
        if jira_host and jira_email and jira_token:
            results.append(
                IntegrationInfo(
                    provider="jira",
                    source="env_var",
                    status="configured",
                    details=f"{jira_host} (API token)",
                    metadata={"host": jira_host, "email": jira_email},
                )
            )

        # Linear
        linear_key = os.environ.get("LINEAR_API_KEY", "")
        if linear_key:
            results.append(
                IntegrationInfo(
                    provider="linear",
                    source="env_var",
                    status="configured",
                    details="API key",
                    metadata={},
                )
            )

        # GitHub
        gh_token = os.environ.get("GITHUB_TOKEN", "")
        gh_owner = os.environ.get("GITHUB_OWNER", "")
        gh_repo = os.environ.get("GITHUB_REPO", "")
        if gh_token:
            details_parts = []
            if gh_owner and gh_repo:
                details_parts.append(f"{gh_owner}/{gh_repo}")
            details_parts.append("token")
            results.append(
                IntegrationInfo(
                    provider="github",
                    source="env_var",
                    status="configured",
                    details=" ".join(details_parts),
                    metadata={"owner": gh_owner, "repo": gh_repo},
                )
            )

        return results

    # ── Local testing ───────────────────────────────────────

    def _test_locally(self, provider: str) -> TestResult:
        """Test by instantiating the adapter and making a lightweight API call."""
        import asyncio
        import time

        from canon.sync.adapters.factory import create_adapter

        # Read project key from CANON.yaml if available
        project_key = self._get_project_key()

        adapter = create_adapter(ticket_project=project_key, system=provider)
        if adapter is None:
            return TestResult(
                provider=provider,
                ok=False,
                message=f"No credentials configured for {provider}",
            )

        start = time.monotonic()
        try:
            # Use a lightweight call to verify credentials
            if provider == "jira":
                # JiraAdapter has validate_config
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(adapter.validate_config(project_key))  # type: ignore[attr-defined]
                finally:
                    loop.close()
            elif provider == "linear":
                # Search with empty pattern to verify auth
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(adapter.search_tickets("", ""))
                finally:
                    loop.close()
            elif provider == "github":
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(adapter.search_tickets(project_key, ""))
                finally:
                    loop.close()

            elapsed = (time.monotonic() - start) * 1000
            return TestResult(
                provider=provider,
                ok=True,
                message="Connection successful",
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return TestResult(
                provider=provider,
                ok=False,
                message=str(e),
                latency_ms=elapsed,
            )

    def _get_project_key(self) -> str:
        """Read project key from CANON.yaml or git remote."""
        config_path = self._root / "CANON.yaml"
        if config_path.exists():
            try:
                from canon.config.parse import parse_canon_yaml

                result = parse_canon_yaml(config_path.read_text())
                if result.config.project_key:
                    return result.config.project_key
            except Exception:
                logger.debug("Failed to read project_key from CANON.yaml", exc_info=True)

        # Fallback: detect from git remote
        try:
            from ._local import resolve_github_remote

            remote = resolve_github_remote(root=self._root)
            if remote:
                return f"{remote[0]}/{remote[1]}"
        except Exception:
            logger.debug("Failed to detect project from git remote", exc_info=True)

        return ""

    # ── CANON.yaml modification ─────────────────────────────

    def add_local_integration(
        self,
        provider: str,
        *,
        project_key: str = "",
        env_prefix: str = "",
        host_override: str = "",
    ) -> None:
        """Add or update a local integration in CANON.yaml.

        Uses line-level edits to preserve comments and formatting.
        """
        import re

        config_path = self._root / "CANON.yaml"
        raw = config_path.read_text() if config_path.exists() else ""

        # Update or insert ticket_system (lambda avoids backreference issues)
        if re.search(r"^ticket_system:", raw, re.MULTILINE):
            raw = re.sub(
                r"^ticket_system:.*$",
                lambda _: f"ticket_system: {provider}",
                raw,
                flags=re.MULTILINE,
            )
        else:
            raw = raw.rstrip("\n") + f"\nticket_system: {provider}\n"

        # Update or insert project_key if provided
        if project_key:
            if re.search(r"^project_key:", raw, re.MULTILINE):
                raw = re.sub(
                    r"^project_key:.*$",
                    lambda _: f"project_key: {project_key}",
                    raw,
                    flags=re.MULTILINE,
                )
            else:
                raw = raw.rstrip("\n") + f"\nproject_key: {project_key}\n"

        # Persist Jira host override so canon sync can find it
        if host_override:
            if re.search(r"^jira_host:", raw, re.MULTILINE):
                raw = re.sub(
                    r"^jira_host:.*$",
                    lambda _: f"jira_host: {host_override}",
                    raw,
                    flags=re.MULTILINE,
                )
            else:
                raw = raw.rstrip("\n") + f"\njira_host: {host_override}\n"

        config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = config_path.with_suffix(".yaml.tmp")
        tmp.write_text(raw)
        tmp.replace(config_path)

    def remove_local_integration(self, provider: str) -> bool:
        """Remove integration config from CANON.yaml.

        Uses line-level edits to preserve comments and formatting.
        Returns True if something was removed.
        """
        import re

        config_path = self._root / "CANON.yaml"
        if not config_path.exists():
            return False

        raw = config_path.read_text()
        changed = False

        # Remove ticket_system line if it matches this provider
        new_raw, count = re.subn(
            rf"^ticket_system:\s*{re.escape(provider)}\s*$\n?",
            "",
            raw,
            flags=re.MULTILINE,
        )
        if count > 0:
            raw = new_raw
            changed = True

        if changed:
            tmp = config_path.with_suffix(".yaml.tmp")
            tmp.write_text(raw)
            tmp.replace(config_path)

        return changed
