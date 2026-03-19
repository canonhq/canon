---
title: "User Profile Page"
type: spec
status: in_progress
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-21
updated: 2026-03-03
tags: [web, auth, rbac, profile]
---

# User Profile Page

The user profile page (`/profile`) displays comprehensive identity and access information for authenticated users, including Auth0 roles, permissions, organization membership, and session details. This interface provides users with full transparency into their identity within Canon and their current access level.

## 1. Background

<!-- specwright:system:1 status:done -->

Canon currently lacks a user-facing interface for viewing identity and access information. The auth store maintains several user attributes—`sub`, `email`, `name`, `picture`, `org_login`, `permissions`, and `githubUser`—but these remain hidden from users.

RBAC-enabled applications require users to understand three critical aspects of their access:

- Their assigned role within the system
- The specific permissions granted to them
- Their organization membership and context

This visibility is essential as we deploy the Auth0 role-assignment Action and enable multi-organization support. Without this interface, users cannot verify their access level or troubleshoot permission issues.

## 2. Profile Header

<!-- specwright:system:2 status:done -->

The profile header presents the user's visual identity, including avatar, display name, email address, and GitHub account linkage.

### Acceptance Criteria

- [x] Display avatar image from Auth0 `picture` field (fallback to initials if unavailable)
- [x] Display user's full name and email address
- [x] Display GitHub username with link to GitHub profile (when `githubUser` is available)
- [x] Display Auth0 subject ID in a muted, copyable format for debugging purposes
- [x] Display "Last login" timestamp from `users.last_login_at` database field

## 3. Roles & Permissions

<!-- canon:system:3 status:in_progress -->

This section displays the user's current Auth0 permissions and inferred role. Permissions are derived from the session's `permissions` array, populated by Auth0 access token claims or the fallback logic in `deps.py`.

The interface presents both the user's effective role and the granular permissions that comprise it, enabling users to understand exactly what actions they can perform.

### Acceptance Criteria

- [x] Display inferred role as a badge (Viewer, Editor, or Admin) based on the user's permission set
- [ ] List all granted permissions with human-readable descriptions (e.g., `specs:read` → "Read access to specs")
- [x] Visually distinguish between granted and ungrantable permissions by showing the full Permission enum
- [x] Display authentication method (session, jwt, or api_key) indicating how the user authenticated
- [x] Include explanatory text noting that permissions are derived from Auth0 RBAC and organization membership

## 4. Organization & Access

<!-- canon:system:4 status:in_progress -->

This section displays the user's current organization context and enables switching between organizations when the user has multi-organization access.

### Acceptance Criteria

- [x] Display current organization name and slug
- [x] Provide organization switcher if user has access to multiple organizations (`orgs` array length > 1)
- [ ] Display Auth0 organization ID in debug/details section (when organization mode is enabled)
- [x] Provide link to organization dashboard filtered to the user's current organization

## 5. Backend API

<!-- canon:system:5 status:in_progress -->

The `GET /api/profile` endpoint returns a complete profile payload by combining session data with database-stored fields, providing a single source of truth for profile information.

### Acceptance Criteria

- [x] `GET /api/profile` returns JSON containing user identity, permissions, organization, and metadata
- [ ] Endpoint requires authentication and returns 401 for anonymous users
- [x] Response includes `last_login_at` from the `users` database table
- [x] Response conforms to the `ProfileResponse` Pydantic model

## 6. Frontend View

<!-- canon:system:6 status:in_progress -->

The Vue 3 view at `/profile` renders a comprehensive profile interface using modular components for each section. The view primarily consumes data from `useAuthStore()`, supplemented by an API call for database-stored fields not available in the session.

### Acceptance Criteria

- [x] Implement Vue route at `/profile` with `ProfileView.vue` component
- [x] Make profile page accessible from user avatar/menu in the navbar
- [ ] Implement responsive layout (single column on mobile, two columns on desktop)
- [x] Display loading skeleton while API data is being fetched
- [x] Handle unauthenticated users gracefully by redirecting to login

## 7. Open Questions

- Should API key management be included on the profile page, or maintained as a separate settings page?
- Do we want to display an "active sessions" view? This would require additional Auth0 Management API calls.
- Should the profile page require authentication in all environments, or should it be accessible to anonymous users in development mode?