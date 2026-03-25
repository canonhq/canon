"""Tests for analytics API endpoints."""

from __future__ import annotations

import pytest

from canon.web.analytics_routes import (
    _query_feature_usage,
    _query_freshness,
    _query_health,
    _query_momentum,
    _query_time_to_ship,
    _sanitize,
)


class _MockQueryClient:
    configured = True

    async def query(self, hogql: str) -> list[dict]:
        return []


class TestSanitize:
    def test_valid_org(self):
        assert _sanitize("my-org") == "my-org"

    def test_valid_org_with_slash(self):
        assert _sanitize("my-org/repo") == "my-org/repo"

    def test_valid_alphanumeric(self):
        assert _sanitize("Org_123") == "Org_123"

    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError):
            _sanitize("'; DROP TABLE events; --")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _sanitize("")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError):
            _sanitize("my org")


class TestQueryFunctions:
    @pytest.mark.asyncio
    async def test_query_health_empty_data(self):
        result = await _query_health(_MockQueryClient(), "testorg", "", 30)
        assert "score" in result and "pillars" in result and "trend" in result
        # Verify pillars are PillarData objects
        for key in ("momentum", "freshness", "time_to_ship"):
            pillar = result["pillars"][key]
            assert "score" in pillar
            assert "summary" in pillar

    @pytest.mark.asyncio
    async def test_query_health_trend_shape(self):
        result = await _query_health(_MockQueryClient(), "testorg", "", 30)
        # Trend items should have "date" and "score" keys
        for item in result["trend"]:
            assert "date" in item
            assert "score" in item

    @pytest.mark.asyncio
    async def test_query_momentum_empty_data(self):
        result = await _query_momentum(_MockQueryClient(), "testorg", "", 30)
        assert "weekly_activity" in result and "top_repos" in result
        assert "top_contributors" in result

    @pytest.mark.asyncio
    async def test_query_freshness_empty_data(self):
        result = await _query_freshness(_MockQueryClient(), "testorg", "", 30)
        assert "specs" in result and "summary" in result
        summary = result["summary"]
        assert "fresh_count" in summary
        assert "stale_count" in summary
        assert "avg_gap_days" in summary

    @pytest.mark.asyncio
    async def test_query_time_to_ship_empty_data(self):
        result = await _query_time_to_ship(_MockQueryClient(), "testorg", "", 30)
        assert "stages" in result
        assert "total_cycle_days" in result
        assert "improvement_pct" in result

    @pytest.mark.asyncio
    async def test_query_feature_usage_empty_data(self):
        result = await _query_feature_usage(_MockQueryClient(), "testorg", "", 0)
        assert "features" in result
        assert "repos_with_config" in result
        assert "repos_without_config" in result
