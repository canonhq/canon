"""Integration tests for the /webhook endpoint.

These tests send realistic HTTP requests through the full FastAPI pipeline —
signature verification, JSON parsing, event routing — mocking only the
downstream handler functions to avoid external service calls.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from .conftest import make_payload, sign_payload, webhook_headers

pytestmark = pytest.mark.integration


class TestSignatureVerification:
    """The webhook endpoint must reject requests with invalid/missing signatures."""

    async def test_valid_signature_returns_200(self, app_client, webhook_secret):
        payload = make_payload("push")
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("push", sig)

        with patch("canon.github.handlers.on_push.on_push", new_callable=AsyncMock):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200

    async def test_invalid_signature_returns_401(self, app_client):
        payload = make_payload("push")
        body = json.dumps(payload).encode()
        sig = sign_payload(body, "wrong-secret")
        headers = webhook_headers("push", sig)

        resp = await app_client.post("/webhook", content=body, headers=headers)
        assert resp.status_code == 401

    async def test_missing_signature_returns_401(self, app_client):
        payload = make_payload("push")
        body = json.dumps(payload).encode()
        headers = {
            "x-github-event": "push",
            "x-github-delivery": "test-delivery-id",
            "content-type": "application/json",
        }

        resp = await app_client.post("/webhook", content=body, headers=headers)
        assert resp.status_code == 401


class TestJsonParsing:
    """The webhook endpoint must reject malformed JSON."""

    async def test_malformed_json_returns_400(self, app_client, webhook_secret):
        body = b"not valid json {{"
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("push", sig)

        resp = await app_client.post("/webhook", content=body, headers=headers)
        assert resp.status_code == 400


class TestEventRouting:
    """Events must be dispatched to the correct handler functions."""

    async def test_push_dispatches_to_on_push(self, app_client, webhook_secret):
        payload = make_payload("push")
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("push", sig)

        mock_handler = AsyncMock()
        with patch("canon.github.handlers.on_push.on_push", mock_handler):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200
        mock_handler.assert_called_once()
        # First arg is the client, second is the payload
        call_payload = mock_handler.call_args[0][1]
        assert call_payload["repository"]["full_name"] == "test-org/test-repo"

    async def test_pull_request_opened_dispatches_to_on_pull_request(
        self, app_client, webhook_secret
    ):
        payload = make_payload("pull_request", action="opened")
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("pull_request", sig)

        mock_handler = AsyncMock()
        with patch("canon.github.handlers.on_pull_request.on_pull_request", mock_handler):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200
        mock_handler.assert_called_once()

    async def test_pull_request_synchronize_dispatches_to_on_pull_request(
        self, app_client, webhook_secret
    ):
        payload = make_payload("pull_request", action="synchronize")
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("pull_request", sig)

        mock_handler = AsyncMock()
        with patch("canon.github.handlers.on_pull_request.on_pull_request", mock_handler):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200
        mock_handler.assert_called_once()

    async def test_pull_request_merged_dispatches_to_on_pull_request_merged(
        self, app_client, webhook_secret
    ):
        payload = make_payload("pull_request", action="closed", merged=True)
        # Ensure merged flag is on the pull_request object
        payload["pull_request"]["merged"] = True
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("pull_request", sig)

        mock_handler = AsyncMock()
        with patch(
            "canon.github.handlers.on_pull_request_merged.on_pull_request_merged",
            mock_handler,
        ):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200
        mock_handler.assert_called_once()

    async def test_issue_comment_created_dispatches_to_on_issue_comment(
        self, app_client, webhook_secret
    ):
        payload = make_payload("issue_comment", action="created")
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("issue_comment", sig)

        mock_handler = AsyncMock()
        with patch("canon.github.handlers.on_issue_comment.on_issue_comment", mock_handler):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200
        mock_handler.assert_called_once()

    async def test_issues_event_dispatches_to_on_issues(self, app_client, webhook_secret):
        payload = make_payload("issues", action="opened")
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("issues", sig)

        mock_handler = AsyncMock()
        with patch("canon.github.handlers.on_issues.on_issues", mock_handler):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200
        mock_handler.assert_called_once()

    async def test_installation_event_dispatches_to_on_installation(
        self, app_client, webhook_secret
    ):
        payload = make_payload("installation", action="created")
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("installation", sig)

        mock_handler = AsyncMock()
        with patch("canon.github.handlers.on_installation.on_installation", mock_handler):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200
        mock_handler.assert_called_once()

    async def test_installation_repositories_dispatches(self, app_client, webhook_secret):
        payload = make_payload("installation_repositories", action="added")
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("installation_repositories", sig)

        mock_handler = AsyncMock()
        with patch(
            "canon.github.handlers.on_installation_repos.on_installation_repositories",
            mock_handler,
        ):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200
        mock_handler.assert_called_once()


class TestUnknownEvent:
    """Unknown events should be acknowledged (200) but no handler called."""

    async def test_unknown_event_returns_200(self, app_client, webhook_secret):
        payload = {"repository": {"full_name": "test-org/test-repo"}}
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("unknown_event_type", sig)

        resp = await app_client.post("/webhook", content=body, headers=headers)
        assert resp.status_code == 200


class TestInstallationIdResolution:
    """Webhook should use installation_id from payload to scope the client."""

    async def test_payload_installation_id_creates_scoped_client(
        self, app_client, webhook_secret, mock_github_client
    ):
        payload = make_payload("push")
        # installation.id=12345 differs from the default client's "99999"
        body = json.dumps(payload).encode()
        sig = sign_payload(body, webhook_secret)
        headers = webhook_headers("push", sig)

        mock_handler = AsyncMock()
        with patch("canon.github.handlers.on_push.on_push", mock_handler):
            resp = await app_client.post("/webhook", content=body, headers=headers)

        assert resp.status_code == 200
        # for_installation should have been called with the payload's installation id
        mock_github_client.for_installation.assert_called_once_with("12345")
        # Handler should have received the scoped child client
        called_client = mock_handler.call_args[0][0]
        assert called_client.installation_id == "12345"
