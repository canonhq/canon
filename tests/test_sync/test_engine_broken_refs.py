"""Engine-level tests for broken-ref skip + record behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from canon.parser.models import SectionStatus
from canon.parser.parse import parse_spec
from canon.sync.engine import reverse_sync
from canon.sync.models import TicketStatusResult

# Existing MockAdapter pattern in tests/test_sync/test_engine.py
from tests.test_sync.test_engine import MockAdapter

_SPEC = """---
title: Broken ref test
status: in_progress
---

# Broken ref test

## 1. Has a ticket

<!-- canon:system:1 status:in_progress -->
<!-- canon:ticket:github:456 url:https://github.com/o/r/issues/456 -->

Body
"""


def _http_404() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.github.com/repos/o/r/issues/456")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("404", request=request, response=response)


@pytest.fixture
def doc():
    return parse_spec(_SPEC).document


@pytest.fixture
def ref_store():
    rows: dict[tuple, dict] = {}
    store = AsyncMock()

    async def _get(installation_id, system, ticket_ref):
        return rows.get((installation_id, system, ticket_ref))

    async def _record_failure(*, installation_id, system, ticket_ref, error_kind, error_message):
        key = (installation_id, system, ticket_ref)
        existing = rows.get(key, {"consecutive_failures": 0, "status": "ok"})
        existing["consecutive_failures"] = existing.get("consecutive_failures", 0) + 1
        if existing["consecutive_failures"] >= 3:
            existing["status"] = "broken"
        existing.update(
            {
                "installation_id": installation_id,
                "system": system,
                "ticket_ref": ticket_ref,
                "last_error_kind": error_kind,
                "last_error_message": error_message,
                "first_failure_at": existing.get("first_failure_at") or datetime.now(UTC),
                "last_check_at": datetime.now(UTC),
                "last_recheck_at": (datetime.now(UTC) if existing["status"] == "broken" else None),
            }
        )
        rows[key] = existing
        return {
            "status": existing["status"],
            "consecutive_failures": existing["consecutive_failures"],
        }

    async def _mark_ok(*, installation_id, system, ticket_ref):
        key = (installation_id, system, ticket_ref)
        if key in rows and rows[key].get("status") != "dismissed":
            rows[key]["status"] = "ok"
            rows[key]["consecutive_failures"] = 0
            rows[key]["last_recheck_at"] = None

    store.get = AsyncMock(side_effect=_get)
    store.record_failure = AsyncMock(side_effect=_record_failure)
    store.mark_ok = AsyncMock(side_effect=_mark_ok)
    store._rows = rows
    return store


class TestThreeFailuresFlipToBroken:
    async def test_flip(self, doc, ref_store):
        adapter = MockAdapter(status_error=_http_404())
        for _ in range(3):
            await reverse_sync(
                doc,
                adapter,
                repo="o/r",
                installation_id=1,
                ref_store=ref_store,
            )
        key = (1, "github", "o/r#456")
        assert ref_store._rows[key]["status"] == "broken"
        assert ref_store._rows[key]["consecutive_failures"] == 3
        assert len(adapter.status_queries) == 3


class TestBrokenRefIsSkipped:
    async def test_skip(self, doc, ref_store):
        recent = datetime.now(UTC) - timedelta(hours=1)
        ref_store._rows[(1, "github", "o/r#456")] = {
            "installation_id": 1,
            "system": "github",
            "ticket_ref": "o/r#456",
            "status": "broken",
            "consecutive_failures": 3,
            "last_recheck_at": recent,
        }
        adapter = MockAdapter(status_error=_http_404())
        result = await reverse_sync(
            doc,
            adapter,
            repo="o/r",
            installation_id=1,
            ref_store=ref_store,
        )
        assert adapter.status_queries == []
        assert result[1].errors == []


class TestSuccessClearsBroken:
    async def test_clear(self, doc, ref_store):
        old = datetime.now(UTC) - timedelta(hours=25)
        ref_store._rows[(1, "github", "o/r#456")] = {
            "installation_id": 1,
            "system": "github",
            "ticket_ref": "o/r#456",
            "status": "broken",
            "consecutive_failures": 3,
            "last_recheck_at": old,
        }
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="456",
                status=SectionStatus(state="done"),
                raw_status="closed",
            )
        )
        await reverse_sync(
            doc,
            adapter,
            repo="o/r",
            installation_id=1,
            ref_store=ref_store,
        )
        assert len(adapter.status_queries) == 1
        assert ref_store._rows[(1, "github", "o/r#456")]["status"] == "ok"


class TestDismissedRefIsSkipped:
    async def test_skip(self, doc, ref_store):
        old = datetime.now(UTC) - timedelta(days=30)
        ref_store._rows[(1, "github", "o/r#456")] = {
            "installation_id": 1,
            "system": "github",
            "ticket_ref": "o/r#456",
            "status": "dismissed",
            "consecutive_failures": 3,
            "last_recheck_at": old,
        }
        adapter = MockAdapter(status_error=_http_404())
        await reverse_sync(
            doc,
            adapter,
            repo="o/r",
            installation_id=1,
            ref_store=ref_store,
        )
        assert adapter.status_queries == []


class TestTransientFailureDoesNotIncrement:
    async def test_500_no_increment(self, doc, ref_store):
        request = httpx.Request("GET", "https://example.com/x")
        err = httpx.HTTPStatusError(
            "500",
            request=request,
            response=httpx.Response(500, request=request),
        )
        adapter = MockAdapter(status_error=err)
        await reverse_sync(
            doc,
            adapter,
            repo="o/r",
            installation_id=1,
            ref_store=ref_store,
        )
        assert (1, "github", "o/r#456") not in ref_store._rows


class TestStoreFailureFailsOpen:
    async def test_get_raises_does_not_abort(self, doc):
        store = AsyncMock()
        store.get = AsyncMock(side_effect=RuntimeError("db down"))
        store.record_failure = AsyncMock()
        store.mark_ok = AsyncMock()
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="456",
                status=SectionStatus(state="done"),
                raw_status="closed",
            )
        )
        await reverse_sync(
            doc,
            adapter,
            repo="o/r",
            installation_id=1,
            ref_store=store,
        )
        assert len(adapter.status_queries) == 1
