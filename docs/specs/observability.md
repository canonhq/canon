---
title: "Observability: PostHog Exception Capture"
status: done
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-02-26
tags: [observability, posthog, monitoring]
---

# Observability: PostHog Exception Capture

Enable PostHog automatic exception capture on both the frontend (JS SDK) and backend (Python SDK) to provide centralized visibility into unhandled errors.

## 1. Background

<!-- specwright:system:1 status:done -->

PostHog supports automatic exception capture on both JS and Python SDKs, but it hasn't been enabled. Unhandled errors are currently only visible in server logs — there's no centralized view of client-side or server-side exceptions, no error grouping, and no trend analysis.

**Related:** [#86](https://github.com/canonhq/canon/issues/86)

## 2. Backend Exception Capture

<!-- specwright:system:2 status:done -->
<!-- specwright:ticket:github:86 -->

Enable PostHog exception capture in the Python SDK (`src/specwright/`) for server-side errors.

### Acceptance Criteria

- [x] PostHog Python SDK configured with `enable_exception_autocapture=True`
<!-- specwright:realized-in:PR#112 file:src/specwright/analytics.py -->
<!-- canon:realized-in:PR#328 file:src/canon/otel_logging.py -->
- [x] Unhandled FastAPI exceptions are captured and sent to PostHog
<!-- specwright:realized-in:PR#112 file:src/specwright/main.py -->
<!-- canon:realized-in:PR#328 file:src/canon/main.py -->
- [x] Exception events include stack trace, request context, and user identity
- [ ] Sensitive data (API keys, tokens) is scrubbed from exception payloads
- [x] Exception capture does not affect application performance or error handling behavior

## 3. Frontend Exception Capture

<!-- specwright:system:3 status:done -->
<!-- specwright:ticket:github:86 -->

Enable PostHog exception capture in the JS SDK for client-side errors in the Vue frontend.

### Acceptance Criteria

- [x] PostHog JS SDK configured with `autocapture_exceptions: true` (or equivalent)
<!-- specwright:realized-in:PR#112 file:templates/base.html -->
- [x] Unhandled JS exceptions and promise rejections are captured
- [x] Exception events include stack trace and page context
- [ ] Source maps configured for readable stack traces in PostHog
- [x] Client-side exceptions are visible in the same PostHog dashboard as backend exceptions

## 4. Open Questions

- Should we set up PostHog alerts for exception spikes?
- What's the exception sampling rate? (100% for now, or sample in production?)
