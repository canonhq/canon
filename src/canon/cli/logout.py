"""``canon logout`` — clear local credentials and revoke server-side session."""

from __future__ import annotations


def register(subparsers) -> None:
    subparsers.add_parser("logout", help="Log out and revoke session")


def run_logout() -> None:
    from ._credentials import clear_credentials, load_credentials

    cred = load_credentials()

    # Best-effort server-side session revocation
    if cred and cred.get("method") == "oauth" and cred.get("refresh_token"):
        try:
            from ._platform import PlatformClient

            client = PlatformClient()
            client.post("/auth/revoke", json={"refresh_token": cred["refresh_token"]})
            client.close()
        except Exception:
            pass  # Best-effort — still clear local credentials

    clear_credentials()
    print("Logged out.")
