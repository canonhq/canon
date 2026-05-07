"""Tests for webhook router endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from canon.webhooks.processor import ProcessResult
from canon.webhooks.router import router


def _make_hmac_signature(payload: bytes, secret: str) -> str:
    """Generate a raw HMAC SHA-256 hex digest."""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


@pytest.fixture
def app():
    """Create a test FastAPI app with the webhooks router."""
    test_app = FastAPI()
    test_app.include_router(router)

    # Mock app state
    settings = MagicMock()
    settings.jira_webhook_secret = "jira-test-secret"
    settings.linear_webhook_secret = "linear-test-secret"
    settings.asana_webhook_secret = "asana-test-secret"

    test_app.state.settings = settings
    test_app.state.github_client = AsyncMock()

    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestJiraEndpoint:
    def test_rejects_invalid_signature(self, client):
        payload = json.dumps({"webhookEvent": "jira:issue_updated"}).encode()
        resp = client.post(
            "/webhooks/jira",
            content=payload,
            headers={"x-hub-signature": "invalid"},
        )
        assert resp.status_code == 401

    def test_accepts_sha256_prefixed_signature(self, client):
        """Jira may send sha256= prefixed signatures."""
        payload = json.dumps({"webhookEvent": "jira:issue_created"}).encode()
        sig = f"sha256={_make_hmac_signature(payload, 'jira-test-secret')}"
        resp = client.post(
            "/webhooks/jira",
            content=payload,
            headers={"x-hub-signature": sig},
        )
        assert resp.status_code == 200
        assert resp.text == "Ignored event"

    def test_ignores_non_update_events(self, client):
        payload = json.dumps({"webhookEvent": "jira:issue_created"}).encode()
        sig = _make_hmac_signature(payload, "jira-test-secret")
        resp = client.post(
            "/webhooks/jira",
            content=payload,
            headers={"x-hub-signature": sig},
        )
        assert resp.status_code == 200
        assert resp.text == "Ignored event"

    def test_processes_issue_update(self, client, app):
        payload_data = {
            "webhookEvent": "jira:issue_updated",
            "issue": {
                "key": "PROJ-123",
                "fields": {
                    "status": {
                        "statusCategory": {"key": "done"},
                    },
                },
            },
        }
        payload = json.dumps(payload_data).encode()
        sig = _make_hmac_signature(payload, "jira-test-secret")

        mock_result = ProcessResult(processed=True, new_state="done")

        with patch(
            "canon.webhooks.router._process_across_repos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                "/webhooks/jira",
                content=payload,
                headers={"x-hub-signature": sig},
            )

        assert resp.status_code == 200
        assert resp.json()["processed"] is True


class TestLinearEndpoint:
    def test_rejects_invalid_signature(self, client):
        payload = json.dumps({"action": "update"}).encode()
        resp = client.post(
            "/webhooks/linear",
            content=payload,
            headers={"linear-signature": "invalid"},
        )
        assert resp.status_code == 401

    def test_ignores_non_update_actions(self, client):
        payload = json.dumps({"action": "create", "type": "Issue"}).encode()
        sig = _make_hmac_signature(payload, "linear-test-secret")
        resp = client.post(
            "/webhooks/linear",
            content=payload,
            headers={"linear-signature": sig},
        )
        assert resp.status_code == 200
        assert resp.text == "Ignored action"

    def test_ignores_non_issue_types(self, client):
        """Linear sends updates for comments, projects, etc. — only Issues matter."""
        payload = json.dumps({"action": "update", "type": "Comment"}).encode()
        sig = _make_hmac_signature(payload, "linear-test-secret")
        resp = client.post(
            "/webhooks/linear",
            content=payload,
            headers={"linear-signature": sig},
        )
        assert resp.status_code == 200
        assert resp.text == "Ignored action"

    def test_processes_issue_update(self, client, app):
        payload_data = {
            "action": "update",
            "type": "Issue",
            "data": {
                "id": "a1b2c3d4-uuid",
                "identifier": "ENG-123",
                "state": {"type": "completed"},
            },
        }
        payload = json.dumps(payload_data).encode()
        sig = _make_hmac_signature(payload, "linear-test-secret")

        mock_result = ProcessResult(processed=True, new_state="done")

        with patch(
            "canon.webhooks.router._process_across_repos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                "/webhooks/linear",
                content=payload,
                headers={"linear-signature": sig},
            )

        assert resp.status_code == 200
        assert resp.json()["processed"] is True


class TestAsanaEndpoint:
    def test_handshake_response(self, client):
        """Asana webhook handshake: respond with X-Hook-Secret header."""
        resp = client.post(
            "/webhooks/asana",
            content=b"",
            headers={"x-hook-secret": "asana-handshake-token"},
        )
        assert resp.status_code == 200
        assert resp.headers["x-hook-secret"] == "asana-handshake-token"

    def test_handshake_sanitizes_long_secret(self, client):
        """Handshake header is length-bounded to 256 chars."""
        long_secret = "a" * 500
        resp = client.post(
            "/webhooks/asana",
            content=b"",
            headers={"x-hook-secret": long_secret},
        )
        assert resp.status_code == 200
        assert len(resp.headers["x-hook-secret"]) == 256

    def test_rejects_invalid_signature_for_events(self, client):
        """Task events with invalid signature return 401."""
        payload = json.dumps({"events": [{"resource": {"resource_type": "task"}}]}).encode()
        resp = client.post(
            "/webhooks/asana",
            content=payload,
            headers={"x-hook-signature": "invalid"},
        )
        assert resp.status_code == 401

    def test_returns_501_for_events(self, client):
        """Task events with valid signature return 501 until Asana adapter is implemented."""
        payload = json.dumps({"events": [{"resource": {"resource_type": "task"}}]}).encode()
        sig = _make_hmac_signature(payload, "asana-test-secret")
        resp = client.post(
            "/webhooks/asana",
            content=payload,
            headers={"x-hook-signature": sig},
        )
        assert resp.status_code == 501


class TestErrorClassification:
    """Verify that business misses return 200 and infra errors return 500."""

    def test_jira_no_linked_section_returns_200(self, client):
        """'No linked spec section' is a business outcome, not a server error."""
        payload_data = {
            "webhookEvent": "jira:issue_updated",
            "issue": {
                "key": "PROJ-999",
                "fields": {"status": {"statusCategory": {"key": "done"}}},
            },
        }
        payload = json.dumps(payload_data).encode()
        sig = _make_hmac_signature(payload, "jira-test-secret")

        mock_result = ProcessResult(
            processed=False, error="No linked spec section found in any repo"
        )
        with patch(
            "canon.webhooks.router._process_across_repos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                "/webhooks/jira",
                content=payload,
                headers={"x-hub-signature": sig},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] is False
        assert "No linked spec section" in body["error"]

    def test_jira_infra_error_returns_500(self, client):
        """Infrastructure failures return 500 with a generic error message."""
        payload_data = {
            "webhookEvent": "jira:issue_updated",
            "issue": {
                "key": "PROJ-999",
                "fields": {"status": {"statusCategory": {"key": "done"}}},
            },
        }
        payload = json.dumps(payload_data).encode()
        sig = _make_hmac_signature(payload, "jira-test-secret")

        mock_result = ProcessResult(
            processed=False,
            error="Failed to list repos: ConnectionError",
            error_kind="infrastructure",
        )
        with patch(
            "canon.webhooks.router._process_across_repos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                "/webhooks/jira",
                content=payload,
                headers={"x-hub-signature": sig},
            )

        assert resp.status_code == 500
        body = resp.json()
        # Error details should NOT be leaked to callers
        assert "ConnectionError" not in body["error"]
        assert body["error"] == "Internal processing error"

    def test_linear_no_linked_section_returns_200(self, client):
        payload_data = {
            "action": "update",
            "type": "Issue",
            "data": {"identifier": "ENG-999", "state": {"type": "completed"}},
        }
        payload = json.dumps(payload_data).encode()
        sig = _make_hmac_signature(payload, "linear-test-secret")

        mock_result = ProcessResult(
            processed=False, error="No linked spec section found in any repo"
        )
        with patch(
            "canon.webhooks.router._process_across_repos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                "/webhooks/linear",
                content=payload,
                headers={"linear-signature": sig},
            )

        assert resp.status_code == 200


class TestBodySizeLimit:
    """Reject oversized payloads before any processing."""

    def test_jira_rejects_oversized_body(self, client):
        large_body = b"x" * (1_048_576 + 1)
        resp = client.post("/webhooks/jira", content=large_body)
        assert resp.status_code == 413

    def test_linear_rejects_oversized_body(self, client):
        large_body = b"x" * (1_048_576 + 1)
        resp = client.post("/webhooks/linear", content=large_body)
        assert resp.status_code == 413

    def test_asana_rejects_oversized_body(self, client):
        large_body = b"x" * (1_048_576 + 1)
        resp = client.post("/webhooks/asana", content=large_body)
        assert resp.status_code == 413


class TestFailClosed:
    """When webhook secrets are not configured, endpoints return 503."""

    def _make_app_without_secrets(self):
        test_app = FastAPI()
        test_app.include_router(router)
        settings = MagicMock()
        settings.jira_webhook_secret = ""
        settings.linear_webhook_secret = ""
        settings.asana_webhook_secret = ""
        test_app.state.settings = settings
        test_app.state.github_client = AsyncMock()
        return test_app

    def test_jira_no_secret_returns_503(self):
        test_app = self._make_app_without_secrets()
        with TestClient(test_app) as tc:
            payload = json.dumps({"webhookEvent": "jira:issue_updated"}).encode()
            resp = tc.post("/webhooks/jira", content=payload)
        assert resp.status_code == 503
        assert "not configured" in resp.text

    def test_linear_no_secret_returns_503(self):
        test_app = self._make_app_without_secrets()
        with TestClient(test_app) as tc:
            payload = json.dumps({"action": "update", "type": "Issue"}).encode()
            resp = tc.post("/webhooks/linear", content=payload)
        assert resp.status_code == 503
        assert "not configured" in resp.text

    def test_asana_no_secret_returns_503(self):
        test_app = self._make_app_without_secrets()
        with TestClient(test_app) as tc:
            resp = tc.post("/webhooks/asana", content=b"{}")
        assert resp.status_code == 503
        assert "not configured" in resp.text

    def test_jira_503_logs_warning_and_emits_telemetry(self, caplog):
        """Regression for the slack/PR#701 silent-failure pattern: a missing
        webhook secret must produce a visible signal — both a logger.warning
        for human eyes and a PostHog event for dashboards. Without these the
        webhook provider retries-then-disables silently."""
        import logging

        test_app = self._make_app_without_secrets()
        with (
            caplog.at_level(logging.WARNING, logger="canon.webhooks.router"),
            patch("canon.webhooks.router.analytics.track") as mock_track,
            TestClient(test_app) as tc,
        ):
            payload = json.dumps({"webhookEvent": "jira:issue_updated"}).encode()
            resp = tc.post("/webhooks/jira", content=payload)

        assert resp.status_code == 503
        assert any("jira webhook returned 503" in r.message.lower() for r in caplog.records), (
            "Missing logger.warning — operators have no signal that the webhook is misconfigured"
        )
        track_calls = [
            c for c in mock_track.call_args_list if c.args[0] == "webhook_misconfigured_503"
        ]
        assert len(track_calls) == 1, "Missing PostHog webhook_misconfigured_503 event"
        assert track_calls[0].kwargs["properties"]["source"] == "jira"

    def test_linear_503_logs_warning_and_emits_telemetry(self, caplog):
        import logging

        test_app = self._make_app_without_secrets()
        with (
            caplog.at_level(logging.WARNING, logger="canon.webhooks.router"),
            patch("canon.webhooks.router.analytics.track") as mock_track,
            TestClient(test_app) as tc,
        ):
            payload = json.dumps({"action": "update", "type": "Issue"}).encode()
            resp = tc.post("/webhooks/linear", content=payload)

        assert resp.status_code == 503
        assert any("linear webhook returned 503" in r.message.lower() for r in caplog.records)
        track_calls = [
            c for c in mock_track.call_args_list if c.args[0] == "webhook_misconfigured_503"
        ]
        assert len(track_calls) == 1
        assert track_calls[0].kwargs["properties"]["source"] == "linear"

    def test_asana_503_logs_warning_and_emits_telemetry(self, caplog):
        import logging

        test_app = self._make_app_without_secrets()
        with (
            caplog.at_level(logging.WARNING, logger="canon.webhooks.router"),
            patch("canon.webhooks.router.analytics.track") as mock_track,
            TestClient(test_app) as tc,
        ):
            resp = tc.post("/webhooks/asana", content=b"{}")

        assert resp.status_code == 503
        assert any("asana webhook returned 503" in r.message.lower() for r in caplog.records)
        track_calls = [
            c for c in mock_track.call_args_list if c.args[0] == "webhook_misconfigured_503"
        ]
        assert len(track_calls) == 1
        assert track_calls[0].kwargs["properties"]["source"] == "asana"

    def test_telemetry_failure_does_not_crash_503_response(self):
        """analytics.track failures must not propagate — webhook must still 503."""
        test_app = self._make_app_without_secrets()
        with (
            patch(
                "canon.webhooks.router.analytics.track",
                side_effect=RuntimeError("posthog down"),
            ),
            TestClient(test_app) as tc,
        ):
            resp = tc.post(
                "/webhooks/jira",
                content=json.dumps({"webhookEvent": "jira:issue_updated"}).encode(),
            )
        assert resp.status_code == 503

    def test_asana_no_secret_blocks_handshake(self):
        """Unauthenticated callers cannot complete the Asana handshake."""
        test_app = self._make_app_without_secrets()
        with TestClient(test_app) as tc:
            resp = tc.post(
                "/webhooks/asana",
                content=b"",
                headers={"x-hook-secret": "asana-handshake-token"},
            )
        assert resp.status_code == 503
