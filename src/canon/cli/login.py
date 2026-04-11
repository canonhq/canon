"""``canon login`` — authenticate with the Canon platform."""

from __future__ import annotations

import contextlib
import sys
import time
import webbrowser
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from ._platform import PlatformClient


def register(subparsers) -> None:
    p = subparsers.add_parser("login", help="Authenticate with the Canon platform")
    p.add_argument("--api-key", default="", help="Authenticate with an API key instead of OAuth")
    p.add_argument(
        "--server",
        default="",
        help="Platform URL (default: $CANON_URL or https://canonhq.co)",
    )
    p.add_argument(
        "--org",
        default="",
        help=(
            "Target organization slug (e.g. 'canonhq'). Used to scope the "
            "device-flow token to a specific Auth0 Organization. If omitted, "
            "auto-detected from the current git remote when run inside a repo."
        ),
    )


def run_login(*, api_key: str = "", server: str = "", org: str = "") -> None:
    from ._platform import PlatformClient

    base_url = server or None
    client = PlatformClient(base_url=base_url)

    if api_key:
        _login_api_key(client, api_key)
    else:
        resolved_org = org or _detect_org_from_git()
        _login_device(client, org=resolved_org)

    client.close()


def _detect_org_from_git() -> str:
    """Best-effort: derive a Canon org slug from the current repo's GitHub remote.

    Canon uses the GitHub owner login as its ``org_login`` (see
    ``Installation.org_login``), so the GitHub owner can be used directly as
    the ``--org`` hint. Returns "" when the CLI isn't running inside a git
    repo, when ``origin`` is missing, or when the URL isn't a recognizable
    GitHub remote. On success, prints a message so the user can see which
    org was auto-selected and override with ``--org`` if needed.

    Note: auto-detect degrades gracefully only in single-org deployments. In
    a multi-org deployment the backend cannot fall back when the hint is
    missing, so users should prefer passing ``--org`` explicitly.
    """
    from pathlib import Path

    from ._local import resolve_github_remote

    try:
        remote = resolve_github_remote(root=Path.cwd())
    except FileNotFoundError:
        # cwd was deleted or inaccessible — treat as "not in a repo".
        return ""
    if not remote:
        return ""
    owner, _repo = remote
    print(f"Detected organization from git remote: {owner} (override with --org)")
    return owner


def _login_api_key(client: PlatformClient, api_key: str) -> None:
    """Validate an API key against the platform and save credentials."""
    from ._credentials import save_credentials

    # Validate by hitting a lightweight authenticated endpoint
    resp = client.raw_get(
        "/app/api/me",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if resp.status_code != 200:
        print(f"Error: API key validation failed (HTTP {resp.status_code})")
        sys.exit(1)

    data = resp.json()
    save_credentials(
        {
            "method": "api_key",
            "api_key": api_key,
            "org": data.get("org", ""),
        }
    )
    print(f"Logged in with API key (org: {data.get('org', 'unknown')})")


def _login_device(client: PlatformClient, *, org: str = "") -> None:
    """Run the device authorization flow.

    When *org* is non-empty, the server resolves it to an Auth0 Organization
    id and scopes the device code to that org — so the resulting access token
    carries an ``org_id`` claim. Without it, backend tenant resolution falls
    back to the single-org heuristic, which breaks for multi-org deployments.
    """
    from ._credentials import save_credentials

    # 1. Request device code
    resp = client.raw_post("/auth/device/code", json={"org": org} if org else {})
    if resp.status_code != 200:
        print(f"Error: Could not start device auth (HTTP {resp.status_code})")
        sys.exit(1)

    data = resp.json()
    user_code = data["user_code"]
    verification_uri = data.get("verification_uri_complete") or data.get("verification_uri", "")
    device_code = data["device_code"]
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 900)

    # 2. Display URL + code and try to open browser
    print(f"\nOpen this URL in your browser:\n  {verification_uri}\n")
    print(f"Enter code: {user_code}\n")
    # Only auto-open real http(s) URLs. A bogus value (empty, relative, or
    # malformed) causes Python's webbrowser to fall back from remote_args to
    # args, spawning two tabs against whatever garbage was passed in.
    parsed = urlparse(verification_uri)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        with contextlib.suppress(Exception):
            webbrowser.open(verification_uri)

    print("Waiting for authorization...", end="", flush=True)

    # 3. Poll for token
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        resp = client.raw_post("/auth/device/token", json={"device_code": device_code})
        if resp.status_code not in (200, 403):
            print(f"\nError: Unexpected response (HTTP {resp.status_code})")
            sys.exit(1)

        result = resp.json()
        status = result.get("status", "")

        if status == "approved":
            save_credentials(
                {
                    "method": "oauth",
                    "access_token": result["access_token"],
                    "refresh_token": result.get("refresh_token", ""),
                    "expires_at": time.time() + result.get("expires_in", 86400),
                    "org": result.get("org", ""),
                    "email": result.get("email", ""),
                }
            )
            print(f"\nLogged in as {result.get('email', 'unknown')}")
            if result.get("org"):
                print(f"Organization: {result['org']}")
            return

        if status == "expired":
            print("\nDevice code expired. Please try again.")
            sys.exit(1)

        if status == "denied":
            print("\nAuthorization denied.")
            sys.exit(1)

        if status == "slow_down":
            interval += 5

        # pending — keep polling
        print(".", end="", flush=True)

    print("\nTimed out waiting for authorization.")
    sys.exit(1)
