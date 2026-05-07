"""Tests for the issue classifier."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add extension src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from issue_triage.classifier import (
    build_user_message,
    parse_classification_response,
)
from issue_triage.models import IssueCategory, IssueContext


@pytest.fixture
def feature_issue():
    return IssueContext(
        number=101,
        title="Add support for GitLab CI integration",
        body="We use GitLab and want Canon integration.",
        author="user1",
        labels=[],
        repo_owner="canonhq",
        repo_name="canon",
    )


@pytest.fixture
def bug_issue():
    return IssueContext(
        number=102,
        title="canon verify crashes on empty AC sections",
        body="TypeError: 'NoneType' object is not iterable",
        author="user2",
        labels=[],
        repo_owner="canonhq",
        repo_name="canon",
    )


@pytest.fixture
def spec_summaries():
    return [
        {
            "path": "docs/specs/github-actions-suite.md",
            "title": "GitHub Actions Suite",
            "status": "draft",
            "sections": ["Background", "Goals & Non-Goals", "Requirements"],
        },
        {
            "path": "docs/specs/ci-actions-adoption.md",
            "title": "CI Actions Adoption & Issue Triage Extension",
            "status": "draft",
            "sections": ["Background", "Dogfood: canon-private PR Workflow"],
        },
    ]


class TestBuildUserMessage:
    def test_includes_issue_details(self, feature_issue, spec_summaries):
        msg = build_user_message(feature_issue, spec_summaries)
        assert "Issue #101" in msg
        assert "Add support for GitLab CI integration" in msg
        assert "user1" in msg

    def test_includes_spec_summaries(self, feature_issue, spec_summaries):
        msg = build_user_message(feature_issue, spec_summaries)
        assert "GitHub Actions Suite" in msg
        assert "docs/specs/github-actions-suite.md" in msg

    def test_truncates_long_body(self, feature_issue, spec_summaries):
        feature_issue.body = "x" * 10000
        msg = build_user_message(feature_issue, spec_summaries)
        # Should be truncated to MAX_BODY_CHARS (8000)
        assert len(msg) < 12000

    def test_handles_empty_specs(self, feature_issue):
        msg = build_user_message(feature_issue, [])
        assert "(no specs found)" in msg

    def test_handles_empty_body(self, feature_issue, spec_summaries):
        feature_issue.body = ""
        msg = build_user_message(feature_issue, spec_summaries)
        assert "(no body)" in msg


class TestParseClassificationResponse:
    def test_parses_valid_json(self):
        response = json.dumps(
            {
                "classification": "feature-request",
                "confidence": 0.92,
                "reasoning": "This describes new functionality.",
                "related_specs": [
                    {"path": "docs/specs/foo.md", "relevance": 0.8, "section": "3.2"}
                ],
                "suggested_labels": ["canon:feature-request"],
                "duplicate_of": None,
            }
        )
        result = parse_classification_response(response)
        assert result.classification == IssueCategory.FEATURE_REQUEST
        assert result.confidence == 0.92
        assert len(result.related_specs) == 1
        assert result.related_specs[0].path == "docs/specs/foo.md"
        assert result.related_specs[0].section == "3.2"

    def test_strips_markdown_fences(self):
        response = (
            "```json\n"
            + json.dumps(
                {
                    "classification": "bug-report",
                    "confidence": 0.85,
                    "reasoning": "Error traceback included.",
                    "related_specs": [],
                    "suggested_labels": [],
                    "duplicate_of": None,
                }
            )
            + "\n```"
        )
        result = parse_classification_response(response)
        assert result.classification == IssueCategory.BUG_REPORT

    def test_handles_all_categories(self):
        for category in IssueCategory:
            response = json.dumps(
                {
                    "classification": category.value,
                    "confidence": 0.5,
                    "reasoning": "test",
                    "related_specs": [],
                }
            )
            result = parse_classification_response(response)
            assert result.classification == category

    def test_raises_on_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            parse_classification_response("not json at all")

    def test_raises_on_invalid_category(self):
        response = json.dumps(
            {
                "classification": "invalid-category",
                "confidence": 0.5,
                "reasoning": "test",
                "related_specs": [],
            }
        )
        with pytest.raises(ValueError):
            parse_classification_response(response)
