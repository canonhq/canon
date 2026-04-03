"""Tests for GitHub org membership lookup."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx

from canon.auth.github_membership import fetch_github_user_orgs, resolve_org_from_github


class TestFetchGithubUserOrgs:
    async def test_empty_token_returns_empty(self):
        assert await fetch_github_user_orgs("") == []

    async def test_valid_response_returns_lowercase_logins(self, respx_mock):
        respx_mock.get("https://api.github.com/user/orgs").mock(
            return_value=httpx.Response(200, json=[{"login": "MyOrg"}, {"login": "OtherOrg"}])
        )
        result = await fetch_github_user_orgs("ghp_test")
        assert result == ["myorg", "otherorg"]

    async def test_non_200_returns_empty(self, respx_mock):
        respx_mock.get("https://api.github.com/user/orgs").mock(
            return_value=httpx.Response(401, json={"message": "Bad credentials"})
        )
        assert await fetch_github_user_orgs("ghp_bad") == []

    async def test_network_error_returns_empty(self, respx_mock):
        respx_mock.get("https://api.github.com/user/orgs").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        assert await fetch_github_user_orgs("ghp_test") == []

    async def test_malformed_entries_filtered(self, respx_mock):
        respx_mock.get("https://api.github.com/user/orgs").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"login": "GoodOrg"},
                    {"no_login_key": True},  # missing login
                    "not-a-dict",  # wrong type
                    {"login": ""},  # empty login filtered by falsy check
                ],
            )
        )
        result = await fetch_github_user_orgs("ghp_test")
        assert result == ["goodorg"]


class TestResolveOrgFromGithub:
    async def test_no_token_returns_empty(self):
        assert await resolve_org_from_github("", AsyncMock()) == []

    async def test_no_registry_returns_empty(self):
        assert await resolve_org_from_github("ghp_test", None) == []

    async def test_cross_references_correctly(self, respx_mock):
        respx_mock.get("https://api.github.com/user/orgs").mock(
            return_value=httpx.Response(200, json=[{"login": "MyOrg"}, {"login": "UninstalledOrg"}])
        )
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(return_value=["myorg", "other-installed"])

        result = await resolve_org_from_github("ghp_test", registry)
        assert result == ["myorg"]

    async def test_case_insensitive_matching(self, respx_mock):
        respx_mock.get("https://api.github.com/user/orgs").mock(
            return_value=httpx.Response(200, json=[{"login": "MYORG"}])
        )
        registry = AsyncMock()
        # Registry stores the canonical casing
        registry.list_orgs = AsyncMock(return_value=["MyOrg"])

        result = await resolve_org_from_github("ghp_test", registry)
        # Should return the registry's casing, not GitHub's
        assert result == ["MyOrg"]

    async def test_no_overlap_returns_empty(self, respx_mock):
        respx_mock.get("https://api.github.com/user/orgs").mock(
            return_value=httpx.Response(200, json=[{"login": "uninstalled"}])
        )
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(return_value=["installed-org"])

        assert await resolve_org_from_github("ghp_test", registry) == []

    async def test_registry_error_returns_empty(self, respx_mock):
        respx_mock.get("https://api.github.com/user/orgs").mock(
            return_value=httpx.Response(200, json=[{"login": "myorg"}])
        )
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(side_effect=Exception("DB error"))

        assert await resolve_org_from_github("ghp_test", registry) == []

    async def test_multiple_matches(self, respx_mock):
        respx_mock.get("https://api.github.com/user/orgs").mock(
            return_value=httpx.Response(
                200, json=[{"login": "org-a"}, {"login": "org-b"}, {"login": "org-c"}]
            )
        )
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(return_value=["org-a", "org-b", "other"])

        result = await resolve_org_from_github("ghp_test", registry)
        assert result == ["org-a", "org-b"]
