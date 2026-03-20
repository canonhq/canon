---
title: "Spec Review Workflow"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-02-26
tags: [workflow, review, collaboration]
---

# Spec Review Workflow

Define and implement a structured review process for specs — from draft through approval — with role-based reviews, async commenting, and status gates.

## 1. Background

<!-- specwright:system:1 status:done -->

Today specs are just files in a repo with no review gates. Anyone can merge a spec change without sign-off. The vision: async, in-platform reviews where engineering leads review for feasibility, design reviews for UX, and PMs review for requirements coverage. Review status should gate ticket generation — only approved specs produce tickets.

**Related:** [#19](https://github.com/canonhq/canon/issues/19)

## 2. Review States

<!-- specwright:system:2 status:done -->

### 2.1 Spec Lifecycle

```
draft → in_review → approved → active
                  ↘ changes_requested → draft (revise and re-submit)
```

### 2.2 Review Roles

| Role | Reviews For | Required? |
|---|---|---|
| PM / Product | Requirements completeness, user stories | Yes |
| Engineering Lead | Technical feasibility, architecture fit | Yes |
| Design | UX/UI considerations (when applicable) | Optional |

### Acceptance Criteria

- [ ] Spec status supports `in_review` and `changes_requested` states
- [ ] Specs can be submitted for review (status transition: draft → in_review)
- [ ] Reviewers can approve or request changes
- [ ] All required review roles must approve before spec reaches `approved`
- [ ] Review status is tracked in spec frontmatter or status comments
- [ ] Only `approved` specs trigger automatic ticket generation (when `auto_tickets: true`)

<!-- canon:ticket:github:428 -->
## 3. Review Interface

<!-- canon:system:3 status:in_progress -->

### 3.1 GitHub-Native Option

Use GitHub Pull Requests as the review mechanism:
- Spec changes submitted as PRs
- GitHub PR reviews provide the approval/request-changes workflow
- Canon bot enforces required reviewers based on `CANON.yaml` config
- Bot updates spec status based on PR review outcome

### 3.2 In-Platform Option

Build review UI in the Spec Explorer web app:
- Review dashboard showing specs awaiting review
- Inline commenting on spec sections
- Approve/request-changes buttons per reviewer role
- Review history and audit trail

### Acceptance Criteria

- [ ] Review interface chosen (GitHub-native PR reviews or in-platform)
- [ ] Reviewers can leave comments on specific spec sections
- [ ] Review decisions (approve/request-changes) are recorded with timestamp and reviewer
- [ ] Review history is visible in the spec or linked from it

## 4. Open Questions

- GitHub PR-based reviews vs. in-platform reviews? (PR reviews are simpler to implement but less discoverable for non-engineers)
- Should review requirements be configurable per-spec or per-team?
- How should review status interact with the existing spec section statuses?
