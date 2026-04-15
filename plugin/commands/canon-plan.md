---
name: canon-plan
description: Spec-driven planning — explore, propose, spec, design, tasks, implementation plan
argument-hint: "[feature description or spec file]"
---

The user invoked `/canon-plan`. Use the Skill tool to invoke the **canon-plan** skill, which guides the user through the spec-driven planning workflow:

1. Explore the codebase for relevant context
2. Propose an approach
3. Create or update a spec
4. Add design details
5. Break into tasks
6. Optionally generate a file-level implementation plan executable by `canon-implement`

If $ARGUMENTS contains a feature description, start from Phase 1 (Explore). If it contains an existing spec file path, jump to Phase 5 (Tasks) or Phase 6 (Implementation Plan).
