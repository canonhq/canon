---
title: "Auth Migration to OAuth 2.0 + PKCE"
status: todo
owner: alex-kumar
team: identity
ticket_project: ID
created: 2026-01-10
updated: 2026-01-20
tags: [auth, security, q1-priority]
---

# Auth Migration to OAuth 2.0 + PKCE

> **Note:** This is an **example spec** demonstrating the Canon spec format for an auth migration scenario. It is not the canonical auth spec for the Canon platform itself — see [`docs/specs/auth-hardening.md`](../specs/auth-hardening.md) for that.

Replace our custom session-based auth with OAuth 2.0 + PKCE flows, enabling SSO and improving security posture.

## 1. Background

<!-- canon:system:1 status:done -->

Current auth is a custom session-cookie system built in 2020. It doesn't support SSO, has no refresh token rotation, and session fixation was patched twice last year. We need standards-based auth before SOC2 audit in Q2.

## 2. OAuth Provider Integration

<!-- canon:system:2 status:todo -->
<!-- canon:ticket:linear:ID-301 -->

Integrate with Auth0 as the OAuth provider. Support Google Workspace and Microsoft Entra ID as identity providers.

### Acceptance Criteria

- [ ] Auth0 tenant configured for production
- [ ] Google Workspace SSO working end-to-end
- [ ] Microsoft Entra ID SSO working end-to-end
- [ ] PKCE flow implemented for all client types

## 3. Token Management

<!-- canon:system:3 status:draft -->
<!-- canon:ticket:linear:ID-302 -->

Implement secure token storage and refresh flows.

Access tokens: 15-minute expiry, stored in memory only.
Refresh tokens: 7-day expiry, rotated on each use, stored in httpOnly cookie.

### Acceptance Criteria

- [ ] Access tokens never persisted to storage
- [ ] Refresh token rotation on every use
- [ ] Revocation endpoint clears all active sessions
- [ ] Token introspection endpoint for service-to-service auth

## 4. Session Migration

<!-- canon:system:4 status:draft -->
<!-- canon:ticket:linear:ID-303 -->

Migrate existing sessions to new auth system without forcing all users to re-login.

Strategy: On next request, validate old session cookie → issue new OAuth tokens → delete old session. Users experience zero downtime.

### Acceptance Criteria

- [ ] Existing sessions upgraded transparently on next request
- [ ] Migration progress tracked in admin dashboard
- [ ] Rollback capability for 30 days post-migration
