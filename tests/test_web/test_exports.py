"""Tests for the user data-export `collect()` step.

The S3 upload, email dispatch, and cleanup cron land with the follow-up
infra PR that provisions the canon-user-exports Spaces bucket — those
tests live alongside the new code there. This file covers what ships
in the code-only PR: the pure-DB collection and its JSON-roundtrip
invariant.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from canon.web.exports import UserExportJob, _json_safe


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Pool whose acquire() returns an async context manager yielding mock_conn."""
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    pool.acquire = _acquire
    return pool


class TestJsonSafe:
    """`_json_safe` must convert every asyncpg-native scalar to a JSON
    primitive — the export bundle's roundtrip-through-json.dumps
    invariant rides on this helper not silently coercing unknown types
    to opaque `str()`."""

    def test_passthrough_primitives(self):
        for v in (None, "x", 1, 1.5, True, False):
            assert _json_safe(v) is v if isinstance(v, str | type(None)) else _json_safe(v) == v

    def test_datetime_to_isoformat(self):
        dt = datetime(2026, 5, 22, 1, 2, 3, tzinfo=UTC)
        assert _json_safe(dt) == "2026-05-22T01:02:03+00:00"

    def test_uuid_to_string(self):
        u = UUID("12345678-1234-5678-1234-567812345678")
        assert _json_safe(u) == "12345678-1234-5678-1234-567812345678"

    def test_nested_dict_and_list(self):
        result = _json_safe(
            {"a": [datetime(2026, 1, 1, tzinfo=UTC), {"b": UUID(int=0)}]},
        )
        assert result == {
            "a": ["2026-01-01T00:00:00+00:00", {"b": "00000000-0000-0000-0000-000000000000"}]
        }

    def test_fallback_logs_and_returns_str(self, caplog):
        class Weird:
            def __str__(self):
                return "weird-value"

        with caplog.at_level("WARNING"):
            assert _json_safe(Weird()) == "weird-value"
        assert any("falling back to str()" in r.getMessage() for r in caplog.records)


class TestCollect:
    USER_ID = 42
    ORG = "acme"

    def _user_row(self) -> dict:
        return {
            "id": self.USER_ID,
            "oidc_sub": "auth0|abc",
            "email": "u@x.com",
            "name": "User",
            "picture": "",
            "role": "admin",
            "status": "active",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "last_login_at": datetime(2026, 5, 1, tzinfo=UTC),
        }

    async def test_assembles_bundle_with_all_user_tables(self):
        # Mocks an in-DB user with one row per supplemental table; bundle
        # is asserted at the structural level (keys + counts) and at the
        # JSON-roundtrip level so a future schema addition that returns a
        # non-JSON-native value can't silently break exports.
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=self._user_row())

        session_row = {
            "id": "sid-1",
            "org_login": self.ORG,
            "device_label": "Chrome",
            "created_at": datetime(2026, 4, 1, tzinfo=UTC),
            "last_used_at": datetime(2026, 5, 1, tzinfo=UTC),
            "expires_at": datetime(2026, 6, 1, tzinfo=UTC),
            "revoked_at": None,
        }
        api_key_row = {
            "id": 9,
            "key_hash": "deadbeef",
            "label": "laptop",
            "org_login": self.ORG,
            "scopes": ["specs:read"],
            "created_at": datetime(2026, 3, 1, tzinfo=UTC),
            "expires_at": None,
            "revoked_at": None,
            "last_used_at": None,
        }
        pref_row = {
            "user_id": self.USER_ID,
            "org_login": self.ORG,
            "slack_dm_enabled": True,
            "slack_dm_pr_comments": True,
            "slack_dm_spec_drift": True,
            "email_digest_cadence": "weekly",
            "email_pr_comments": False,
            "theme": "system",
            "timezone": "",
            "relative_time": True,
        }
        audit_row = {
            "id": UUID(int=1),
            "created_at": datetime(2026, 5, 21, tzinfo=UTC),
            "org": self.ORG,
            "event_type": "profile.account.updated",
            "resource_type": "user_session",
            "resource_id": "auth0|abc",
            "detail": {"fields": ["name"]},
            "ip_address": "10.0.0.1",
        }
        # fetch() called four times in order: sessions, api_keys, prefs, audit.
        mock_conn.fetch = AsyncMock(
            side_effect=[[session_row], [api_key_row], [pref_row], [audit_row]]
        )
        pool = _mock_pool_with_conn(mock_conn)

        job = UserExportJob(pool)
        bundle = await job.collect(self.USER_ID, self.ORG)

        # Structural invariants.
        assert bundle["schema_version"] == 1
        assert bundle["user_id"] == self.USER_ID
        assert "exported_at" in bundle
        assert bundle["users"]["oidc_sub"] == "auth0|abc"
        assert len(bundle["sessions"]) == 1
        assert len(bundle["api_keys"]) == 1
        assert len(bundle["user_preferences"]) == 1
        assert len(bundle["audit_events"]) == 1

        # Datetimes/UUIDs/JSONB all converted to JSON-native types.
        roundtripped = json.loads(json.dumps(bundle))
        assert roundtripped == bundle

        # AC: api_keys exports key_hash (the salted hash), never anything
        # that would let an attacker reconstruct the raw key.
        api_key = bundle["api_keys"][0]
        assert api_key["key_hash"] == "deadbeef"
        # Defense in depth: no raw-key column should ever exist on this
        # row. If a future migration adds one, this assertion fails
        # before the export ships it to the user (and to whoever sniffs
        # the signed URL).
        for forbidden in ("key", "raw_key", "plaintext"):
            assert forbidden not in api_key

        # Audit query is scoped to the requesting org; verify the SQL
        # carries the org param so a future refactor that drops the
        # ($2 = '' OR org = $2) guard breaks this test.
        audit_call = mock_conn.fetch.call_args_list[-1]
        sql, *args = audit_call.args
        assert "org = $2" in sql
        assert args == [self.USER_ID, self.ORG]

    async def test_handles_missing_user_row(self):
        # Race: user was deleted between the auth check and the export
        # query. We don't want to crash; the bundle's `users` key is
        # None and the supplemental tables are empty (cascade fired).
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.fetch = AsyncMock(side_effect=[[], [], [], []])
        pool = _mock_pool_with_conn(mock_conn)

        job = UserExportJob(pool)
        bundle = await job.collect(self.USER_ID, self.ORG)

        assert bundle["users"] is None
        assert bundle["sessions"] == []
        assert bundle["api_keys"] == []
        # Still JSON-roundtrips.
        assert json.loads(json.dumps(bundle)) == bundle

    async def test_omits_realization_evidence(self):
        # realization_evidence has no per-user authorship column today;
        # documented as out of scope until a schema addition lands. The
        # bundle must not include the key so consumers can't accidentally
        # rely on an empty list as "this user authored nothing" when in
        # reality we can't tell.
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=self._user_row())
        mock_conn.fetch = AsyncMock(side_effect=[[], [], [], []])
        pool = _mock_pool_with_conn(mock_conn)

        job = UserExportJob(pool)
        bundle = await job.collect(self.USER_ID, self.ORG)

        assert "realization_evidence" not in bundle

    async def test_empty_org_skips_org_filter(self):
        # CLI exports run outside any org context; passing org_login=""
        # should return audit events across all orgs the user has touched.
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=self._user_row())
        mock_conn.fetch = AsyncMock(side_effect=[[], [], [], []])
        pool = _mock_pool_with_conn(mock_conn)

        job = UserExportJob(pool)
        await job.collect(self.USER_ID, "")

        audit_call = mock_conn.fetch.call_args_list[-1]
        _, *args = audit_call.args
        assert args == [self.USER_ID, ""]
