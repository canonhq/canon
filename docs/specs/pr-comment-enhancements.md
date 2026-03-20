---
title: "PR Comment & Preview Enhancements"
status: done
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-03-04
tags: [pr-comments, preview, web-app, developer-experience]
---

# PR Comment & Preview Enhancements

Add Canon web app deep links to GitHub PR comments and enable preview deployments for the Spec Explorer web UI.

## 1. Background

<!-- specwright:system:1 status:done -->

When the Canon agent posts comments on PRs (spec coverage, analysis results), the comments don't link back to the Canon web app. Users have no easy way to navigate from a PR comment to the relevant spec in the editor. Additionally, the Spec Explorer web UI has no preview deployment capability — reviewers can't see UI changes before merging.

**Related:** [#94](https://github.com/canonhq/canon/issues/94), [#41](https://github.com/canonhq/canon/issues/41)

## 2. Web App Links in PR Comments

<!-- specwright:system:2 status:done -->

Update the GitHub comment templates in the agent/analyzer to include deep links to the Canon web app for each referenced spec.

### 2.1 Link Format

For each spec mentioned in a PR comment, include a link like:
`[View in Canon](https://canonhq.co/app/{org}/{repo}/specs/{spec-slug})`

### 2.2 Comment Sections to Update

- Spec coverage summary → link to org dashboard
- Per-spec analysis → link to individual spec view
- Acceptance criteria checklist → link to spec section

### Acceptance Criteria

- [x] PR comments include deep links to the Canon web app
<!-- specwright:realized-in:PR#117 file:src/specwright/agent/analyzer.py -->
- [x] Links point to the correct spec/section in the web app
<!-- specwright:realized-in:PR#117 file:tests/test_agent/test_analyzer.py -->
- [x] Links use the configured Canon domain (not hardcoded)
<!-- specwright:realized-in:PR#117 file:src/specwright/settings.py -->
<!-- specwright:realized-in:PR#117 file:src/specwright/github/handlers/on_pull_request.py -->
<!-- specwright:realized-in:PR#298 file:chart/specwright/templates/configmap.yaml -->
<!-- specwright:realized-in:PR#298 file:chart/specwright/values.yaml -->
- [x] Comments degrade gracefully if web app URL is not configured (omit links, don't error)
<!-- specwright:realized-in:PR#117 file:src/specwright/agent/analyzer.py -->
- [x] Existing PR comment formatting is preserved
<!-- specwright:realized-in:PR#117 file:tests/test_agent/test_analyzer.py -->

## 3. Preview Deployments for Spec Explorer

<!-- specwright:system:3 status:done -->

Enable preview deployments for the Spec Explorer web UI so reviewers can see UI changes before merging. The main webhook handler cannot be previewed (single webhook URL), but the read-only web UI can.

### 3.1 Approach

- Build and deploy the web UI (Jinja2 templates + static assets) as a standalone preview
- Preview connects to the production GitHub App for data (read-only)
- Preview URL posted as a PR comment or GitHub deployment status

### Acceptance Criteria

- [x] PRs that modify `templates/` or `static/` files trigger a preview deployment
<!-- specwright:realized-in:PR#298 file:.github/workflows/preview.yml -->
<!-- specwright:realized-in file:.github/workflows/preview.yml -->
- [x] Preview URL is accessible and shows the updated UI
<!-- specwright:realized-in:PR#298 file:chart/specwright/values-preview.yaml -->
<!-- specwright:realized-in file:chart/specwright/values-preview.yaml -->
- [x] Preview connects to production data source (read-only)
<!-- specwright:realized-in file:.github/workflows/preview.yml -->
- [x] Preview deployments are cleaned up after PR merge/close
<!-- specwright:realized-in file:.github/workflows/preview.yml -->
- [x] Preview URL is posted as a GitHub deployment status or PR comment
<!-- specwright:realized-in:PR#298 file:src/specwright/github/handlers/on_pull_request.py -->
<!-- specwright:realized-in:PR#298 file:src/specwright/github/client.py -->
<!-- specwright:realized-in file:src/specwright/github/handlers/on_pull_request.py -->
<!-- specwright:realized-in file:.github/workflows/preview.yml -->

## 4. Resolved Questions

- **Hosting:** K8s ephemeral namespace on existing DOKS cluster (`canon-preview-{pr_number}`)
- **GitHub App:** Production installation (web UI is read-only, no webhook conflict)
- **Auth:** Same Auth0 tenant with wildcard callback URL (`https://pr-*.canonhq.co/auth/callback`)
