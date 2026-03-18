"""Tests for get_claude_client_for_org BYOK routing logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from canon.agent.client import (
    AgentUnavailableError,
    ClaudeClient,
    get_claude_client_for_org,
)
from canon.billing.models import (
    BillingCycle,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from canon.billing.service import BillingService


def _make_subscription(plan: Plan = Plan.PRO, **overrides) -> Subscription:
    defaults = dict(
        id="1",
        org_login="test-org",
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_456",
        plan=plan,
        billing_cycle=BillingCycle.MONTHLY,
        status=SubscriptionStatus.ACTIVE,
    )
    defaults.update(overrides)
    return Subscription(**defaults)


def _mock_billing_service() -> BillingService:
    """Create a mock that passes isinstance(obj, BillingService) checks."""
    mock = AsyncMock(spec=BillingService)
    return mock


class TestGetClaudeClientForOrg:
    async def test_no_billing_service_returns_default(self):
        default = ClaudeClient(api_key="default-key")
        result = await get_claude_client_for_org("org-1", default, billing_service=None)
        assert result is default

    async def test_non_billing_service_instance_returns_default(self):
        """If billing_service is not a BillingService instance, return default."""
        default = ClaudeClient(api_key="default-key")
        result = await get_claude_client_for_org("org-1", default, billing_service="not-a-service")
        assert result is default

    async def test_no_subscription_returns_default(self):
        """Org with no subscription (e.g. self-hosted) should use default."""
        default = ClaudeClient(api_key="default-key")
        mock_billing = _mock_billing_service()
        mock_billing.get_subscription = AsyncMock(return_value=None)

        result = await get_claude_client_for_org("org-1", default, billing_service=mock_billing)
        assert result is default

    async def test_pro_plan_returns_default(self):
        """Pro plan orgs should use Canon's default API key."""
        default = ClaudeClient(api_key="default-key")
        sub = _make_subscription(plan=Plan.PRO)
        mock_billing = _mock_billing_service()
        mock_billing.get_subscription = AsyncMock(return_value=sub)

        result = await get_claude_client_for_org("org-1", default, billing_service=mock_billing)
        assert result is default

    async def test_enterprise_plan_returns_default(self):
        """Enterprise plan orgs should use Canon's default API key."""
        default = ClaudeClient(api_key="default-key")
        sub = _make_subscription(plan=Plan.ENTERPRISE)
        mock_billing = _mock_billing_service()
        mock_billing.get_subscription = AsyncMock(return_value=sub)

        result = await get_claude_client_for_org("org-1", default, billing_service=mock_billing)
        assert result is default

    async def test_starter_plan_with_byok_key_returns_byok_client(self):
        """Starter plan with a BYOK key should return a client using that key."""
        default = ClaudeClient(api_key="default-key")
        sub = _make_subscription(plan=Plan.STARTER)
        mock_billing = _mock_billing_service()
        mock_billing.get_subscription = AsyncMock(return_value=sub)
        mock_billing.get_anthropic_key = AsyncMock(return_value="sk-byok-key-12345")

        result = await get_claude_client_for_org("org-1", default, billing_service=mock_billing)

        assert result is not default
        assert result.api_key == "sk-byok-key-12345"
        assert result.is_available

    async def test_starter_plan_without_byok_key_raises(self):
        """Starter plan without a BYOK key should raise AgentUnavailableError."""
        default = ClaudeClient(api_key="default-key")
        sub = _make_subscription(plan=Plan.STARTER)
        mock_billing = _mock_billing_service()
        mock_billing.get_subscription = AsyncMock(return_value=sub)
        mock_billing.get_anthropic_key = AsyncMock(return_value=None)

        with pytest.raises(AgentUnavailableError):
            await get_claude_client_for_org("org-1", default, billing_service=mock_billing)

    async def test_starter_plan_with_empty_string_byok_key_raises(self):
        """BYOK key returning empty string should raise AgentUnavailableError."""
        default = ClaudeClient(api_key="default-key")
        sub = _make_subscription(plan=Plan.STARTER)
        mock_billing = _mock_billing_service()
        mock_billing.get_subscription = AsyncMock(return_value=sub)
        mock_billing.get_anthropic_key = AsyncMock(return_value="")

        with pytest.raises(AgentUnavailableError):
            await get_claude_client_for_org("org-1", default, billing_service=mock_billing)

    async def test_unexpected_error_raises_unavailable(self):
        """Unexpected errors should raise AgentUnavailableError (not silently fall back)."""
        default = ClaudeClient(api_key="default-key")
        mock_billing = _mock_billing_service()
        mock_billing.get_subscription = AsyncMock(side_effect=RuntimeError("db connection failed"))

        with pytest.raises(AgentUnavailableError):
            await get_claude_client_for_org("org-1", default, billing_service=mock_billing)

    async def test_import_error_returns_default(self):
        """If BillingService import fails, fall back to default client."""
        default = ClaudeClient(api_key="default-key")

        # Patch the import inside the function to raise ImportError
        with patch.dict("sys.modules", {"canon.billing.service": None}):
            # Passing a non-None billing_service that will trigger the import
            result = await get_claude_client_for_org(
                "org-1", default, billing_service="some-object"
            )
        # The import fails, so isinstance can't be checked, causing ImportError
        # which is caught and returns default
        assert result is default

    async def test_for_api_key_returns_new_client(self):
        """Verify ClaudeClient.for_api_key creates a new independent client."""
        original = ClaudeClient(api_key="original-key")
        byok = original.for_api_key("byok-key-12345")
        assert byok is not original
        assert byok.api_key == "byok-key-12345"
        assert original.api_key == "original-key"
        assert byok.is_available

    async def test_get_subscription_called_with_correct_org(self):
        """Verify get_subscription is called with the right org_login."""
        default = ClaudeClient(api_key="default-key")
        mock_billing = _mock_billing_service()
        mock_billing.get_subscription = AsyncMock(return_value=None)

        await get_claude_client_for_org("my-org", default, billing_service=mock_billing)
        mock_billing.get_subscription.assert_awaited_once_with("my-org")

    async def test_starter_get_anthropic_key_called_with_correct_org(self):
        """Verify get_anthropic_key is called with the right org_login for starter plans."""
        default = ClaudeClient(api_key="default-key")
        sub = _make_subscription(plan=Plan.STARTER)
        mock_billing = _mock_billing_service()
        mock_billing.get_subscription = AsyncMock(return_value=sub)
        mock_billing.get_anthropic_key = AsyncMock(return_value="sk-byok-key")

        await get_claude_client_for_org("my-org", default, billing_service=mock_billing)
        mock_billing.get_anthropic_key.assert_awaited_once_with("my-org")
