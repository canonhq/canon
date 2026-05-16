"""Tests for the shared CLI output module."""

from __future__ import annotations

from canon.cli._output import (
    configure,
    coverage_style,
    coverage_text,
    get_console,
    get_stdout,
    is_quiet,
    prompt,
    prompt_choice,
    prompt_confirm,
    result_badge,
    status_badge,
)


class TestStatusBadge:
    def test_done_is_green(self):
        badge = status_badge("done")
        assert badge.plain == "done"
        assert "green" in str(badge.style)

    def test_in_progress_is_yellow(self):
        badge = status_badge("in_progress")
        assert badge.plain == "in_progress"
        assert "yellow" in str(badge.style)

    def test_todo_is_dim(self):
        badge = status_badge("todo")
        assert badge.plain == "todo"
        assert "dim" in str(badge.style)

    def test_blocked_is_red(self):
        badge = status_badge("blocked")
        assert badge.plain == "blocked"
        assert "red" in str(badge.style)

    def test_unknown_status(self):
        badge = status_badge("custom_status")
        assert badge.plain == "custom_status"


class TestResultBadge:
    def test_pass(self):
        badge = result_badge("pass")
        assert badge.plain == "PASS"
        assert "green" in str(badge.style)

    def test_fail(self):
        badge = result_badge("fail")
        assert badge.plain == "FAIL"
        assert "red" in str(badge.style)

    def test_warn(self):
        badge = result_badge("warn")
        assert badge.plain == "WARN"
        assert "yellow" in str(badge.style)

    def test_unknown_result(self):
        badge = result_badge("custom")
        assert badge.plain == "CUSTOM"


class TestCoverage:
    def test_high_coverage_green(self):
        assert coverage_style(85.0) == "green"

    def test_medium_coverage_yellow(self):
        assert coverage_style(60.0) == "yellow"

    def test_low_coverage_red(self):
        assert coverage_style(30.0) == "red"

    def test_boundary_80(self):
        assert coverage_style(80.0) == "green"

    def test_boundary_50(self):
        assert coverage_style(50.0) == "yellow"

    def test_coverage_text_default_label(self):
        text = coverage_text(85.0)
        assert text.plain == "85%"

    def test_coverage_text_custom_label(self):
        text = coverage_text(85.0, label="5/6")
        assert text.plain == "5/6"


class TestConfigure:
    def test_quiet_flag(self):
        configure(quiet=True)
        assert is_quiet() is True
        configure(quiet=False)
        assert is_quiet() is False

    def test_no_color_replaces_consoles(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        old_stdout = get_stdout()
        configure(no_color=True)
        new_stdout = get_stdout()
        assert new_stdout is not old_stdout
        assert new_stdout.no_color is True
        # Clean up
        configure(no_color=False)
        monkeypatch.delenv("NO_COLOR", raising=False)

    def test_accessors_return_current(self):
        c = get_console()
        s = get_stdout()
        assert c is not None
        assert s is not None
        assert c.stderr is True


class TestPrompt:
    def test_returns_user_input(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "hello")
        assert prompt("Name") == "hello"

    def test_returns_default_on_empty(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert prompt("Name", default="world") == "world"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "  hello  ")
        assert prompt("Name") == "hello"


class TestPromptConfirm:
    def test_default_yes(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert prompt_confirm("Continue?", default=True) is True

    def test_default_no(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert prompt_confirm("Continue?", default=False) is False

    def test_explicit_yes(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        assert prompt_confirm("Continue?", default=False) is True

    def test_explicit_no(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        assert prompt_confirm("Continue?", default=True) is False


class TestPromptChoice:
    def test_numeric_selection(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "2")
        result = prompt_choice("Pick:", ["a", "b", "c"], default="a")
        assert result == "b"

    def test_text_selection(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "github")
        result = prompt_choice("System:", ["github", "jira", "linear"], default="github")
        assert result == "github"

    def test_default_on_empty(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = prompt_choice("Pick:", ["a", "b"], default="b")
        assert result == "b"

    def test_invalid_input_falls_back(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda _: "99")
        result = prompt_choice("Pick:", ["a", "b"], default="a")
        assert result == "a"
        output = capsys.readouterr().out
        assert "Invalid choice" in output
