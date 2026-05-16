"""Tests for PR review deep link in format_analysis_comment() and head_sha in embedded JSON."""

from __future__ import annotations

import base64
import json

from canon.agent.analyzer import (
    PRAnalysisResult,
    TokenUsage,
    format_analysis_comment,
)


def _make_result(**overrides) -> PRAnalysisResult:
    defaults = {
        "summary": "Test summary.",
        "spec_references": [],
        "discrepancies": [],
        "doc_updates": [],
        "tokens_used": TokenUsage(input=100, output=50),
    }
    return PRAnalysisResult(**{**defaults, **overrides})


class TestDeepLink:
    BASE = "https://canonhq.co"

    def test_review_link_when_pr_number_provided(self):
        result = _make_result()
        comment = format_analysis_comment(
            result,
            base_url=self.BASE,
            owner="acme",
            repo="myrepo",
            pr_number=42,
        )
        assert "[View in Canon](https://canonhq.co/app/acme/reviews/acme/myrepo/42)" in comment

    def test_fallback_to_repo_link_when_no_pr_number(self):
        result = _make_result()
        comment = format_analysis_comment(
            result,
            base_url=self.BASE,
            owner="acme",
            repo="myrepo",
            pr_number=0,
        )
        assert "[View in Canon](https://canonhq.co/app/acme/repos/acme/myrepo)" in comment

    def test_no_link_when_no_base_url(self):
        result = _make_result()
        comment = format_analysis_comment(
            result,
            base_url="",
            owner="acme",
            repo="myrepo",
            pr_number=42,
        )
        assert "View in Canon" not in comment

    def test_no_link_when_no_owner(self):
        result = _make_result()
        comment = format_analysis_comment(
            result,
            base_url=self.BASE,
            owner="",
            repo="myrepo",
            pr_number=42,
        )
        assert "View in Canon" not in comment


class TestEmbeddedHeadSha:
    def _extract_embedded(self, comment: str) -> dict:
        marker = "<!-- canon-analysis-b64: "
        start = comment.index(marker) + len(marker)
        end = comment.index(" -->", start)
        encoded = comment[start:end]
        return json.loads(base64.b64decode(encoded))

    def test_head_sha_in_embedded_json(self):
        result = _make_result()
        comment = format_analysis_comment(
            result,
            head_sha="abc1234def5678",
        )
        data = self._extract_embedded(comment)
        assert data["headSha"] == "abc1234def5678"

    def test_no_head_sha_when_empty(self):
        result = _make_result()
        comment = format_analysis_comment(
            result,
            head_sha="",
        )
        data = self._extract_embedded(comment)
        assert "headSha" not in data
