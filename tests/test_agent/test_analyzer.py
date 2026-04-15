"""Port of pr-analyzer tests — JSON parsing, comment formatting, cost calc."""

from __future__ import annotations

import base64
import json
from typing import ClassVar
from unittest.mock import patch

from canon.agent.analyzer import (
    PARSE_FALLBACK_SUMMARY,
    ACRealization,
    DocUpdateSuggestion,
    PRAnalysisResult,
    RealizationStatus,
    SpecDiscrepancy,
    SpecReference,
    TokenUsage,
    _spec_link,
    estimate_cost,
    extract_analysis_data,
    format_analysis_comment,
    parse_analysis_response,
)


class TestParseAnalysisResponse:
    def test_parses_valid_json(self):
        response = json.dumps(
            {
                "summary": "This PR adds payment processing.",
                "specReferences": [
                    {
                        "specFile": "docs/specs/payments.md",
                        "sectionId": "2-stripe",
                        "sectionTitle": "Stripe Migration",
                        "relevance": "high",
                        "explanation": "PR modifies payment code",
                    }
                ],
                "discrepancies": [],
                "docUpdates": [],
            }
        )
        result = parse_analysis_response(response)
        assert result["summary"] == "This PR adds payment processing."
        assert len(result["spec_references"]) == 1
        assert result["spec_references"][0].relevance == "high"

    def test_strips_code_fences(self):
        response = '```json\n{"summary":"test","specReferences":[],"discrepancies":[],"docUpdates":[]}\n```'
        result = parse_analysis_response(response)
        assert result["summary"] == "test"

    def test_handles_malformed_json(self):
        """Unparseable input must return the stable fallback summary — NOT
        embed the raw model output. Previously the parser leaked short
        unparsed responses into the summary via an ``Analysis response
        (unparsed): ...`` prefix, which would then be posted verbatim as a
        PR comment. That's a publishing footgun — if Claude ever returned
        a refusal, apology, or sensitive content, it'd end up in a public
        bot comment. The fallback summary is now a stable constant
        regardless of input shape.
        """
        result = parse_analysis_response("not json at all")
        assert result["summary"] == PARSE_FALLBACK_SUMMARY
        assert "unparsed" not in result["summary"]
        assert "not json at all" not in result["summary"]

    def test_handles_empty_string(self):
        result = parse_analysis_response("")
        assert result["summary"] == PARSE_FALLBACK_SUMMARY

    def test_handles_long_unparseable_text(self):
        result = parse_analysis_response("x" * 600)
        assert result["summary"] == PARSE_FALLBACK_SUMMARY

    def test_parses_discrepancies(self):
        response = json.dumps(
            {
                "summary": "test",
                "specReferences": [],
                "discrepancies": [
                    {
                        "specFile": "spec.md",
                        "sectionId": "1-bg",
                        "sectionTitle": "Background",
                        "specSays": "Use REST",
                        "prDoes": "Uses GraphQL",
                        "severity": "conflict",
                        "suggestedSpecUpdate": "Update to GraphQL",
                    }
                ],
                "docUpdates": [],
            }
        )
        result = parse_analysis_response(response)
        assert len(result["discrepancies"]) == 1
        assert result["discrepancies"][0].severity == "conflict"

    def test_parses_doc_updates(self):
        response = json.dumps(
            {
                "summary": "test",
                "specReferences": [],
                "discrepancies": [],
                "docUpdates": [
                    {
                        "specFile": "spec.md",
                        "sectionId": "2-api",
                        "currentText": "old text",
                        "suggestedText": "new text",
                        "reason": "Outdated",
                    }
                ],
            }
        )
        result = parse_analysis_response(response)
        assert len(result["doc_updates"]) == 1
        assert result["doc_updates"][0].reason == "Outdated"

    def test_handles_missing_fields_gracefully(self):
        response = json.dumps({"summary": "partial"})
        result = parse_analysis_response(response)
        assert result["summary"] == "partial"
        assert result["spec_references"] == []
        assert result["discrepancies"] == []

    def test_non_string_summary_falls_back(self):
        response = json.dumps({"summary": 42})
        result = parse_analysis_response(response)
        assert result["summary"] == "Unable to parse analysis response."

    def test_no_coverage_note_in_result(self):
        response = json.dumps(
            {
                "summary": "test",
                "specReferences": [],
                "discrepancies": [],
                "docUpdates": [],
                "coverageNote": "This should be ignored",
            }
        )
        result = parse_analysis_response(response)
        assert "coverage_note" not in result


class TestParseAnalysisResponseRecoveryStrategies:
    """Ladder of extraction strategies the parser tries when the response
    has preamble, postamble, fences, or answer tags.

    These cases mirror the shapes we observed Claude actually returning on
    production runs with ~100k input tokens, where the model routinely
    ignores "respond with raw JSON only" in the system prompt and wraps
    its output. Before the fix, 85% of bot runs silently fell back to
    empty results.
    """

    _VALID_JSON_OBJ: ClassVar[dict] = {
        "summary": "recovered",
        "specReferences": [],
        "discrepancies": [],
        "docUpdates": [],
    }

    def _json(self) -> str:
        return json.dumps(self._VALID_JSON_OBJ)

    def test_preamble_before_json(self):
        """Model prepends prose before the JSON object — recovered via
        brace-slice strategy."""
        response = "Here's the analysis:\n\n" + self._json()
        result = parse_analysis_response(response)
        assert result["summary"] == "recovered"

    def test_postamble_after_json(self):
        """Model appends prose after the JSON object."""
        response = self._json() + "\n\nLet me know if you need adjustments."
        result = parse_analysis_response(response)
        assert result["summary"] == "recovered"

    def test_preamble_and_postamble(self):
        response = "I'll analyze this PR:\n" + self._json() + "\n\n— Claude"
        result = parse_analysis_response(response)
        assert result["summary"] == "recovered"

    def test_fence_with_preamble(self):
        """```json fence with surrounding prose — the old anchored regex
        failed here because ``^...$`` required the entire string to be
        the fence block."""
        response = "I'll analyze this PR:\n\n```json\n" + self._json() + "\n```\n\nDone!"
        result = parse_analysis_response(response)
        assert result["summary"] == "recovered"

    def test_unlabelled_fence_with_preamble(self):
        response = "Analysis:\n```\n" + self._json() + "\n```\nEnd."
        result = parse_analysis_response(response)
        assert result["summary"] == "recovered"

    def test_answer_tags(self):
        """Some thinking-mode responses wrap final output in
        ``<answer>...</answer>``."""
        response = "<answer>\n" + self._json() + "\n</answer>"
        result = parse_analysis_response(response)
        assert result["summary"] == "recovered"

    def test_answer_tags_with_thinking_preamble(self):
        response = (
            "Let me think about this...\n\n"
            "The PR modifies auth code.\n\n"
            "<answer>\n" + self._json() + "\n</answer>"
        )
        result = parse_analysis_response(response)
        assert result["summary"] == "recovered"

    def test_json_array_root_falls_through(self):
        """A valid JSON *array* is not the expected shape — parser moves
        on rather than treating ``[]`` as a dict."""
        response = "[1, 2, 3]"
        result = parse_analysis_response(response)
        assert result["summary"] == PARSE_FALLBACK_SUMMARY

    def test_json_string_root_falls_through(self):
        """A valid JSON *string* is not the expected shape."""
        response = '"just a string"'
        result = parse_analysis_response(response)
        assert result["summary"] == PARSE_FALLBACK_SUMMARY

    def test_multiple_fenced_blocks_picks_first(self):
        """If the model emits an example block before the real answer,
        the first fence wins. This is a known limitation worth
        documenting — if the first block is an example, the parser will
        return that. In practice, Claude rarely emits multiple fenced
        blocks in the PR analysis prompt."""
        first = json.dumps({**self._VALID_JSON_OBJ, "summary": "first"})
        second = json.dumps({**self._VALID_JSON_OBJ, "summary": "second"})
        response = f"```json\n{first}\n```\n\nAnd here's another:\n\n```json\n{second}\n```"
        result = parse_analysis_response(response)
        # Document current behavior — not necessarily the ideal. The fence
        # strategy picks the first block, not the last.
        assert result["summary"] == "first"


class TestParseAnalysisResponseReporting:
    """The parser MUST report parse failures to ops so they can be
    diagnosed. Historically it swallowed ``JSONDecodeError`` with no log
    and no analytics event, leaving 85% of production bot runs in the
    dark. These tests pin the reporting contract."""

    def test_emits_parse_failed_event_with_response_preview(self):
        """On total parse failure, emit a ``pr_analysis_parse_failed``
        PostHog event with the raw response preview so operators can
        actually see what Claude returned."""
        raw = "garbage that is definitely not JSON"
        with patch("canon.agent.analyzer.analytics.track") as mock_track:
            parse_analysis_response(raw)

        # Find the failure event (there may be others in the future).
        failure_calls = [
            c for c in mock_track.call_args_list if c.args[0] == "pr_analysis_parse_failed"
        ]
        assert len(failure_calls) == 1, (
            f"expected exactly one pr_analysis_parse_failed event, got {mock_track.call_args_list}"
        )
        props = failure_calls[0].kwargs["properties"]
        assert props["stage"] == "json_decode"
        assert props["error_type"] == "JSONDecodeError"
        assert props["response_length"] == len(raw)
        assert props["response_preview"] == raw
        assert props["error_message"]  # populated

    def test_truncates_response_preview_to_2000_chars(self):
        """Very long unparseable responses must not blow up the PostHog
        event — preview is capped at 2000 chars, but response_length
        reflects the true length so we can see outliers."""
        raw = "x" * 10_000
        with patch("canon.agent.analyzer.analytics.track") as mock_track:
            parse_analysis_response(raw)

        failure_call = next(
            c for c in mock_track.call_args_list if c.args[0] == "pr_analysis_parse_failed"
        )
        props = failure_call.kwargs["properties"]
        assert props["response_length"] == 10_000
        assert len(props["response_preview"]) == 2000

    def test_emits_parse_recovered_event_for_nontrivial_strategy(self):
        """When recovery via a non-direct strategy succeeds, emit a
        ``pr_analysis_parse_recovered`` event so we can measure how often
        the model is wrapping its output (and tune the prompt)."""
        response = "Here's the analysis:\n\n" + json.dumps(
            {
                "summary": "test",
                "specReferences": [],
                "discrepancies": [],
                "docUpdates": [],
            }
        )
        with patch("canon.agent.analyzer.analytics.track") as mock_track:
            parse_analysis_response(response)

        recovery_calls = [
            c for c in mock_track.call_args_list if c.args[0] == "pr_analysis_parse_recovered"
        ]
        assert len(recovery_calls) == 1
        props = recovery_calls[0].kwargs["properties"]
        assert props["strategy"] == "brace_slice"
        assert props["response_length"] == len(response)

    def test_direct_parse_emits_no_recovery_event(self):
        """Happy-path direct parses should not produce recovery events —
        those are meant to measure *drift*, not every successful run."""
        response = json.dumps(
            {
                "summary": "test",
                "specReferences": [],
                "discrepancies": [],
                "docUpdates": [],
            }
        )
        with patch("canon.agent.analyzer.analytics.track") as mock_track:
            parse_analysis_response(response)

        assert not any(
            c.args[0] == "pr_analysis_parse_recovered" for c in mock_track.call_args_list
        )
        assert not any(c.args[0] == "pr_analysis_parse_failed" for c in mock_track.call_args_list)

    def test_empty_response_does_not_emit_event(self):
        """Empty responses return fallback without firing a failure event
        — they're typically caused by API-level issues that are already
        reported elsewhere, and firing an event here would spam PostHog
        if the API flaps."""
        with patch("canon.agent.analyzer.analytics.track") as mock_track:
            parse_analysis_response("")

        assert mock_track.call_count == 0

    def test_analytics_failure_does_not_break_parser(self):
        """If analytics.track itself raises (PostHog outage, key
        misconfigured), the parser must still return a valid fallback
        rather than propagating the exception to the webhook handler."""
        with patch("canon.agent.analyzer.analytics.track", side_effect=RuntimeError("boom")):
            result = parse_analysis_response("not json")

        assert result["summary"] == PARSE_FALLBACK_SUMMARY


class TestFormatAnalysisComment:
    def _make_result(self, **overrides) -> PRAnalysisResult:
        defaults = {
            "summary": "This PR touches payments.",
            "spec_references": [],
            "discrepancies": [],
            "doc_updates": [],
            "tokens_used": TokenUsage(input=100, output=50),
        }
        return PRAnalysisResult(**{**defaults, **overrides})

    def test_header_is_canon(self):
        result = self._make_result()
        comment = format_analysis_comment(result)
        assert "## Canon" in comment

    def test_summary_is_blockquote(self):
        result = self._make_result()
        comment = format_analysis_comment(result)
        assert "> This PR touches payments." in comment

    def test_includes_spec_references_grouped(self):
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="docs/specs/auth-migration.md",
                    section_id="2-oauth",
                    section_title="OAuth Provider Integration",
                    relevance="high",
                    explanation="Modifies auth flow",
                )
            ]
        )
        comment = format_analysis_comment(result)
        assert "### Relevant Specs" in comment
        assert "**auth-migration**" in comment
        assert "| Section | |" in comment
        assert "OAuth Provider Integration" in comment
        assert "Modifies auth flow" in comment

    def test_groups_multiple_refs_from_same_spec(self):
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="docs/specs/web-app.md",
                    section_id="1-bg",
                    section_title="Background",
                    relevance="high",
                    explanation="Implements web app",
                ),
                SpecReference(
                    spec_file="docs/specs/web-app.md",
                    section_id="2-dashboard",
                    section_title="Dashboard",
                    relevance="high",
                    explanation="Adds dashboard routes",
                ),
                SpecReference(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    section_title="Login",
                    relevance="medium",
                    explanation="Touches auth flow",
                ),
            ]
        )
        comment = format_analysis_comment(result)
        # Should have two spec groups
        assert "**web-app**" in comment
        assert "**auth**" in comment
        # Both sections from web-app under the same group
        assert "Background" in comment
        assert "Dashboard" in comment

    def test_discrepancies_use_admonitions(self):
        result = self._make_result(
            discrepancies=[
                SpecDiscrepancy(
                    spec_file="spec.md",
                    section_id="1-bg",
                    section_title="Background",
                    spec_says="Use REST",
                    pr_does="Uses GraphQL",
                    severity="conflict",
                    suggested_spec_update="Update API spec",
                )
            ]
        )
        comment = format_analysis_comment(result)
        assert "> [!CAUTION]" in comment
        assert "### Discrepancies" in comment
        assert "Spec says: Use REST" in comment
        assert "PR does: Uses GraphQL" in comment

    def test_warning_discrepancy_uses_warning_admonition(self):
        result = self._make_result(
            discrepancies=[
                SpecDiscrepancy(
                    spec_file="spec.md",
                    section_id="1",
                    section_title="Test",
                    spec_says="a",
                    pr_does="b",
                    severity="warning",
                    suggested_spec_update="",
                )
            ]
        )
        comment = format_analysis_comment(result)
        assert "> [!WARNING]" in comment

    def test_filters_info_severity_discrepancies(self):
        result = self._make_result(
            discrepancies=[
                SpecDiscrepancy(
                    spec_file="spec.md",
                    section_id="1",
                    section_title="Test",
                    spec_says="a",
                    pr_does="b",
                    severity="info",
                    suggested_spec_update="",
                )
            ]
        )
        comment = format_analysis_comment(result)
        assert "Discrepancies" not in comment

    def test_doc_updates_use_diff_blocks(self):
        result = self._make_result(
            doc_updates=[
                DocUpdateSuggestion(
                    spec_file="docs/specs/auth.md",
                    section_id="2-api",
                    current_text="old text",
                    suggested_text="new text",
                    reason="Changed implementation",
                )
            ]
        )
        comment = format_analysis_comment(result)
        assert "### Suggested Updates" in comment
        assert "```diff" in comment
        assert "- old text" in comment
        assert "+ new text" in comment

    def test_filters_noop_doc_updates(self):
        result = self._make_result(
            doc_updates=[
                DocUpdateSuggestion(
                    spec_file="spec.md",
                    section_id="1",
                    current_text="same text",
                    suggested_text="same text",
                    reason="No real change",
                ),
                DocUpdateSuggestion(
                    spec_file="spec.md",
                    section_id="2",
                    current_text="  same text  ",
                    suggested_text="same text",
                    reason="Whitespace-only difference",
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert "Suggested Updates" not in comment

    def test_keeps_meaningful_doc_updates(self):
        result = self._make_result(
            doc_updates=[
                DocUpdateSuggestion(
                    spec_file="spec.md",
                    section_id="1",
                    current_text="same text",
                    suggested_text="same text",
                    reason="No real change",
                ),
                DocUpdateSuggestion(
                    spec_file="spec.md",
                    section_id="2",
                    current_text="old",
                    suggested_text="new",
                    reason="Real change",
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert "Suggested Updates" in comment
        assert "- old" in comment
        assert "+ new" in comment
        # The no-op update should not appear as a rendered diff block
        # (it may still appear in embedded JSON data)
        rendered = comment.split("<!-- canon-analysis-b64:")[0]
        assert "No real change" not in rendered

    def test_footer_format(self):
        result = self._make_result(tokens_used=TokenUsage(input=10200, output=758))
        comment = format_analysis_comment(result, model="claude-sonnet-4-6")
        assert "canon" in comment
        assert "sonnet" in comment
        assert "10.2k in" in comment
        assert "758 out" in comment
        assert "$" in comment
        assert "dismiss" in comment
        assert "reanalyze" in comment

    def test_preview_url_in_footer(self):
        result = self._make_result()
        comment = format_analysis_comment(result, preview_url="https://pr-39.canonhq.co")
        assert "[preview](https://pr-39.canonhq.co)" in comment

    def test_no_preview_url(self):
        result = self._make_result()
        comment = format_analysis_comment(result)
        assert "[preview]" not in comment

    def test_embeds_analysis_data(self):
        result = self._make_result()
        comment = format_analysis_comment(result)
        assert "<!-- canon-analysis-b64:" in comment

    def test_bot_marker(self):
        result = self._make_result()
        comment = format_analysis_comment(result)
        assert "<!-- canon-bot -->" in comment


class TestExtractAnalysisData:
    def test_extracts_b64_encoded_data(self):
        data = {"docUpdates": [{"specFile": "spec.md"}], "discrepancies": []}
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        comment = f"Some text\n<!-- canon-analysis-b64: {encoded} -->"
        result = extract_analysis_data(comment)
        assert result is not None
        assert len(result["doc_updates"]) == 1

    def test_extracts_legacy_raw_json(self):
        data = {"docUpdates": [{"specFile": "spec.md"}], "discrepancies": []}
        comment = f"Some text\n<!-- canon-analysis: {json.dumps(data)} -->"
        result = extract_analysis_data(comment)
        assert result is not None
        assert len(result["doc_updates"]) == 1

    def test_returns_none_when_no_marker(self):
        assert extract_analysis_data("Regular comment") is None

    def test_returns_none_on_invalid_json(self):
        assert extract_analysis_data("<!-- canon-analysis: {bad json} -->") is None

    def test_b64_with_dashes_in_json(self):
        """Verify that em dashes and '--' in JSON don't break the comment."""
        data = {
            "docUpdates": [],
            "discrepancies": [],
            "realizations": [
                {"explanation": "PR doesn\u2019t modify cron job \u2014 retained as specified"}
            ],
        }
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        comment = f"<!-- canon-analysis-b64: {encoded} -->"
        result = extract_analysis_data(comment)
        assert result is not None
        assert len(result["realizations"]) == 1


class TestFormatCommentHeading:
    def _make_result(self, **overrides) -> PRAnalysisResult:
        defaults = {
            "summary": "Test summary.",
            "spec_references": [],
            "discrepancies": [],
            "doc_updates": [],
            "tokens_used": TokenUsage(input=100, output=50),
        }
        return PRAnalysisResult(**{**defaults, **overrides})

    def test_format_comment_with_non_spec_refs(self):
        """When references include non-spec files, heading says 'Relevant Documents'."""
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="docs/adrs/0001-auth.md",
                    section_id="decision",
                    section_title="Decision",
                    relevance="high",
                    explanation="Contradicts ADR",
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert "### Relevant Documents" in comment
        assert "### Relevant Specs" not in comment

    def test_format_comment_with_only_spec_refs(self):
        """When all references are spec files, heading says 'Relevant Specs'."""
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    section_title="Login",
                    relevance="high",
                    explanation="Implements login",
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert "### Relevant Specs" in comment
        assert "### Relevant Documents" not in comment

    def test_format_comment_mixed_refs(self):
        """When references are mixed, heading says 'Relevant Documents'."""
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    section_title="Login",
                    relevance="high",
                    explanation="Implements login",
                ),
                SpecReference(
                    spec_file="docs/adrs/0001.md",
                    section_id="decision",
                    section_title="Decision",
                    relevance="medium",
                    explanation="Related ADR",
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert "### Relevant Documents" in comment
        assert "### Relevant Specs" not in comment


class TestParseRealizationsFromResponse:
    def test_parses_realizations_from_json(self):
        response = json.dumps(
            {
                "summary": "This PR implements retry logic.",
                "specReferences": [],
                "discrepancies": [],
                "docUpdates": [],
                "realizations": [
                    {
                        "specFile": "docs/specs/payments.md",
                        "sectionId": "3-retry",
                        "sectionTitle": "Retry & Error Handling",
                        "acText": "Exponential backoff with jitter",
                        "status": "realized",
                        "evidenceFiles": [{"path": "src/retry.py", "startLine": 42, "endLine": 60}],
                        "explanation": "Implements exponential backoff",
                    }
                ],
            }
        )
        result = parse_analysis_response(response)
        assert len(result["realizations"]) == 1
        r = result["realizations"][0]
        assert r.spec_file == "docs/specs/payments.md"
        assert r.ac_text == "Exponential backoff with jitter"
        assert r.status == RealizationStatus.REALIZED
        assert r.evidence_files == [{"path": "src/retry.py", "startLine": 42, "endLine": 60}]

    def test_parses_multiple_realization_statuses(self):
        response = json.dumps(
            {
                "summary": "test",
                "specReferences": [],
                "discrepancies": [],
                "docUpdates": [],
                "realizations": [
                    {
                        "specFile": "s.md",
                        "sectionId": "1",
                        "sectionTitle": "A",
                        "acText": "AC1",
                        "status": "realized",
                        "evidenceFiles": [],
                        "explanation": "",
                    },
                    {
                        "specFile": "s.md",
                        "sectionId": "1",
                        "sectionTitle": "A",
                        "acText": "AC2",
                        "status": "partially_realized",
                        "evidenceFiles": [],
                        "explanation": "missing X",
                    },
                    {
                        "specFile": "s.md",
                        "sectionId": "1",
                        "sectionTitle": "A",
                        "acText": "AC3",
                        "status": "conflicting",
                        "evidenceFiles": [],
                        "explanation": "contradicts",
                    },
                    {
                        "specFile": "s.md",
                        "sectionId": "1",
                        "sectionTitle": "A",
                        "acText": "AC4",
                        "status": "not_addressed",
                        "evidenceFiles": [],
                        "explanation": "",
                    },
                ],
            }
        )
        result = parse_analysis_response(response)
        assert len(result["realizations"]) == 4
        assert result["realizations"][0].status == RealizationStatus.REALIZED
        assert result["realizations"][1].status == RealizationStatus.PARTIALLY_REALIZED
        assert result["realizations"][2].status == RealizationStatus.CONFLICTING
        assert result["realizations"][3].status == RealizationStatus.NOT_ADDRESSED

    def test_defaults_to_empty_when_no_realizations_key(self):
        response = json.dumps(
            {
                "summary": "test",
                "specReferences": [],
                "discrepancies": [],
                "docUpdates": [],
            }
        )
        result = parse_analysis_response(response)
        assert result["realizations"] == []

    def test_skips_invalid_realization_entries(self):
        response = json.dumps(
            {
                "summary": "test",
                "specReferences": [],
                "discrepancies": [],
                "docUpdates": [],
                "realizations": [
                    {
                        "specFile": "s.md",
                        "sectionId": "1",
                        "sectionTitle": "A",
                        "acText": "Valid",
                        "status": "realized",
                        "evidenceFiles": [],
                        "explanation": "",
                    },
                    {
                        "specFile": "s.md",
                        "sectionId": "1",
                        "sectionTitle": "A",
                        "acText": "Bad",
                        "status": "invalid_status",
                        "evidenceFiles": [],
                        "explanation": "",
                    },
                ],
            }
        )
        result = parse_analysis_response(response)
        assert len(result["realizations"]) == 1
        assert result["realizations"][0].ac_text == "Valid"

    def test_handles_camelcase_mapping(self):
        response = json.dumps(
            {
                "summary": "test",
                "specReferences": [],
                "discrepancies": [],
                "docUpdates": [],
                "realizations": [
                    {
                        "specFile": "spec.md",
                        "sectionId": "2-api",
                        "sectionTitle": "API",
                        "acText": "Has auth",
                        "status": "realized",
                        "evidenceFiles": [{"path": "auth.py", "startLine": 10, "endLine": 20}],
                        "explanation": "Auth implemented",
                    }
                ],
            }
        )
        result = parse_analysis_response(response)
        r = result["realizations"][0]
        assert r.spec_file == "spec.md"
        assert r.section_id == "2-api"
        assert r.section_title == "API"
        assert r.ac_text == "Has auth"


class TestFormatRealizationTable:
    def _make_result(self, **overrides) -> PRAnalysisResult:
        defaults = {
            "summary": "Test summary.",
            "spec_references": [],
            "discrepancies": [],
            "doc_updates": [],
            "tokens_used": TokenUsage(input=100, output=50),
        }
        return PRAnalysisResult(**{**defaults, **overrides})

    def test_renders_realization_table(self):
        result = self._make_result(
            realizations=[
                ACRealization(
                    spec_file="docs/specs/payments.md",
                    section_id="3-retry",
                    section_title="Retry & Error Handling",
                    ac_text="Exponential backoff with jitter",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "src/retry.py", "start_line": 42, "end_line": 60}],
                    explanation="",
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert "### Realization Status" in comment
        assert "Retry & Error Handling" in comment
        assert "| AC | Status | Evidence |" in comment
        assert "Exponential backoff with jitter" in comment
        assert ":white_check_mark: Realized" in comment
        assert "`src/retry.py:42-60`" in comment

    def test_renders_partial_and_conflicting(self):
        result = self._make_result(
            realizations=[
                ACRealization(
                    spec_file="s.md",
                    section_id="1",
                    section_title="Sec",
                    ac_text="AC partial",
                    status=RealizationStatus.PARTIALLY_REALIZED,
                    evidence_files=[{"path": "f.py", "start_line": 10}],
                ),
                ACRealization(
                    spec_file="s.md",
                    section_id="1",
                    section_title="Sec",
                    ac_text="AC conflict",
                    status=RealizationStatus.CONFLICTING,
                    evidence_files=[],
                    explanation="contradicts spec",
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert ":large_orange_diamond: Partial" in comment
        assert ":warning: Conflicting" in comment
        assert "contradicts spec" in comment

    def test_renders_not_addressed(self):
        result = self._make_result(
            realizations=[
                ACRealization(
                    spec_file="s.md",
                    section_id="1",
                    section_title="Sec",
                    ac_text="Unrelated AC",
                    status=RealizationStatus.NOT_ADDRESSED,
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert ":white_large_square: Not addressed" in comment

    def test_groups_by_spec_and_section(self):
        result = self._make_result(
            realizations=[
                ACRealization(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    section_title="Login",
                    ac_text="OAuth support",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "auth.py"}],
                ),
                ACRealization(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    section_title="Login",
                    ac_text="Session management",
                    status=RealizationStatus.NOT_ADDRESSED,
                ),
                ACRealization(
                    spec_file="docs/specs/payments.md",
                    section_id="2-flow",
                    section_title="Flow",
                    ac_text="Stripe integration",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "pay.py", "start_line": 1, "end_line": 10}],
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert "**auth**" in comment
        assert "**payments**" in comment
        assert "Login" in comment
        assert "Flow" in comment

    def test_no_realization_section_when_empty(self):
        result = self._make_result(realizations=[])
        comment = format_analysis_comment(result)
        assert "### Realization Status" not in comment

    def test_embedded_data_includes_realizations(self):
        result = self._make_result(
            realizations=[
                ACRealization(
                    spec_file="s.md",
                    section_id="1",
                    section_title="T",
                    ac_text="test",
                    status=RealizationStatus.REALIZED,
                ),
            ]
        )
        comment = format_analysis_comment(result)
        data = extract_analysis_data(comment)
        assert data is not None
        assert len(data["realizations"]) == 1
        assert data["realizations"][0]["status"] == "realized"

    def test_escapes_pipe_in_ac_text(self):
        result = self._make_result(
            realizations=[
                ACRealization(
                    spec_file="s.md",
                    section_id="1",
                    section_title="Sec",
                    ac_text="A | B should work",
                    status=RealizationStatus.REALIZED,
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert "A \\| B should work" in comment

    def test_evidence_with_start_line_only(self):
        result = self._make_result(
            realizations=[
                ACRealization(
                    spec_file="s.md",
                    section_id="1",
                    section_title="Sec",
                    ac_text="Test AC",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "f.py", "start_line": 42}],
                ),
            ]
        )
        comment = format_analysis_comment(result)
        assert "`f.py:42`" in comment


class TestSpecLink:
    def test_returns_plain_text_when_no_base_url(self):
        assert _spec_link("", "owner", "repo", "docs/specs/auth.md", "auth") == "auth"

    def test_returns_plain_text_when_no_owner(self):
        assert _spec_link("https://app.com", "", "repo", "spec.md", "spec") == "spec"

    def test_returns_plain_text_when_no_repo(self):
        assert _spec_link("https://app.com", "owner", "", "spec.md", "spec") == "spec"

    def test_returns_link_with_base_url(self):
        result = _spec_link(
            "https://canonhq.co",
            "acme",
            "myrepo",
            "docs/specs/auth.md",
            "auth",
        )
        assert result == "[auth](https://canonhq.co/acme/myrepo/edit/docs/specs/auth.md)"

    def test_returns_link_with_section_id(self):
        result = _spec_link(
            "https://canonhq.co",
            "acme",
            "myrepo",
            "docs/specs/auth.md",
            "auth § 2-oauth",
            "2-oauth",
        )
        assert (
            result
            == "[auth § 2-oauth](https://canonhq.co/acme/myrepo/edit/docs/specs/auth.md#2-oauth)"
        )

    def test_strips_trailing_slash_from_base_url(self):
        result = _spec_link(
            "https://canonhq.co/",
            "acme",
            "myrepo",
            "docs/specs/auth.md",
            "auth",
        )
        assert "canonhq.co/acme/" in result
        assert "com//acme" not in result


class TestFormatCommentWithLinks:
    BASE = "https://canonhq.co"

    def _make_result(self, **overrides) -> PRAnalysisResult:
        defaults = {
            "summary": "Test summary.",
            "spec_references": [],
            "discrepancies": [],
            "doc_updates": [],
            "tokens_used": TokenUsage(input=100, output=50),
        }
        return PRAnalysisResult(**{**defaults, **overrides})

    def test_spec_references_become_links(self):
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    section_title="Login",
                    relevance="high",
                    explanation="Implements login",
                ),
            ]
        )
        comment = format_analysis_comment(
            result,
            base_url=self.BASE,
            owner="acme",
            repo="myrepo",
        )
        assert f"[auth]({self.BASE}/acme/myrepo/edit/docs/specs/auth.md)" in comment

    def test_discrepancy_links_include_section_anchor(self):
        result = self._make_result(
            discrepancies=[
                SpecDiscrepancy(
                    spec_file="docs/specs/auth.md",
                    section_id="2-oauth",
                    section_title="OAuth",
                    spec_says="Use REST",
                    pr_does="Uses GraphQL",
                    severity="conflict",
                    suggested_spec_update="",
                ),
            ]
        )
        comment = format_analysis_comment(
            result,
            base_url=self.BASE,
            owner="acme",
            repo="myrepo",
        )
        assert f"{self.BASE}/acme/myrepo/edit/docs/specs/auth.md#2-oauth)" in comment

    def test_suggested_updates_links_include_section_anchor(self):
        result = self._make_result(
            doc_updates=[
                DocUpdateSuggestion(
                    spec_file="docs/specs/auth.md",
                    section_id="2-api",
                    current_text="old text",
                    suggested_text="new text",
                    reason="Changed",
                ),
            ]
        )
        comment = format_analysis_comment(
            result,
            base_url=self.BASE,
            owner="acme",
            repo="myrepo",
        )
        assert f"{self.BASE}/acme/myrepo/edit/docs/specs/auth.md#2-api)" in comment

    def test_realization_links_include_section_anchor(self):
        result = self._make_result(
            realizations=[
                ACRealization(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    section_title="Login",
                    ac_text="OAuth support",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "auth.py"}],
                ),
            ]
        )
        comment = format_analysis_comment(
            result,
            base_url=self.BASE,
            owner="acme",
            repo="myrepo",
        )
        assert f"[auth]({self.BASE}/acme/myrepo/edit/docs/specs/auth.md#1-login)" in comment

    def test_view_in_canon_footer(self):
        result = self._make_result()
        comment = format_analysis_comment(
            result,
            base_url=self.BASE,
            owner="acme",
            repo="myrepo",
        )
        assert f"[View in Canon]({self.BASE}/acme/myrepo)" in comment

    def test_no_links_when_base_url_empty(self):
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    section_title="Login",
                    relevance="high",
                    explanation="Implements login",
                ),
            ]
        )
        comment = format_analysis_comment(result)
        # Should have plain text, not links
        assert "**auth**" in comment
        assert "View in Canon" not in comment

    def test_no_links_when_base_url_none_equivalent(self):
        """Passing base_url='' is the default and should produce no links."""
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    section_title="Login",
                    relevance="high",
                    explanation="Implements login",
                ),
            ]
        )
        comment = format_analysis_comment(result, base_url="", owner="acme", repo="myrepo")
        assert "](http" not in comment
        assert "View in Canon" not in comment


class TestFormatAnalysisCommentDocPatterns:
    """Test format_analysis_comment with the doc_patterns parameter."""

    def _make_result(self, **overrides) -> PRAnalysisResult:
        defaults = {
            "summary": "PR touches custom paths.",
            "spec_references": [],
            "discrepancies": [],
            "doc_updates": [],
            "tokens_used": TokenUsage(input=100, output=50),
        }
        return PRAnalysisResult(**{**defaults, **overrides})

    def test_custom_patterns_classifies_spec_heading(self):
        """With custom doc_patterns, spec refs matching patterns get 'Relevant Specs' heading."""
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="design/auth.md",
                    section_id="1-bg",
                    section_title="Background",
                    relevance="high",
                    explanation="Custom path spec",
                ),
            ]
        )
        comment = format_analysis_comment(result, doc_patterns=["design/*.md"])
        assert "### Relevant Specs" in comment

    def test_custom_patterns_non_spec_gets_documents_heading(self):
        """With custom doc_patterns, refs NOT matching patterns get 'Relevant Documents'."""
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="design/auth.md",
                    section_id="1-bg",
                    section_title="Background",
                    relevance="high",
                    explanation="Matches pattern",
                ),
                SpecReference(
                    spec_file="other/guide.md",
                    section_id="2-setup",
                    section_title="Setup",
                    relevance="medium",
                    explanation="Does not match pattern",
                ),
            ]
        )
        comment = format_analysis_comment(result, doc_patterns=["design/*.md"])
        assert "### Relevant Documents" in comment

    def test_none_patterns_falls_back_to_hardcoded(self):
        """With doc_patterns=None, falls back to docs/specs/ prefix check."""
        result = self._make_result(
            spec_references=[
                SpecReference(
                    spec_file="docs/specs/auth.md",
                    section_id="1-bg",
                    section_title="Background",
                    relevance="high",
                    explanation="Default path",
                ),
            ]
        )
        comment = format_analysis_comment(result, doc_patterns=None)
        assert "### Relevant Specs" in comment


class TestEstimateCost:
    def test_zero_tokens(self):
        assert estimate_cost(0, 0) == "0.0000"

    def test_known_values(self):
        # 1000 input * 0.8 + 500 output * 4.0 = 800 + 2000 = 2800
        # 2800 / 1_000_000 = 0.0028
        assert estimate_cost(1000, 500) == "0.0028"
