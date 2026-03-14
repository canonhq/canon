"""Local credential storage for the Canon CLI.

Credentials are persisted at ``~/.config/canon/credentials.json``
with file permissions restricted to the current user (0600).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

_NEW_CONFIG_DIR = Path.home() / ".config" / "canon"
_OLD_CONFIG_DIR = Path.home() / ".config" / "specwright"
_NEW_CRED_FILE = _NEW_CONFIG_DIR / "credentials.json"
_OLD_CRED_FILE = _OLD_CONFIG_DIR / "credentials.json"


def _get_cred_file() -> Path:
    """Return the credential file path, migrating from legacy location if needed."""
    if _NEW_CRED_FILE.exists():
        return _NEW_CRED_FILE
    if _OLD_CRED_FILE.exists():
        import warnings

        warnings.warn(
            "Credentials at ~/.config/specwright/ are deprecated. "
            "Run `canon login` to migrate to ~/.config/canon/.",
            DeprecationWarning,
            stacklevel=3,
        )
        return _OLD_CRED_FILE
    return _NEW_CRED_FILE


def load_credentials() -> dict | None:
    """Load saved credentials, or return None if absent / malformed."""
    try:
        return json.loads(_get_cred_file().read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save_credentials(cred: dict) -> None:
    """Persist a credential dict to disk (chmod 0600)."""
    _NEW_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _NEW_CRED_FILE.write_text(json.dumps(cred, indent=2))
    os.chmod(_NEW_CRED_FILE, 0o600)


def clear_credentials() -> None:
    """Remove the credential file if it exists."""
    _NEW_CRED_FILE.unlink(missing_ok=True)
    _OLD_CRED_FILE.unlink(missing_ok=True)


def is_token_expired(cred: dict) -> bool:
    """Check whether the access token in *cred* has expired.

    Returns True if ``expires_at`` is in the past (with a 30-second buffer)
    or if the field is missing.
    """
    expires_at = cred.get("expires_at")
    if expires_at is None:
        return True
    return time.time() >= (expires_at - 30)
