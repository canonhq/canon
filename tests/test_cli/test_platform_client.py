"""Tests for the CLI platform HTTP client."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from canon.cli._platform import AuthRequiredError, PlatformClient


def _mock_credentials(method="oauth", expired=False, **overrides):
    cred = {
        "method": method,
        "access_token": "at-123",
        "refresh_token": "rt-456",
        "expires_at": time.time() + (-100 if expired else 3600),
        "org": "my-org",
        "email": "user@example.com",
    }
    if method == "api_key":
        cred = {"method": "api_key", "api_key": "sw_test", "org": "my-org"}
    cred.update(overrides)
    return cred


class TestPlatformClientInit:
    def test_default_url(self):
        client = PlatformClient()
        assert "canonhq.co" in client.base_url
        client.close()

    def test_custom_url(self):
        client = PlatformClient(base_url="http://localhost:3000")
        assert client.base_url == "http://localhost:3000"
        client.close()

    def test_env_override(self):
        with patch.dict("os.environ", {"CANON_URL": "http://custom:8080"}):
            client = PlatformClient()
            assert client.base_url == "http://custom:8080"
            client.close()


class TestAuthRequired:
    def test_raises_when_no_credentials(self):
        with patch("canon.cli._platform.load_credentials", return_value=None):
            client = PlatformClient(base_url="http://test")
            with pytest.raises(AuthRequiredError, match="Not logged in"):
                client.request("GET", "/test")
            client.close()


class TestAuthHeader:
    def test_oauth_header(self):
        header = PlatformClient._auth_header({"method": "oauth", "access_token": "at-123"})
        assert header == {"Authorization": "Bearer at-123"}

    def test_api_key_header(self):
        header = PlatformClient._auth_header({"method": "api_key", "api_key": "sw_test"})
        assert header == {"Authorization": "Bearer sw_test"}


class TestPreemptiveRefresh:
    def test_refreshes_expired_token_before_request(self):
        expired_cred = _mock_credentials(expired=True)
        refreshed_cred = _mock_credentials(expired=False, access_token="new-at")

        mock_http = MagicMock()
        mock_http.request = MagicMock(return_value=MagicMock(status_code=200))
        mock_http.post = MagicMock(
            return_value=MagicMock(
                status_code=200,
                json=MagicMock(return_value={"access_token": "new-at", "expires_in": 3600}),
            )
        )

        call_count = 0

        def load_side_effect():
            nonlocal call_count
            call_count += 1
            # First call returns expired, subsequent calls return refreshed
            return expired_cred if call_count == 1 else refreshed_cred

        with (
            patch("canon.cli._platform.load_credentials", side_effect=load_side_effect),
            patch("canon.cli._platform.save_credentials"),
            patch("canon.cli._platform.is_token_expired", return_value=True),
        ):
            client = PlatformClient(base_url="http://test")
            client._http = mock_http
            client.request("GET", "/test")

        # Should have called refresh
        mock_http.post.assert_called_once()
        assert "/auth/refresh" in str(mock_http.post.call_args)


class TestReactiveRefresh:
    def test_retries_on_401(self):
        valid_cred = _mock_credentials()

        mock_401 = MagicMock(status_code=401)
        mock_200 = MagicMock(status_code=200)
        mock_refresh = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "access_token": "new-at",
                    "refresh_token": "new-rt",
                    "expires_in": 3600,
                }
            ),
        )

        mock_http = MagicMock()
        mock_http.request = MagicMock(side_effect=[mock_401, mock_200])
        mock_http.post = MagicMock(return_value=mock_refresh)

        with (
            patch("canon.cli._platform.load_credentials", return_value=valid_cred),
            patch("canon.cli._platform.save_credentials"),
            patch("canon.cli._platform.is_token_expired", return_value=False),
        ):
            client = PlatformClient(base_url="http://test")
            client._http = mock_http
            resp = client.request("GET", "/test")

        assert resp.status_code == 200
        # Original + retry
        assert mock_http.request.call_count == 2


class TestRefreshFailure:
    def test_raises_on_refresh_failure(self):
        expired_cred = _mock_credentials(expired=True)

        mock_http = MagicMock()
        mock_http.post = MagicMock(return_value=MagicMock(status_code=401))

        with (
            patch("canon.cli._platform.load_credentials", return_value=expired_cred),
            patch("canon.cli._platform.is_token_expired", return_value=True),
        ):
            client = PlatformClient(base_url="http://test")
            client._http = mock_http
            with pytest.raises(AuthRequiredError, match="refresh failed"):
                client.request("GET", "/test")

    def test_raises_when_no_refresh_token(self):
        cred = _mock_credentials(expired=True, refresh_token="")

        with (
            patch("canon.cli._platform.load_credentials", return_value=cred),
            patch("canon.cli._platform.is_token_expired", return_value=True),
        ):
            client = PlatformClient(base_url="http://test")
            with pytest.raises(AuthRequiredError, match="No refresh token"):
                client.request("GET", "/test")
