"""Tests for canon.cli._backend_audit — backend routing for audit."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from canon.cli._backend_audit import (
    BackendAuditError,
    call_audit_endpoint,
    resolve_backend_credential,
    should_use_backend,
)
from canon.parser.models import SpecDocument, SpecFrontmatter


def _make_spec_doc(path: str = "docs/specs/test.md", raw: str = "# Test") -> SpecDocument:
    return SpecDocument(
        file_path=path,
        frontmatter=SpecFrontmatter(
            title="Test",
            status="active",
            owner="dev",
            team="platform",
        ),
        sections=[],
        raw=raw,
    )


class TestResolveBackendCredential:
    def test_returns_env_token(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok123")
        monkeypatch.delenv("CANON_API_URL", raising=False)

        cred = resolve_backend_credential()

        assert cred is not None
        assert cred.token == "tok123"
        assert cred.api_url == "https://api.canonhq.co"

    def test_returns_env_token_with_custom_url(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok123")
        monkeypatch.setenv("CANON_API_URL", "https://custom.example.com")

        cred = resolve_backend_credential()

        assert cred is not None
        assert cred.api_url == "https://custom.example.com"

    def test_returns_stored_token_credential(self, monkeypatch):
        monkeypatch.delenv("CANON_TOKEN", raising=False)

        stored = {"method": "token", "token": "stored_tok", "api_url": "https://stored.example.com"}
        with patch("canon.cli._backend_audit.load_credentials", return_value=stored):
            cred = resolve_backend_credential()

        assert cred is not None
        assert cred.token == "stored_tok"
        assert cred.api_url == "https://stored.example.com"

    def test_returns_none_when_no_credential(self, monkeypatch):
        monkeypatch.delenv("CANON_TOKEN", raising=False)

        with patch("canon.cli._backend_audit.load_credentials", return_value=None):
            assert resolve_backend_credential() is None

    def test_returns_none_for_non_token_method(self, monkeypatch):
        monkeypatch.delenv("CANON_TOKEN", raising=False)

        stored = {"method": "oauth", "access_token": "at_123"}
        with patch("canon.cli._backend_audit.load_credentials", return_value=stored):
            assert resolve_backend_credential() is None

    def test_ignores_empty_env_token(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "  ")

        with patch("canon.cli._backend_audit.load_credentials", return_value=None):
            assert resolve_backend_credential() is None

    def test_stored_cred_defaults_api_url(self, monkeypatch):
        monkeypatch.delenv("CANON_TOKEN", raising=False)

        stored = {"method": "token", "token": "tok"}
        with patch("canon.cli._backend_audit.load_credentials", return_value=stored):
            cred = resolve_backend_credential()

        assert cred is not None
        assert cred.api_url == "https://api.canonhq.co"


class TestShouldUseBackend:
    def test_true_when_credential_exists(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok123")
        assert should_use_backend() is True

    def test_false_when_no_credential(self, monkeypatch):
        monkeypatch.delenv("CANON_TOKEN", raising=False)
        with patch("canon.cli._backend_audit.load_credentials", return_value=None):
            assert should_use_backend() is False


class TestCallAuditEndpoint:
    def test_successful_call(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok123")

        response_data = {"results": [{"spec": "test.md", "status": "pass"}]}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = response_data

        with patch("canon.cli._backend_audit.httpx.post", return_value=mock_response) as mock_post:
            result = call_audit_endpoint(
                docs=[_make_spec_doc()],
                evidence_by_path={"docs/specs/test.md": {"1": ["found function"]}},
                repo="owner/repo",
            )

        assert result == response_data
        call_args = mock_post.call_args
        assert "Bearer tok123" in call_args.kwargs["headers"]["Authorization"]
        payload = call_args.kwargs["json"]
        assert payload["repo"] == "owner/repo"
        assert len(payload["specs"]) == 1
        assert len(payload["evidence"]) == 1

    def test_raises_on_missing_credential(self, monkeypatch):
        monkeypatch.delenv("CANON_TOKEN", raising=False)
        with (
            patch("canon.cli._backend_audit.load_credentials", return_value=None),
            pytest.raises(BackendAuditError, match="No CANON_TOKEN"),
        ):
            call_audit_endpoint(docs=[], evidence_by_path={})

    def test_raises_on_401(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "bad_tok")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.is_success = False

        with (
            patch("canon.cli._backend_audit.httpx.post", return_value=mock_response),
            pytest.raises(BackendAuditError, match="rejected the token"),
        ):
            call_audit_endpoint(docs=[], evidence_by_path={})

    def test_raises_on_413(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok")

        mock_response = MagicMock()
        mock_response.status_code = 413
        mock_response.is_success = False

        with (
            patch("canon.cli._backend_audit.httpx.post", return_value=mock_response),
            pytest.raises(BackendAuditError, match="too large"),
        ):
            call_audit_endpoint(docs=[], evidence_by_path={})

    def test_raises_on_500(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.is_success = False

        with (
            patch("canon.cli._backend_audit.httpx.post", return_value=mock_response),
            pytest.raises(BackendAuditError, match="backend error"),
        ):
            call_audit_endpoint(docs=[], evidence_by_path={})

    def test_raises_on_network_error(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok")

        with (
            patch(
                "canon.cli._backend_audit.httpx.post",
                side_effect=httpx.ConnectError("connection refused"),
            ),
            pytest.raises(BackendAuditError, match="network error"),
        ):
            call_audit_endpoint(docs=[], evidence_by_path={})

    def test_raises_on_non_json_response(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.side_effect = ValueError("not JSON")

        with (
            patch("canon.cli._backend_audit.httpx.post", return_value=mock_response),
            pytest.raises(BackendAuditError, match="non-JSON"),
        ):
            call_audit_endpoint(docs=[], evidence_by_path={})

    def test_includes_workflow_run_id(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {}

        with patch("canon.cli._backend_audit.httpx.post", return_value=mock_response) as mock_post:
            call_audit_endpoint(
                docs=[],
                evidence_by_path={},
                workflow_run_id="run-42",
            )

        payload = mock_post.call_args.kwargs["json"]
        assert payload["workflow_run_id"] == "run-42"

    def test_omits_optional_fields_when_none(self, monkeypatch):
        monkeypatch.setenv("CANON_TOKEN", "tok")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {}

        with patch("canon.cli._backend_audit.httpx.post", return_value=mock_response) as mock_post:
            call_audit_endpoint(docs=[], evidence_by_path={})

        payload = mock_post.call_args.kwargs["json"]
        assert "repo" not in payload
        assert "workflow_run_id" not in payload
