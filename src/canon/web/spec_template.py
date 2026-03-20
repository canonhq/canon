"""Default template for new spec documents."""

from __future__ import annotations

from datetime import date


def new_spec_template(*, title: str = "Untitled Spec", owner: str = "", team: str = "") -> str:
    """Generate a new spec document from the default template."""
    today = date.today().isoformat()
    return f"""---
title: {title}
status: draft
owner: {owner}
team: {team}
review_status: draft
created: "{today}"
tags: []
---

## 1. Overview

_Describe the feature or change at a high level._

## 2. Requirements

### Acceptance Criteria

- [ ] First acceptance criterion
- [ ] Second acceptance criterion

## 3. Design

_Technical design details._

## 4. Rollout Plan

_How this will be deployed and validated._
"""
