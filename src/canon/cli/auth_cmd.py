"""``canon auth status`` — display current authentication state."""

from __future__ import annotations

import time


def register(subparsers) -> None:
    auth_parser = subparsers.add_parser("auth", help="Authentication utilities")
    auth_sub = auth_parser.add_subparsers(dest="auth_command")
    auth_sub.add_parser("status", help="Show current authentication status")


def run_auth_status() -> None:
    from ._credentials import load_credentials

    cred = load_credentials()
    if cred is None:
        print("Not logged in. Run `canon login` to authenticate.")
        return

    method = cred.get("method", "unknown")
    print(f"Auth method: {method}")

    if org := cred.get("org"):
        print(f"Organization: {org}")

    if email := cred.get("email"):
        print(f"Email:        {email}")

    if method == "oauth":
        expires_at = cred.get("expires_at")
        if expires_at:
            remaining = int(expires_at - time.time())
            if remaining > 0:
                mins, _secs = divmod(remaining, 60)
                hours, mins = divmod(mins, 60)
                print(f"Token:        valid ({hours}h {mins}m remaining)")
            else:
                has_refresh = bool(cred.get("refresh_token"))
                print(
                    f"Token:        expired (refresh {'available' if has_refresh else 'unavailable'})"
                )
        else:
            print("Token:        unknown expiry")

    elif method == "api_key":
        # Mask the key, showing only prefix + last 4
        key = cred.get("api_key", "")
        if len(key) > 8:
            print(f"API key:      {key[:3]}...{key[-4:]}")
        else:
            print("API key:      (set)")
