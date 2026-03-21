"""Tests for canon.db.migrate URL normalisation helpers."""

from __future__ import annotations

from canon.db.migrate import _to_asyncpg_url, _to_sqla_async_url

# ---------------------------------------------------------------------------
# _to_sqla_async_url — sslmode conversion
# ---------------------------------------------------------------------------


class TestToSqlaAsyncUrl:
    """Verify sslmode→ssl conversion for SQLAlchemy+asyncpg URLs."""

    def test_sslmode_require_converted_to_ssl_require(self) -> None:
        url = "postgresql://u:p@host:5432/db?sslmode=require"
        result = _to_sqla_async_url(url)
        assert "sslmode" not in result
        assert "ssl=require" in result
        assert result.startswith("postgresql+asyncpg://")

    def test_sslmode_prefer_converted_to_ssl_require(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=prefer"
        result = _to_sqla_async_url(url)
        assert "sslmode" not in result
        assert "ssl=require" in result

    def test_sslmode_disable_strips_ssl(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=disable"
        result = _to_sqla_async_url(url)
        assert "sslmode" not in result
        assert "ssl" not in result

    def test_sslmode_verify_full(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=verify-full"
        result = _to_sqla_async_url(url)
        assert "sslmode" not in result
        assert "ssl=verify-full" in result

    def test_sslmode_verify_ca_maps_to_verify_full(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=verify-ca"
        result = _to_sqla_async_url(url)
        assert "sslmode" not in result
        assert "ssl=verify-full" in result

    def test_no_sslmode_passes_through_unchanged(self) -> None:
        url = "postgresql://u:p@host:5432/db"
        result = _to_sqla_async_url(url)
        assert result == "postgresql+asyncpg://u:p@host:5432/db"

    def test_existing_ssl_param_not_overwritten(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=require&ssl=verify-full"
        result = _to_sqla_async_url(url)
        assert "sslmode" not in result
        # existing ssl=verify-full should be preserved, not overwritten
        assert "ssl=verify-full" in result

    def test_other_query_params_preserved(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=require&application_name=canon"
        result = _to_sqla_async_url(url)
        assert "application_name=canon" in result
        assert "ssl=require" in result
        assert "sslmode" not in result

    def test_channel_binding_stripped(self) -> None:
        url = "postgresql://u:p@host/db?channel_binding=require"
        result = _to_sqla_async_url(url)
        assert "channel_binding" not in result
        assert result.startswith("postgresql+asyncpg://")

    def test_channel_binding_stripped_with_sslmode(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=require&channel_binding=require"
        result = _to_sqla_async_url(url)
        assert "channel_binding" not in result
        assert "ssl=require" in result
        assert "sslmode" not in result

    def test_postgres_scheme_normalised(self) -> None:
        url = "postgres://u:p@host/db?sslmode=require"
        result = _to_sqla_async_url(url)
        assert result.startswith("postgresql+asyncpg://")
        assert "ssl=require" in result
        assert "sslmode" not in result

    def test_asyncpg_scheme_normalised(self) -> None:
        url = "postgresql+asyncpg://u:p@host/db?sslmode=require"
        result = _to_sqla_async_url(url)
        assert result.startswith("postgresql+asyncpg://")
        assert "ssl=require" in result
        assert "sslmode" not in result

    def test_sslmode_allow_upgraded_to_ssl_require(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=allow"
        result = _to_sqla_async_url(url)
        assert "sslmode" not in result
        assert "ssl=require" in result

    def test_unknown_sslmode_passes_through_unchanged(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=bogus"
        result = _to_sqla_async_url(url)
        # Unknown values are left as-is (with a warning logged)
        assert "sslmode=bogus" in result
        assert result.startswith("postgresql+asyncpg://")

    def test_sslmode_disable_strips_existing_ssl_param(self) -> None:
        url = "postgresql://u:p@host/db?ssl=require&sslmode=disable"
        result = _to_sqla_async_url(url)
        assert "sslmode" not in result
        assert "ssl" not in result


# ---------------------------------------------------------------------------
# _to_asyncpg_url — sslmode should be preserved (raw asyncpg handles it)
# ---------------------------------------------------------------------------


class TestToAsyncpgUrl:
    """Verify that _to_asyncpg_url preserves sslmode for raw asyncpg."""

    def test_sslmode_preserved(self) -> None:
        url = "postgresql://u:p@host/db?sslmode=require"
        result = _to_asyncpg_url(url)
        assert "sslmode=require" in result

    def test_scheme_normalised_from_postgres(self) -> None:
        url = "postgres://u:p@host/db"
        result = _to_asyncpg_url(url)
        assert result.startswith("postgresql://")

    def test_scheme_normalised_from_asyncpg(self) -> None:
        url = "postgresql+asyncpg://u:p@host/db"
        result = _to_asyncpg_url(url)
        assert result.startswith("postgresql://")
        assert "+asyncpg" not in result
