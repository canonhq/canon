---
title: "Multi-Org & Personal Account Support"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon-private
created: 2026-03-26
updated: 2026-03-26
tags: [auth, multi-tenant, onboarding, github-app]
---

# Multi-Org & Personal Account Support

When the Canon GitHub App is installed on a personal GitHub account (not an org),
the installation fails to provision an identity provider org and the web UI has no
way to scope the session to the personal account's repos. This spec covers fixing
the full install-to-dashboard flow for non-org GitHub accounts and improving
multi-org switching for users who belong to more than one installation.

## 1. Background

<!-- canon:system:1 status:done -->

Canon's GitHub App can be installed on any GitHub account (org or personal) when
the app visibility is set to "Any account." The `on_installation` webhook handler
registers the installation and kicks off three background tasks:

1. **Repo indexing** — works correctly for personal accounts.
2. **Auth0 org provisioning** — fails because it assumes every installation maps
   to an Auth0 Organization, but personal accounts don't have a meaningful org
   boundary in Auth0.
3. **Repo onboarding** — works correctly.

The web UI session is scoped to a single `org_login` resolved from the Auth0
access token's `org_id` claim. When Auth0 provisioning fails, the new
installation has no `oidc_org_id`, so the user's session never resolves to it.
Repos from the personal account get indexed but appear under whatever org the
user's existing session is scoped to (e.g., `canonhq`), creating a confusing
cross-org bleed in the Explorer.

**Observed symptoms (njgerner installing Canon on personal account):**
- PostHog logs: "Access token verification failed — permissions not extracted"
  followed by "Failed to provision Auth0 org for installation 119312249"
- Setup redirect lands on `canonhq.co/app/setup/` showing `canonhq` org context
- Repo dropdown shows `njgerner/dc-wedding-site (12)` under the `canonhq` heading
- No way to switch to an `njgerner`-scoped view

## 2. Auth Provider Provisioning for Personal Accounts

<!-- canon:system:2 status:todo -->

<!-- canon:ticket:github:570 -->
Fix `_provision_auth0_org` in `on_installation.py` to handle personal GitHub
accounts (where `account.type == "User"` rather than `"Organization"`).

### 2.1 Detect Account Type

<!-- canon:system:2.1 status:todo -->

<!-- canon:ticket:github:571 -->
The installation webhook payload includes `installation.account.type` which is
either `"Organization"` or `"User"`. Pass this through to the provisioning logic.

### 2.2 Personal Account Strategy

<!-- canon:system:2.2 status:todo -->

<!-- canon:ticket:github:572 -->
For personal accounts, either:
- **(a)** Create an Auth0 org named after the GitHub username (e.g., `njgerner`)
  — same flow as org installs, just with a user-scoped name. Simplest approach.
- **(b)** Skip Auth0 org creation entirely and use a direct user-to-installation
  mapping in the DB — avoids Auth0 org sprawl for individual users.

Option (a) is recommended for consistency — the rest of the system already
assumes every installation has an `oidc_org_id`.

### Acceptance Criteria

- [ ] Personal account installations successfully provision an identity org
- [ ] `registry.set_oidc_org_id` is called for personal account installations
- [ ] Auth0 provisioning failure for personal accounts is logged with actionable
      context (account type, login, specific error)
- [ ] Existing org installations are unaffected

## 3. Session Org Scoping & Switching

<!-- canon:system:3 status:todo -->

<!-- canon:ticket:github:573 -->
Users who belong to multiple installations (e.g., `canonhq` org + `njgerner`
personal) need a way to switch between them in the web UI.

### 3.1 Resolve Session Org from Installation

<!-- canon:system:3.1 status:todo -->

<!-- canon:ticket:github:574 -->
When a user logs in, if the access token doesn't contain an `org_id` (common
with personal account installations), fall back to looking up all installations
the user has access to and let them pick or auto-select.

### 3.2 Org Switcher UI

<!-- canon:system:3.2 status:todo -->

<!-- canon:ticket:github:575 -->
Add an org/account switcher to the web UI header (next to the user menu) that
lists all installations the current user has access to. Selecting one re-scopes
the session's `org_login` and reloads the Explorer.

### 3.3 Setup Redirect Scoping

<!-- canon:system:3.3 status:todo -->

<!-- canon:ticket:github:576 -->
The `/app/setup/` redirect after GitHub App installation should scope to the
newly installed account, not the user's existing session org. The GitHub OAuth
callback includes an `installation_id` parameter — use this to set the correct
`org_login` in the session before redirecting to the Explorer.

### Acceptance Criteria

- [ ] After installing the GitHub App on a personal account, the setup page shows
      that account's repos (not the previously-scoped org)
- [ ] Users with multiple installations can switch between them in the UI
- [ ] Org switcher shows both org and personal account installations
- [ ] Deep links like `/app/njgerner/` scope correctly

## 4. Cross-Org Repo Bleed Prevention

<!-- canon:system:4 status:todo -->

<!-- canon:ticket:github:577 -->
Repos from one installation should not appear under another installation's scope
in the Explorer.

### 4.1 Installation-Scoped Repo Queries

<!-- canon:system:4.1 status:todo -->

<!-- canon:ticket:github:578 -->
Explorer API queries must filter repos by the session's current
`installation_id`, not just `org_login`. This prevents `njgerner/dc-wedding-site`
from appearing under the `canonhq` Explorer view.

### 4.2 Index Isolation

<!-- canon:system:4.2 status:todo -->

<!-- canon:ticket:github:579 -->
Verify that the spec search index partitions results by installation. If the
index is shared, add an `installation_id` filter to search queries.

### Acceptance Criteria

- [ ] Repos from personal accounts only appear when that account is selected
- [ ] Repos from org installations don't leak into personal account views
- [ ] Search results respect installation boundaries

## 5. Open Questions

- Should personal account installations share an Auth0 org with an org
  installation if the GitHub username matches an org member? (Probably not —
  keep them separate.)
- Do we need rate limiting or a cap on personal account installations to prevent
  abuse in the managed cloud offering?
- Should the org switcher be a full page or a dropdown? (Dropdown is simpler for
  MVP.)
