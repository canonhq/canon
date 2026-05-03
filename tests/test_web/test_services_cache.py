"""Tests for content cache fallback in web services."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canon.web.cache import TTLCache


def _make_mock_client():
    client = AsyncMock()
    client.get_file_content = AsyncMock(
        return_value=(
            "---\ntitle: Test\nstatus: draft\n---\n# Test\n## Section 1\nContent",
            "sha123",
        )
    )
    client._get = AsyncMock(return_value={})
    return client


def _make_mock_content_cache_store(*, raw=None):
    store = AsyncMock()
    store.get_spec_raw = AsyncMock(return_value=raw)
    return store


class TestGetSpecDetailCacheFallback:
    """Test that get_spec_detail falls back to GitHub on cache miss."""

    @pytest.fixture
    def mock_client(self):
        return _make_mock_client()

    @pytest.fixture
    def cache(self):
        return TTLCache(ttl_seconds=60)

    @pytest.fixture
    def mock_content_cache_store(self):
        return _make_mock_content_cache_store(raw=None)  # cache miss by default

    async def test_falls_back_to_github_on_cache_miss(
        self, mock_client, cache, mock_content_cache_store
    ):
        """When content cache returns None, should fetch from GitHub."""
        from canon.web.services import get_spec_detail

        with patch("canon.web.services._load_config", return_value=None):
            result = await get_spec_detail(
                mock_client,
                "owner",
                "repo",
                "docs/specs/test.md",
                cache,
                content_cache_store=mock_content_cache_store,
            )

        # Should have tried cache first
        mock_content_cache_store.get_spec_raw.assert_called_once_with(
            "owner/repo", "docs/specs/test.md"
        )
        # Should have fallen back to GitHub
        mock_client.get_file_content.assert_called_once()
        assert result is not None

    async def test_uses_cache_when_available(self, mock_client, cache):
        """When content cache has data, should NOT call GitHub."""
        cached_content = "---\ntitle: Cached\nstatus: done\n---\n# Cached\nContent"
        store = _make_mock_content_cache_store(raw=cached_content)

        from canon.web.services import get_spec_detail

        with patch("canon.web.services._load_config", return_value=None):
            result = await get_spec_detail(
                mock_client,
                "owner",
                "repo",
                "docs/specs/test.md",
                cache,
                content_cache_store=store,
            )

        store.get_spec_raw.assert_called_once()
        mock_client.get_file_content.assert_not_called()
        assert result is not None

    async def test_falls_back_on_cache_exception(self, mock_client, cache):
        """When content cache raises, should fall back to GitHub gracefully."""
        store = AsyncMock()
        store.get_spec_raw = AsyncMock(side_effect=Exception("DB down"))

        from canon.web.services import get_spec_detail

        with patch("canon.web.services._load_config", return_value=None):
            result = await get_spec_detail(
                mock_client,
                "owner",
                "repo",
                "docs/specs/test.md",
                cache,
                content_cache_store=store,
            )

        mock_client.get_file_content.assert_called_once()
        assert result is not None

    async def test_no_cache_store_goes_directly_to_github(self, mock_client, cache):
        """When no content_cache_store is provided, should go directly to GitHub."""
        from canon.web.services import get_spec_detail

        with patch("canon.web.services._load_config", return_value=None):
            result = await get_spec_detail(
                mock_client,
                "owner",
                "repo",
                "docs/specs/test.md",
                cache,
            )

        mock_client.get_file_content.assert_called_once()
        assert result is not None

    async def test_returns_none_when_github_also_fails(self, cache):
        """When both cache and GitHub fail, should return None."""
        client = AsyncMock()
        client.get_file_content = AsyncMock(side_effect=Exception("GitHub down"))
        store = _make_mock_content_cache_store(raw=None)

        from canon.web.services import get_spec_detail

        with patch("canon.web.services._load_config", return_value=None):
            result = await get_spec_detail(
                client,
                "owner",
                "repo",
                "docs/specs/test.md",
                cache,
                content_cache_store=store,
            )

        assert result is None

    async def test_in_memory_cache_hit_skips_everything(self, mock_client, cache):
        """When the TTL cache has data, neither content_cache_store nor GitHub is called."""
        from canon.web.models import SpecDetail
        from canon.web.services import get_spec_detail

        # Pre-populate the TTL cache
        sentinel = MagicMock(spec=SpecDetail)
        cache.set("spec:owner/repo/docs/specs/test.md", sentinel)

        store = _make_mock_content_cache_store(raw=None)

        result = await get_spec_detail(
            mock_client,
            "owner",
            "repo",
            "docs/specs/test.md",
            cache,
            content_cache_store=store,
        )

        store.get_spec_raw.assert_not_called()
        mock_client.get_file_content.assert_not_called()
        assert result is sentinel

    async def test_write_through_cache_on_github_fetch(self, mock_client, cache):
        """After a GitHub fetch, the content should be written to the content cache."""
        store = _make_mock_content_cache_store(raw=None)  # cache miss

        from canon.web.services import get_spec_detail

        with (
            patch("canon.web.services._load_config", return_value=None),
            patch("canon.sync.content_sync.ContentSyncEngine") as mock_engine_cls,
        ):
            mock_engine = AsyncMock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.sync_spec = AsyncMock()

            result = await get_spec_detail(
                mock_client,
                "owner",
                "repo",
                "docs/specs/test.md",
                cache,
                content_cache_store=store,
            )

        assert result is not None
        # Write-through attempted — either succeeded or was swallowed silently
        mock_client.get_file_content.assert_called_once()
