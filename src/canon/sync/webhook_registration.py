"""Auto-register webhooks with ticket providers after OAuth connection.

Called from OAuth callbacks to set up reverse sync without manual configuration.
Stores webhook IDs in provider_metadata for cleanup on disconnect.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def register_jira_webhook(
    *,
    cloud_id: str,
    access_token: str,
    base_url: str,
) -> dict:
    """Register a Jira webhook for issue updates.

    Uses Jira's dynamic webhook registration API. Returns dict with webhook_id
    on success. Webhook signature verification uses settings.jira_webhook_secret
    (env var), not a per-registration secret — Jira's dynamic webhook API does
    not support client-provided signing secrets.
    """
    callback_url = f"{base_url}/webhooks/jira"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/webhook",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "webhooks": [
                    {
                        "url": callback_url,
                        "events": ["jira:issue_updated"],
                        "jqlFilter": "",  # all issues
                    }
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    # Jira returns a list of created webhooks
    created = data.get("webhookRegistrationResult", [])
    if created:
        webhook_id = str(created[0].get("createdWebhookId", ""))
        logger.info("Registered Jira webhook %s for cloud %s", webhook_id, cloud_id)
        return {"webhook_id": webhook_id}

    logger.warning("Jira webhook registration returned no results: %s", data)
    return {}


async def deregister_jira_webhook(
    *,
    cloud_id: str,
    access_token: str,
    webhook_id: str,
) -> bool:
    """Deregister a Jira webhook by ID."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(
                f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/webhook",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"webhookIds": [int(webhook_id)]},
            )
            resp.raise_for_status()
        logger.info("Deregistered Jira webhook %s", webhook_id)
        return True
    except Exception:
        logger.warning("Failed to deregister Jira webhook %s", webhook_id, exc_info=True)
        return False


async def register_linear_webhook(
    *,
    access_token: str,
    base_url: str,
) -> dict:
    """Register a Linear webhook for issue updates.

    Uses Linear's GraphQL API. Linear generates the signing secret.
    Returns dict with webhook_id on success.
    """
    callback_url = f"{base_url}/webhooks/linear"
    label = "Canon reverse sync"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.linear.app/graphql",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "query": """
                    mutation($input: WebhookCreateInput!) {
                        webhookCreate(input: $input) {
                            success
                            webhook { id enabled secret }
                        }
                    }
                """,
                "variables": {
                    "input": {
                        "url": callback_url,
                        "label": label,
                        "resourceTypes": ["Issue", "Comment", "IssueLabel"],
                        "enabled": True,
                        "allPublicTeams": True,
                    }
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()

    webhook_data = data.get("data", {}).get("webhookCreate", {})
    if webhook_data.get("success"):
        webhook = webhook_data.get("webhook", {})
        webhook_id = webhook.get("id", "")
        webhook_secret = webhook.get("secret", "")
        logger.info("Registered Linear webhook %s", webhook_id)
        return {"webhook_id": webhook_id, "webhook_secret": webhook_secret}

    errors = data.get("errors", [])
    logger.warning("Linear webhook registration failed: %s", errors)
    return {}


async def deregister_linear_webhook(
    *,
    access_token: str,
    webhook_id: str,
) -> bool:
    """Deregister a Linear webhook by ID."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.linear.app/graphql",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": """
                        mutation($id: String!) {
                            webhookDelete(id: $id) { success }
                        }
                    """,
                    "variables": {"id": webhook_id},
                },
            )
            resp.raise_for_status()
        logger.info("Deregistered Linear webhook %s", webhook_id)
        return True
    except Exception:
        logger.warning("Failed to deregister Linear webhook %s", webhook_id, exc_info=True)
        return False
