---
name: canon-verify
description: Verify code against spec acceptance criteria (report or gate mode)
argument-hint: "[--gate] [section id]"
---

The user invoked `/canon-verify`. Use the Skill tool to invoke the **canon-verify** skill, which checks whether the current codebase satisfies a spec's acceptance criteria.

If $ARGUMENTS contains `--gate`, run in gate mode (pass/fail) instead of report mode. If it contains a section ID, scope verification to that section. The verify skill itself documents both modes — pass the user's intent through.
