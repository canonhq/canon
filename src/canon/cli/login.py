"""``canon login`` — authenticate with the Canon platform."""

from __future__ import annotations

import contextlib
import sys
import time
import webbrowser
from typing import TYPE_CHECKING

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


def run_login(*, api_key: str = "", server: str = "") -> None:
    from ._platform import PlatformClient

    base_url = server or None
    client = PlatformClient(base_url=base_url)

    if api_key:
        _login_api_key(client, api_key)
    else:
        _login_device(client)

    client.close()


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


def _login_device(client: PlatformClient) -> None:
    """Run the device authorization flow."""
    from ._credentials import save_credentials

    # 1. Request device code
    resp = client.raw_post("/auth/device/code", json={})
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
