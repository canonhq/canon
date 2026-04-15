"""Plugin → GitHub App evidence pipeline.

Captures dev-session evidence (which spec sections were touched, which ACs
were addressed, which files were modified, which gate runs occurred) so the
GitHub App's PR analyzer can use it as hint input at PR-open time.

See `docs/specs/plugin-evidence-pipeline.md` for the full design.
"""
