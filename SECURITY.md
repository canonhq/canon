# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Canon, please report it responsibly.

**Email:** [security@canonhq.co](mailto:security@canonhq.co)

Please include:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge your report within 48 hours and aim to provide a fix within 7 days for critical issues.

## What Qualifies

- Authentication or authorization bypasses
- Injection vulnerabilities (SQL, command, template)
- Exposure of secrets or credentials
- Cross-site scripting (XSS) in the web dashboard
- Webhook signature verification bypasses

## What Doesn't Qualify

- Issues in dependencies (report upstream)
- Denial of service through expected API usage
- Social engineering

## Disclosure

We practice coordinated disclosure. Please do not file a public GitHub issue for security vulnerabilities. We will credit reporters in the release notes (unless you prefer anonymity).
