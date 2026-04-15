"""Pydantic models for the plugin evidence pipeline.

See `docs/specs/plugin-evidence-pipeline.md` §2.1 for the canonical schema.

The on-disk format at `.canon/session-evidence.json` is a top-level
`SessionEvidence` document containing a list of `SessionRecord` entries —
one per dev session that touched the branch. Multi-session aggregation
happens by appending to the list rather than overwriting.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VerifyStatus = Literal["realized", "partial", "not_started", "unknown"]
VerifyMode = Literal["report", "gate"]
VerifyResult = Literal["pass", "fail"]


class SpecTouched(BaseModel):
    """A spec the developer interacted with during the session."""

    spec: str = Field(min_length=1)  # spec slug, e.g. "auth-hardening"
    sections: list[str] = []  # section IDs, e.g. ["2.1", "2.2"]
    loaded_via: list[str] = []  # ["canon-context", "canon-task", ...]


class AcAddressed(BaseModel):
    """An acceptance criterion the developer worked on during the session."""

    spec: str = Field(min_length=1)
    section: str = Field(min_length=1)
    ac_text: str = Field(min_length=1)
    files: list[str] = []
    line_ranges: list[str] = []
    verify_status: VerifyStatus = "unknown"
    verified_at: str | None = None  # ISO 8601


class VerifyRun(BaseModel):
    """A single canon verify gate-mode invocation."""

    at: str = Field(min_length=1)  # ISO 8601
    section: str | None = None
    mode: VerifyMode = "gate"
    result: VerifyResult
    gaps: int = Field(default=0, ge=0)
    conflicts: int = Field(default=0, ge=0)


class SessionRecord(BaseModel):
    """One dev session — a unit of work between Claude session start and end."""

    session_id: str = Field(min_length=1)  # YYYYMMDD-HHMMSS-<short-hash>
    started_at: str = Field(min_length=1)  # ISO 8601
    ended_at: str = Field(min_length=1)  # ISO 8601
    git_branch: str = Field(min_length=1)
    git_base: str | None = None
    specs_touched: list[SpecTouched] = []
    acs_addressed: list[AcAddressed] = []
    files_modified: list[str] = []
    verify_runs: list[VerifyRun] = []


class SessionEvidence(BaseModel):
    """Top-level container for `.canon/session-evidence.json`.

    Multi-session aggregation: append `SessionRecord` entries to `sessions`
    rather than overwriting. The PR analyzer reads the union when analyzing
    a PR.
    """

    version: Literal[1] = 1
    sessions: list[SessionRecord] = []
