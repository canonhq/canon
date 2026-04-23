"""Tests for canon doctor diagnostic command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from canon.cli.doctor_cmd import (
    CheckResult,
    _auth_checks,
    _config_checks,
    _mcp_checks,
    run_doctor,
)
from canon.cli.integration_manager import IntegrationInfo


class TestConfigChecks:
    def test_pass_with_valid_config(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: test\nticket_system: github\n")
        (tmp_path / ".mcp.json").write_text('{"mcpServers": {"canon": {}}}')
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "feature.md").write_text("# Feature")

        results = _config_checks(tmp_path)
        statuses = {r.name: r.status for r in results}
        assert statuses["CANON.yaml"] == "pass"
        assert statuses[".mcp.json"] == "pass"
        assert statuses["Spec files"] == "pass"

    def test_fail_missing_yaml(self, tmp_path: Path):
        results = _config_checks(tmp_path)
        yaml_check = next(r for r in results if r.name == "CANON.yaml")
        assert yaml_check.status == "fail"
        assert "Run `canon setup`" in yaml_check.fix_hint

    def test_warn_missing_mcp(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: test\n")
        results = _config_checks(tmp_path)
        mcp_check = next(r for r in results if r.name == ".mcp.json")
        assert mcp_check.status == "warn"

    def test_warn_no_canon_in_mcp(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: test\n")
        (tmp_path / ".mcp.json").write_text('{"mcpServers": {"other": {}}}')
        results = _config_checks(tmp_path)
        mcp_check = next(r for r in results if r.name == ".mcp.json")
        assert mcp_check.status == "warn"
        assert "No canon server" in mcp_check.message

    def test_warn_no_specs(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: test\n")
        results = _config_checks(tmp_path)
        specs_check = next(r for r in results if r.name == "Spec files")
        assert specs_check.status == "warn"

    def test_fail_invalid_yaml(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: [invalid: yaml: {")
        results = _config_checks(tmp_path)
        yaml_check = next(r for r in results if r.name == "CANON.yaml")
        assert yaml_check.status == "fail"

    def test_warn_with_yaml_warnings(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: test\nunknown_key: value\n")
        results = _config_checks(tmp_path)
        yaml_check = next(r for r in results if r.name == "CANON.yaml")
        assert yaml_check.status == "warn"

    def test_counts_specs_correctly(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: test\n")
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        for i in range(5):
            (tmp_path / "docs" / "specs" / f"spec{i}.md").write_text(f"# Spec {i}")
        (tmp_path / "docs" / "specs" / "_template.md").write_text("# Template")

        results = _config_checks(tmp_path)
        specs_check = next(r for r in results if r.name == "Spec files")
        assert specs_check.status == "pass"
        assert "5 spec files" in specs_check.message


class TestAuthChecks:
    def test_no_credentials(self):
        with (
            patch("canon.cli._credentials.load_credentials", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            results = _auth_checks()
        canon_auth = next(r for r in results if r.name == "Canon auth")
        assert canon_auth.status == "warn"
        assert "Not logged in" in canon_auth.message

    def test_valid_oauth(self):
        import time

        cred = {
            "method": "oauth",
            "email": "user@test.com",
            "org": "testorg",
            "expires_at": time.time() + 3600,
        }
        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            results = _auth_checks()
        canon_auth = next(r for r in results if r.name == "Canon auth")
        assert canon_auth.status == "pass"
        assert "user@test.com" in canon_auth.message

    def test_expired_oauth(self):
        import time

        cred = {
            "method": "oauth",
            "email": "user@test.com",
            "org": "testorg",
            "expires_at": time.time() - 3600,
        }
        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            results = _auth_checks()
        canon_auth = next(r for r in results if r.name == "Canon auth")
        assert canon_auth.status == "warn"
        assert "expired" in canon_auth.message

    def test_api_key_auth(self):
        cred = {"method": "api_key", "api_key": "key", "org": "testorg"}
        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            results = _auth_checks()
        canon_auth = next(r for r in results if r.name == "Canon auth")
        assert canon_auth.status == "pass"

    def test_gh_cli_authenticated(self):
        with (
            patch("canon.cli._credentials.load_credentials", return_value=None),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            results = _auth_checks()
        gh_check = next(r for r in results if r.name == "GitHub CLI")
        assert gh_check.status == "pass"

    def test_gh_cli_not_installed(self):
        with (
            patch("canon.cli._credentials.load_credentials", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            results = _auth_checks()
        gh_check = next(r for r in results if r.name == "GitHub CLI")
        assert gh_check.status == "warn"
        assert "Not installed" in gh_check.message


class TestMcpChecks:
    def test_no_mcp_json_skips(self, tmp_path: Path):
        results = _mcp_checks(tmp_path)
        assert results == []

    def test_uvx_available(self, tmp_path: Path):
        (tmp_path / ".mcp.json").write_text('{"mcpServers": {"canon": {}}}')
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            results = _mcp_checks(tmp_path)
        mcp_check = next(r for r in results if r.name == "MCP runtime")
        assert mcp_check.status == "pass"

    def test_uvx_not_installed(self, tmp_path: Path):
        (tmp_path / ".mcp.json").write_text('{"mcpServers": {"canon": {}}}')
        with patch("subprocess.run", side_effect=FileNotFoundError):
            results = _mcp_checks(tmp_path)
        mcp_check = next(r for r in results if r.name == "MCP runtime")
        assert mcp_check.status == "warn"


class TestRunDoctor:
    def test_json_output(self, tmp_path: Path, capsys, monkeypatch):
        (tmp_path / "CANON.yaml").write_text("team: test\n")
        monkeypatch.chdir(tmp_path)

        with (
            patch("canon.cli._credentials.load_credentials", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            run_doctor(json_output=True, fix=False)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert all("name" in d and "status" in d for d in data)

    def test_exit_code_0_all_pass(self, tmp_path: Path, monkeypatch):
        (tmp_path / "CANON.yaml").write_text("team: test\nticket_system: github\n")
        (tmp_path / ".mcp.json").write_text('{"mcpServers": {"canon": {}}}')
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "f.md").write_text("# F")
        monkeypatch.chdir(tmp_path)

        cred = {
            "method": "api_key",
            "api_key": "key",
            "org": "testorg",
        }

        from canon.cli.integration_manager import IntegrationManager, TestResult

        mock_test = TestResult(provider="github", ok=True, message="OK", latency_ms=10.0)

        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("subprocess.run") as mock_run,
            patch(
                "canon.cli.integration_manager.IntegrationManager._from_backend",
                return_value=[
                    IntegrationInfo(
                        provider="github",
                        source="backend",
                        status="connected",
                        details="acme/repo",
                    )
                ],
            ),
            patch.object(IntegrationManager, "test_connection", return_value=mock_test),
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Logged in"
            mock_run.return_value.stderr = ""
            exit_code = run_doctor(json_output=True, fix=False)

        assert exit_code == 0

    def test_exit_code_1_on_fail(self, tmp_path: Path, monkeypatch):
        """Missing CANON.yaml should produce a fail."""
        monkeypatch.chdir(tmp_path)
        with (
            patch("canon.cli._credentials.load_credentials", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            exit_code = run_doctor(json_output=True, fix=False)

        assert exit_code == 1


class TestCheckResult:
    def test_fix_action_called_on_fix(self):
        fixed = False

        def fixer():
            nonlocal fixed
            fixed = True
            return True

        r = CheckResult(
            name="test",
            category="config",
            status="fail",
            message="broken",
            fix_action=fixer,
        )
        # Simulate --fix
        if r.status == "fail" and r.fix_action is not None and r.fix_action():
            r.status = "pass"
            r.message += " (fixed)"

        assert fixed
        assert r.status == "pass"
        assert "(fixed)" in r.message
