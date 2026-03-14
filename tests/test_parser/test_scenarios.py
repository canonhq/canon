"""Tests for BDD scenario parsing."""

from __future__ import annotations

from canon.parser import parse_scenarios, parse_spec
from canon.parser.parse import _extract_strength


class TestParseScenarios:
    def test_basic_scenario(self):
        content = """#### Scenario: User logs in

- GIVEN a registered user
- WHEN they submit valid credentials
- THEN they receive an auth token"""

        scenarios = parse_scenarios(content, 10)
        assert len(scenarios) == 1
        assert scenarios[0].name == "User logs in"
        assert len(scenarios[0].steps) == 3
        assert scenarios[0].steps[0].keyword == "GIVEN"
        assert scenarios[0].steps[0].text == "a registered user"
        assert scenarios[0].steps[1].keyword == "WHEN"
        assert scenarios[0].steps[2].keyword == "THEN"
        assert scenarios[0].steps[2].text == "they receive an auth token"

    def test_and_but_steps(self):
        content = """#### Scenario: Payment flow

- GIVEN a cart with items
- AND a valid payment method
- WHEN the user checks out
- THEN the order is created
- BUT the user is not charged twice"""

        scenarios = parse_scenarios(content, 1)
        assert len(scenarios[0].steps) == 5
        assert scenarios[0].steps[1].keyword == "AND"
        assert scenarios[0].steps[4].keyword == "BUT"

    def test_multiple_scenarios(self):
        content = """#### Scenario: Success path

- GIVEN valid input
- WHEN submitted
- THEN success

#### Scenario: Error path

- GIVEN invalid input
- WHEN submitted
- THEN error returned"""

        scenarios = parse_scenarios(content, 1)
        assert len(scenarios) == 2
        assert scenarios[0].name == "Success path"
        assert scenarios[1].name == "Error path"
        assert len(scenarios[1].steps) == 3

    def test_strength_detection_in_steps(self):
        content = """#### Scenario: Auth validation

- GIVEN a request without token
- WHEN the API is called
- THEN the system MUST return 401
- AND the response SHOULD include an error message"""

        scenarios = parse_scenarios(content, 1)
        assert scenarios[0].steps[2].strength == "MUST"
        assert scenarios[0].steps[3].strength == "SHOULD"
        assert scenarios[0].steps[0].strength is None

    def test_line_tracking(self):
        content = """Some preamble text

#### Scenario: Test

- GIVEN something
- THEN result"""

        scenarios = parse_scenarios(content, 10)
        assert scenarios[0].start_line == 12  # offset 10 + line index 2
        assert scenarios[0].steps[0].line == 14  # offset 10 + line index 4

    def test_case_insensitive_keywords(self):
        content = """#### Scenario: Mixed case

- given lowercase start
- When mixed case
- then lowercase end"""

        scenarios = parse_scenarios(content, 1)
        assert len(scenarios[0].steps) == 3
        assert scenarios[0].steps[0].keyword == "GIVEN"
        assert scenarios[0].steps[1].keyword == "WHEN"
        assert scenarios[0].steps[2].keyword == "THEN"

    def test_case_insensitive_scenario_heading(self):
        content = """#### scenario: lowercase heading

- GIVEN a condition
- THEN a result"""

        scenarios = parse_scenarios(content, 1)
        assert len(scenarios) == 1
        assert scenarios[0].name == "lowercase heading"
        assert len(scenarios[0].steps) == 2

    def test_empty_content(self):
        scenarios = parse_scenarios("", 1)
        assert scenarios == []

    def test_no_scenarios_in_content(self):
        content = """Just regular content.

- Regular list item
- Another item"""
        scenarios = parse_scenarios(content, 1)
        assert scenarios == []

    def test_scenario_with_blank_lines_between_steps(self):
        content = """#### Scenario: Spaced out

- GIVEN a condition

- WHEN action taken

- THEN result happens"""

        scenarios = parse_scenarios(content, 1)
        assert len(scenarios[0].steps) == 3

    def test_scenario_stops_at_non_step_content(self):
        content = """#### Scenario: Limited

- GIVEN a thing
- THEN a result

Some other content that is not a step."""

        scenarios = parse_scenarios(content, 1)
        assert len(scenarios[0].steps) == 2

    def test_integration_with_parse_spec(self):
        raw = """---
title: "BDD Spec"
status: draft
owner: test
team: test
---

# BDD Spec

## 1. Feature

#### Scenario: Happy path

- GIVEN valid input
- WHEN processed
- THEN output MUST be correct"""

        result = parse_spec(raw)
        section = result.document.sections[0]
        assert len(section.scenarios) == 1
        assert section.scenarios[0].name == "Happy path"
        assert section.scenarios[0].steps[2].strength == "MUST"


class TestExtractStrength:
    def test_must(self):
        assert _extract_strength("system MUST validate") == "MUST"

    def test_should(self):
        assert _extract_strength("API SHOULD cache") == "SHOULD"

    def test_may(self):
        assert _extract_strength("response MAY include") == "MAY"

    def test_must_not(self):
        assert _extract_strength("system MUST NOT leak") == "MUST_NOT"

    def test_should_not(self):
        assert _extract_strength("client SHOULD NOT retry") == "SHOULD_NOT"

    def test_no_strength(self):
        assert _extract_strength("regular text without keywords") is None

    def test_lowercase_not_matched(self):
        assert _extract_strength("it must work") is None

    def test_only_first_keyword_captured(self):
        """Multiple RFC 2119 keywords: only the first match is returned."""
        assert _extract_strength("system MUST NOT fail and SHOULD log") == "MUST_NOT"


class TestScenarioEdgeCases:
    def test_wrong_level_heading_not_parsed(self):
        """### Scenario: at h3 level should NOT be parsed as a scenario."""
        content = """### Scenario: Wrong level

- GIVEN a condition
- THEN a result"""

        scenarios = parse_scenarios(content, 1)
        assert scenarios == []

    def test_h5_heading_not_parsed(self):
        """##### Scenario: at h5 level should NOT be parsed."""
        content = """##### Scenario: Too deep

- GIVEN a condition
- THEN a result"""

        scenarios = parse_scenarios(content, 1)
        assert scenarios == []

    def test_heading_with_no_steps_skipped(self):
        """#### Scenario: heading followed by non-step content should be skipped."""
        content = """#### Scenario: Empty

Some regular text, not BDD steps.

#### Scenario: Has steps

- GIVEN something
- THEN result"""

        scenarios = parse_scenarios(content, 1)
        assert len(scenarios) == 1
        assert scenarios[0].name == "Has steps"
