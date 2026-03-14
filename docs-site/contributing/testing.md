# Testing

Canon uses pytest for backend tests. Tests mirror the `src/` directory structure.

## Running Tests

```bash
# Run all tests
make test

# Verbose output
make test-backend-v

# With coverage
make test-cov

# Run a specific test file
uv run pytest tests/test_parser.py

# Run a specific test
uv run pytest tests/test_parser.py::test_parse_frontmatter -v
```

## Test Structure

```
tests/
├── test_parser.py          # Spec parser tests
├── test_writer.py          # Spec writer tests
├── test_analyzer.py        # Agent analyzer tests
├── test_prompts.py         # Prompt builder tests
├── test_config.py          # Config parser tests
├── test_sync.py            # Ticket sync tests
├── test_verify.py          # Webhook signature tests
├── test_spec_utils.py      # Spec utility tests
└── ...
```

## Writing Tests

### Conventions

- Test files are named `test_<module>.py`
- Test functions are named `test_<behavior>`
- Use pytest fixtures for shared setup
- Use `unittest.mock.patch` or `pytest-mock` for mocking external calls

### Example

```python
import pytest
from canon.parser.parse import parse_spec

def test_parse_frontmatter():
    content = """---
title: "Test Spec"
status: draft
owner: test-user
---

# Test Spec

## 1. Background

Some background text.
"""
    doc = parse_spec(content)
    assert doc.title == "Test Spec"
    assert doc.status == "draft"
    assert doc.owner == "test-user"
    assert len(doc.sections) == 1

def test_parse_acceptance_criteria():
    content = """---
title: "Test"
status: draft
---

# Test

## 1. Feature

### Acceptance Criteria

- [ ] First criterion
- [x] Second criterion
- [ ] Third criterion
"""
    doc = parse_spec(content)
    section = doc.sections[0]
    assert len(section.acceptance_criteria) == 3
    assert section.acceptance_criteria[0].checked is False
    assert section.acceptance_criteria[1].checked is True
```

### Mocking External Services

Tests should not make real API calls. Mock external services:

```python
from unittest.mock import AsyncMock, patch

@patch("canon.agent.client.ClaudeClient.analyze")
async def test_pr_analysis(mock_analyze):
    mock_analyze.return_value = {
        "summary": "Test summary",
        "specReferences": [],
        "discrepancies": [],
        "docUpdates": [],
        "realizations": [],
    }
    # ... test analysis pipeline
```

## Frontend Tests

```bash
# Type checking (acts as a basic validation)
make test-frontend

# E2E tests (requires Playwright)
make test-e2e
```
