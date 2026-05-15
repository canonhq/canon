"""Tests for canon.cli._keywords — keyword extraction for grep-based search."""

from __future__ import annotations

from canon.cli._keywords import extract_keywords


class TestExtractKeywords:
    def test_removes_stop_words(self):
        result = extract_keywords("the user should have access to the dashboard")
        assert "the" not in result
        assert "should" not in result
        assert "have" not in result

    def test_filters_short_words(self):
        result = extract_keywords("a go app is set up for CI")
        # Words with 3 or fewer chars should be excluded
        for word in result:
            assert len(word) > 3

    def test_returns_meaningful_words(self):
        result = extract_keywords("Username validation with regex pattern")
        assert "username" in result
        assert "validation" in result
        assert "regex" in result
        assert "pattern" in result

    def test_limits_to_five_keywords(self):
        text = "authentication authorization encryption decryption hashing salting signing verification"
        result = extract_keywords(text)
        assert len(result) <= 5

    def test_lowercases_input(self):
        result = extract_keywords("JWT Token Generation")
        assert all(w == w.lower() for w in result)

    def test_strips_backticks(self):
        result = extract_keywords("the `render_template` function")
        assert "render_template" in result
        assert "`render_template`" not in result

    def test_strips_parentheses(self):
        result = extract_keywords("function(param) called")
        # parentheses are replaced with spaces, so "function" and "param" are separate
        assert "function(param)" not in result

    def test_empty_string(self):
        assert extract_keywords("") == []

    def test_only_stop_words(self):
        assert extract_keywords("the a an is are was were") == []

    def test_only_short_words(self):
        assert extract_keywords("go run app set") == []
