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
        "--token",
        default="",
        help=(
            "Non-interactive: store the given token without round-tripping "
            "the platform. Intended for CI environments where the Canon "
            "backend may not be reachable at login time. Use --api-key "
            "instead when you want immediate validation."
        ),
    )
    p.add_argument(
        "--api-url",
        default="",
        help=(
            "Canon backend URL to record alongside the credential. "
            "Defaults to the platform URL configured by --server or "
            "https://api.canonhq.co. Used by the audit routing switch."
        ),
    )
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


def run_login(
    *,
    api_key: str = "",
    token: str = "",
    api_url: str = "",
    server: str = "",
    org: str = "",
) -> None:
    if token:
        # Non-interactive token storage path — used by CI environments where
        # we want a credential on disk without contacting the backend.
        _login_token(token=token, api_url=api_url, server=server, org=org)
        return

    from ._platform import PlatformClient

    base_url = server or None
    client = PlatformClient(base_url=base_url)

    if api_key:
        _login_api_key(client, api_key)
    else:
        resolved_org = org or _detect_org()
        _login_device(client, org=resolved_org)

    client.close()


def _login_token(*, token: str, api_url: str, server: str, org: str) -> None:
    """Store a token non-interactively without validating against the backend.

    The audit routing switch reads the saved credential and uses it to
    POST to ``${api_url}/v1/actions/audit``. The token is treated as
    opaque — validation happens on the first real call.
    """
    from ._credentials import save_credentials

    resolved_url = api_url or server or "https://api.canonhq.co"
    save_credentials(
        {
            "method": "token",
            "token": token,
            "api_url": resolved_url,
            "org": org,
        }
    )
    print(f"Stored token credential (api_url: {resolved_url})")


def _detect_org() -> str:
    """Detect the Canon org from CANON.yaml, git remote, or interactive prompt.

    Resolution order:
    1. CANON.yaml ``team`` field (most explicit)
    2. Git remote owner (GitHub owner = Canon org)
    3. Interactive prompt (if stdin is a TTY)

    Returns "" if detection fails and no interactive prompt is possible.
    """
    import re
    from pathlib import Path

    slug_re = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
    root = Path.cwd()

    # 1. CANON.yaml team field
    config_path = root / "CANON.yaml"
    if config_path.exists():
        try:
            from canon.config.parse import parse_canon_yaml

            result = parse_canon_yaml(config_path.read_text())
            if result.config.team and slug_re.match(result.config.team):
                print(f"Detected organization from CANON.yaml: {result.config.team}")
                return result.config.team
        except Exception:
            pass

    # 2. Git remote
    from ._local import resolve_github_remote

    try:
        remote = resolve_github_remote(root=root)
    except FileNotFoundError:
        remote = None
    if remote:
        owner, _repo = remote
        if slug_re.match(owner):
            print(f"Detected organization from git remote: {owner}")
            return owner

    # 3. Interactive prompt
    if sys.stdin.isatty():
        org = input("Organization slug (e.g. canonhq): ").strip()
        if org and slug_re.match(org):
            return org

    return ""


def _detect_org_from_git() -> str:
    """Legacy alias — prefer _detect_org()."""
    return _detect_org()


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
            # Only trust org from the backend response — don't persist the
            # locally-detected hint, as the user may not actually be linked
            # to that org. _get_org() handles fallback at call time.
            resolved_org = result.get("org", "")
            save_credentials(
                {
                    "method": "oauth",
                    "access_token": result["access_token"],
                    "refresh_token": result.get("refresh_token", ""),
                    "expires_at": time.time() + result.get("expires_in", 86400),
                    "org": resolved_org,
                    "email": result.get("email", ""),
                }
            )
            print(f"\nLogged in as {result.get('email', 'unknown')}")
            if resolved_org:
                print(f"Organization: {resolved_org}")
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
