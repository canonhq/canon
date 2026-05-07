"""Slack OAuth install flow for multi-workspace support."""

from __future__ import annotations

import base64
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)


def _derive_fernet_key(byok_key: str) -> bytes:
    """Derive a Fernet-compatible key from the BYOK encryption key.

    Uses HKDF (RFC 5869) with a domain-separation label to derive a
    consistent 32-byte key, then base64-encodes it for Fernet compatibility.
    """
    hkdf = HKDF(algorithm=SHA256(), length=32, salt=None, info=b"canon-slack-token-encryption")
    return base64.urlsafe_b64encode(hkdf.derive(byok_key.encode()))


def is_self_hosted_mode(bot_token: str, app_token: str) -> bool:
    """Check if running in self-hosted (single workspace) mode.

    Self-hosted mode uses manual SLACK_BOT_TOKEN configuration
    without OAuth. Returns True when bot_token is set directly.
    """
    return True  # For now, all deployments are self-hosted


class SlackInstallStore:
    """Store and retrieve Slack installations from the DB.

    Bot tokens are encrypted at rest using BYOK encryption (Fernet).
    Used by managed cloud (multi-tenant) deployments.
    """

    def __init__(self, registry: Any, encryption_key: str) -> None:
        self._registry = registry
        self._encryption_key = encryption_key
        self._fernet = Fernet(_derive_fernet_key(encryption_key))

    async def async_save(self, installation: Any) -> None:
        """Save a Slack installation (from OAuth callback).

        Stores the bot token encrypted, links the workspace to a Canon org.
        """
        team_id = installation.team_id
        bot_token = installation.bot_token
        org_id = getattr(installation, "org_id", None) or ""

        # Encrypt bot token before storage
        encrypted_token = self._encrypt(bot_token)

        await self._registry.save_slack_installation(
            {
                "team_id": team_id,
                "bot_token": encrypted_token,
                "enterprise_id": getattr(installation, "enterprise_id", None),
                "org_id": org_id,
            }
        )
        logger.info("Saved Slack installation for team %s (org=%s)", team_id, org_id)

    async def async_find_installation(
        self,
        enterprise_id: str | None = None,
        team_id: str | None = None,
        **kwargs: Any,
    ) -> Any | None:
        """Find a Slack installation by team ID."""
        if not team_id:
            return None

        record = await self._registry.get_slack_installation(team_id)
        if record is None:
            return None

        # Decrypt bot token — return None on key rotation / corruption
        try:
            record["bot_token"] = self._decrypt(record["bot_token"])
        except InvalidToken:
            logger.warning("Failed to decrypt bot token for team %s (key rotation?)", team_id)
            return None
        return record

    async def get_org_for_workspace(self, team_id: str) -> str | None:
        """Get the Canon org linked to a Slack workspace."""
        record = await self._registry.get_slack_installation(team_id)
        if record is None:
            return None
        return record.get("org_id")

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a string using Fernet with the BYOK-derived key."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt a string using Fernet with the BYOK-derived key."""
        return self._fernet.decrypt(ciphertext.encode()).decode()


class SharedChannelGuard:
    """Controls whether the bot responds in Slack Connect shared channels.

    Ensures responses are scoped to the requesting org's data only.
    """

    def __init__(self, allow_shared_channels: bool = False) -> None:
        self._allow = allow_shared_channels

    def should_respond(self, event: dict) -> bool:
        """Check if the bot should respond in this channel.

        Returns False for shared channels when not explicitly allowed.
        """
        is_shared = event.get("is_ext_shared_channel", False)
        if is_shared and not self._allow:
            logger.debug("Skipping shared channel (allow_shared_channels=false)")
            return False
        return True

    def get_org_scope(self, event: dict, team_id: str) -> str:
        """Return the org ID to scope data queries to.

        In shared channels, ensures we only return data for the
        workspace that owns the bot installation — not cross-org data.
        """
        return team_id
