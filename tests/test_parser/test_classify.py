"""Tests for classify_doc_type shared utility."""

from __future__ import annotations

from canon.parser.classify import classify_doc_type


class TestClassifyDocType:
    def test_spec_path(self):
        assert classify_doc_type("docs/specs/payments.md") == "spec"

    def test_spec_path_nested(self):
        assert classify_doc_type("docs/specs/infra/deploy.md") == "spec"

    def test_adr_path(self):
        assert classify_doc_type("docs/adrs/0001-auth.md") == "adr"

    def test_adr_in_path(self):
        assert classify_doc_type("architecture/adr-decisions/0005.md") == "adr"

    def test_readme(self):
        assert classify_doc_type("README.md") == "readme"

    def test_readme_nested(self):
        assert classify_doc_type("src/components/README.md") == "readme"

    def test_changelog(self):
        assert classify_doc_type("CHANGELOG.md") == "changelog"

    def test_contributing(self):
        assert classify_doc_type("CONTRIBUTING.md") == "contributing"

    def test_runbook(self):
        assert classify_doc_type("ops/runbook-deploy.md") == "runbook"

    def test_playbook(self):
        assert classify_doc_type("ops/playbook-incident.md") == "runbook"

    def test_generic_doc(self):
        assert classify_doc_type("docs/api-guide.md") == "doc"

    def test_case_insensitive(self):
        assert classify_doc_type("DOCS/SPECS/Auth.md") == "spec"
        assert classify_doc_type("Docs/ADRs/0001.md") == "adr"
        assert classify_doc_type("Readme.md") == "readme"


class TestClassifyDocTypeWithPatterns:
    def test_custom_spec_patterns(self):
        patterns = ["design/*.md"]
        assert classify_doc_type("design/auth.md", spec_patterns=patterns) == "spec"

    def test_custom_patterns_non_spec(self):
        patterns = ["design/*.md"]
        assert classify_doc_type("docs/api-guide.md", spec_patterns=patterns) == "doc"

    def test_custom_patterns_still_classifies_adr(self):
        patterns = ["design/*.md"]
        assert classify_doc_type("docs/adrs/0001-auth.md", spec_patterns=patterns) == "adr"

    def test_default_path_not_matched_with_custom_patterns(self):
        patterns = ["design/*.md"]
        # docs/specs/auth.md would normally be "spec" but with custom patterns it's not
        assert classify_doc_type("docs/specs/auth.md", spec_patterns=patterns) == "doc"
