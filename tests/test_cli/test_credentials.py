"""Tests for CLI credential storage."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from canon.cli._credentials import (
    clear_credentials,
    is_token_expired,
    load_credentials,
    save_credentials,
)


class TestLoadCredentials:
    def test_loads_valid_json(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"
        cred_file.write_text(json.dumps({"method": "oauth", "access_token": "at-123"}))

        with patch("canon.cli._credentials._NEW_CRED_FILE", cred_file):
            result = load_credentials()

        assert result is not None
        assert result["method"] == "oauth"
        assert result["access_token"] == "at-123"

    def test_returns_none_when_missing(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"
        old_cred_file = tmp_path / "old_credentials.json"

        with (
            patch("canon.cli._credentials._NEW_CRED_FILE", cred_file),
            patch("canon.cli._credentials._OLD_CRED_FILE", old_cred_file),
        ):
            result = load_credentials()

        assert result is None

    def test_returns_none_on_invalid_json(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"
        cred_file.write_text("not valid json")

        with patch("canon.cli._credentials._NEW_CRED_FILE", cred_file):
            result = load_credentials()

        assert result is None


class TestSaveCredentials:
    def test_writes_json_with_permissions(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        cred_file = config_dir / "credentials.json"

        with (
            patch("canon.cli._credentials._NEW_CONFIG_DIR", config_dir),
            patch("canon.cli._credentials._NEW_CRED_FILE", cred_file),
        ):
            save_credentials({"method": "api_key", "api_key": "sw_test"})

        assert cred_file.exists()
        data = json.loads(cred_file.read_text())
        assert data["method"] == "api_key"
        # Check file permissions (0600)
        mode = oct(os.stat(cred_file).st_mode)[-3:]
        assert mode == "600"

    def test_creates_parent_directories(self, tmp_path: Path):
        config_dir = tmp_path / "deep" / "nested" / "config"
        cred_file = config_dir / "credentials.json"

        with (
            patch("canon.cli._credentials._NEW_CONFIG_DIR", config_dir),
            patch("canon.cli._credentials._NEW_CRED_FILE", cred_file),
        ):
            save_credentials({"method": "oauth"})

        assert cred_file.exists()


class TestClearCredentials:
    def test_removes_file(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"
        cred_file.write_text("{}")
        old_cred_file = tmp_path / "old_credentials.json"

        with (
            patch("canon.cli._credentials._NEW_CRED_FILE", cred_file),
            patch("canon.cli._credentials._OLD_CRED_FILE", old_cred_file),
        ):
            clear_credentials()

        assert not cred_file.exists()

    def test_no_error_when_missing(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"
        old_cred_file = tmp_path / "old_credentials.json"

        with (
            patch("canon.cli._credentials._NEW_CRED_FILE", cred_file),
            patch("canon.cli._credentials._OLD_CRED_FILE", old_cred_file),
        ):
            clear_credentials()  # Should not raise


class TestIsTokenExpired:
    def test_expired_token(self):
        cred = {"expires_at": time.time() - 100}
        assert is_token_expired(cred) is True

    def test_valid_token(self):
        cred = {"expires_at": time.time() + 3600}
        assert is_token_expired(cred) is False

    def test_missing_expires_at(self):
        cred = {"method": "oauth"}
        assert is_token_expired(cred) is True

    def test_token_within_buffer(self):
        # Token expires in 10 seconds — within 30s buffer
        cred = {"expires_at": time.time() + 10}
        assert is_token_expired(cred) is True

    def test_token_just_outside_buffer(self):
        # Token expires in 60 seconds — outside 30s buffer
        cred = {"expires_at": time.time() + 60}
        assert is_token_expired(cred) is False
