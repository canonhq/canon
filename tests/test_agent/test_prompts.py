"""Port of prompts tests — token estimation, message building."""

from __future__ import annotations

from canon.agent.prompts import (
    BASE_SYSTEM_PROMPT,
    REALIZATION_JSON_SCHEMA,
    REALIZATION_PROMPT_SECTION,
    SYSTEM_PROMPT,
    ContextDoc,
    PRAnalysisContext,
    PRFile,
    RepoSpec,
    build_user_message,
    estimate_tokens,
)
from canon.parser.models import (
    AcceptanceCriterion,
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
)


def _make_context(
    *,
    specs: list[RepoSpec] | None = None,
    files: list[PRFile] | None = None,
    body: str | None = "PR description",
) -> PRAnalysisContext:
    return PRAnalysisContext(
        pr=PRAnalysisContext.PRInfo(
            number=42,
            title="Add payment flow",
            body=body,
            author="alice",
            base_branch="main",
            head_branch="feat/payments",
            url="https://github.com/org/repo/pull/42",
        ),
        files=files or [],
        specs=specs or [],
    )


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        # "hello" = 5 chars → ceil(5/4) = 2
        assert estimate_tokens("hello") == 2

    def test_longer_string(self):
        text = "a" * 100
        assert estimate_tokens(text) == 25


class TestBuildUserMessage:
    def test_includes_pr_metadata(self):
        context = _make_context()
        msg = build_user_message(context)
        assert "#42" in msg
        assert "Add payment flow" in msg
        assert "alice" in msg
        assert "feat/payments" in msg

    def test_includes_pr_body(self):
        context = _make_context(body="This fixes the checkout bug")
        msg = build_user_message(context)
        assert "This fixes the checkout bug" in msg

    def test_shows_no_specs_message_when_empty(self):
        context = _make_context(specs=[])
        msg = build_user_message(context)
        assert "No spec documents found" in msg

    def test_includes_spec_summaries(self):
        spec = RepoSpec(
            file_path="docs/specs/payments.md",
            document=SpecDocument(
                file_path="docs/specs/payments.md",
                frontmatter=SpecFrontmatter(
                    title="Payments", status="in_progress", owner="sarah", team="payments"
                ),
                sections=[
                    SpecSection(
                        id="1-background",
                        section_number="1",
                        title="Background",
                        depth=2,
                        content="Context here.",
                        status=SectionStatus(state="done"),
                        children=[],
                        start_line=10,
                        end_line=15,
                    )
                ],
                raw="",
            ),
        )
        context = _make_context(specs=[spec])
        msg = build_user_message(context)
        assert "payments.md" in msg
        assert "Background" in msg

    def test_includes_file_list(self):
        files = [
            PRFile(
                filename="src/payments.ts",
                status="modified",
                additions=10,
                deletions=5,
            )
        ]
        context = _make_context(files=files)
        msg = build_user_message(context)
        assert "src/payments.ts" in msg
        assert "+10" in msg

    def test_includes_diffs_within_budget(self):
        files = [
            PRFile(
                filename="small.ts",
                status="modified",
                patch="+ added line\n- removed line",
                additions=1,
                deletions=1,
            )
        ]
        context = _make_context(files=files)
        msg = build_user_message(context)
        assert "```diff" in msg
        assert "+ added line" in msg

    def test_omits_diffs_exceeding_budget(self):
        files = [
            PRFile(
                filename="big.ts",
                status="modified",
                patch="x" * 30000,
                additions=100,
                deletions=100,
            )
        ]
        context = _make_context(files=files)
        msg = build_user_message(context, max_diff_chars=100)
        assert "omitted due to size limits" in msg

    def test_system_prompt_is_defined(self):
        assert "Canon" in SYSTEM_PROMPT
        assert "JSON" in SYSTEM_PROMPT

    def test_system_prompt_mentions_context_documents(self):
        assert "context documents" in SYSTEM_PROMPT

    def test_includes_context_docs_section(self):
        context = _make_context()
        context.context_docs = [
            ContextDoc(
                path="docs/adrs/0001-auth.md",
                doc_title="ADR 1: Auth",
                heading="Decision",
                body="We chose OAuth2.",
                score=0.85,
            ),
        ]
        msg = build_user_message(context)
        assert "## Related Documents" in msg
        assert "docs/adrs/0001-auth.md" in msg
        assert "ADR 1: Auth" in msg
        assert "We chose OAuth2." in msg

    def test_context_docs_empty_by_default(self):
        context = _make_context()
        msg = build_user_message(context)
        assert "## Related Documents" not in msg


class TestSystemPromptComposition:
    def test_system_prompt_contains_base(self):
        assert BASE_SYSTEM_PROMPT in SYSTEM_PROMPT

    def test_system_prompt_contains_realization_section(self):
        assert REALIZATION_PROMPT_SECTION in SYSTEM_PROMPT

    def test_system_prompt_contains_realization_json_schema(self):
        assert REALIZATION_JSON_SCHEMA in SYSTEM_PROMPT

    def test_realization_prompt_mentions_statuses(self):
        assert "realized" in REALIZATION_PROMPT_SECTION
        assert "partially_realized" in REALIZATION_PROMPT_SECTION
        assert "conflicting" in REALIZATION_PROMPT_SECTION
        assert "not_addressed" in REALIZATION_PROMPT_SECTION

    def test_realization_json_schema_has_required_fields(self):
        assert "acText" in REALIZATION_JSON_SCHEMA
        assert "evidenceFiles" in REALIZATION_JSON_SCHEMA
        assert "specFile" in REALIZATION_JSON_SCHEMA


class TestSectionSummaryWithAC:
    def test_includes_unchecked_ac_in_summary(self):
        spec = RepoSpec(
            file_path="docs/specs/auth.md",
            document=SpecDocument(
                file_path="docs/specs/auth.md",
                frontmatter=SpecFrontmatter(
                    title="Auth", status="in_progress", owner="test", team="test"
                ),
                sections=[
                    SpecSection(
                        id="1-login",
                        section_number="1",
                        title="Login",
                        depth=2,
                        content="Login flow.",
                        status=SectionStatus(state="in_progress"),
                        acceptance_criteria=[
                            AcceptanceCriterion(text="OAuth support", checked=False, line=10),
                            AcceptanceCriterion(text="Session management", checked=True, line=11),
                        ],
                        children=[],
                        start_line=5,
                        end_line=15,
                    )
                ],
                raw="",
            ),
        )
        context = _make_context(specs=[spec])
        msg = build_user_message(context)
        assert "- [ ] OAuth support" in msg
        assert "- [x] Session management" in msg

    def test_no_ac_lines_when_no_criteria(self):
        spec = RepoSpec(
            file_path="docs/specs/auth.md",
            document=SpecDocument(
                file_path="docs/specs/auth.md",
                frontmatter=SpecFrontmatter(
                    title="Auth", status="draft", owner="test", team="test"
                ),
                sections=[
                    SpecSection(
                        id="1-bg",
                        section_number="1",
                        title="Background",
                        depth=2,
                        content="Context.",
                        status=SectionStatus(state="draft"),
                        acceptance_criteria=[],
                        children=[],
                        start_line=5,
                        end_line=10,
                    )
                ],
                raw="",
            ),
        )
        context = _make_context(specs=[spec])
        msg = build_user_message(context)
        assert "- [ ]" not in msg
        assert "- [x]" not in msg

    def test_child_section_ac_included(self):
        spec = RepoSpec(
            file_path="docs/specs/auth.md",
            document=SpecDocument(
                file_path="docs/specs/auth.md",
                frontmatter=SpecFrontmatter(
                    title="Auth", status="in_progress", owner="test", team="test"
                ),
                sections=[
                    SpecSection(
                        id="1-auth",
                        section_number="1",
                        title="Auth",
                        depth=2,
                        content="Auth section.",
                        status=SectionStatus(state="in_progress"),
                        acceptance_criteria=[],
                        children=[
                            SpecSection(
                                id="1.1-login",
                                section_number="1.1",
                                title="Login",
                                depth=3,
                                content="Login flow.",
                                status=SectionStatus(state="todo"),
                                acceptance_criteria=[
                                    AcceptanceCriterion(
                                        text="Child AC item", checked=False, line=20
                                    ),
                                ],
                                children=[],
                                start_line=15,
                                end_line=25,
                            )
                        ],
                        start_line=5,
                        end_line=25,
                    )
                ],
                raw="",
            ),
        )
        context = _make_context(specs=[spec])
        msg = build_user_message(context)
        assert "- [ ] Child AC item" in msg
