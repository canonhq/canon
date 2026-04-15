"""canon evidence — capture and inspect dev-session evidence.

See `docs/specs/plugin-evidence-pipeline.md` §3 + §5 for the design.

Subcommands:
    canon evidence record              — append a SessionRecord to session-evidence.json
    canon evidence list-verify-runs    — read .canon/verify-log.jsonl
    canon evidence show                — pretty-print session-evidence.json
    canon evidence push                — persist evidence per commit_on_push mode
                                         (file mode: stage + commit; mcp mode: stub
                                         until §6 ships)
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from canon.evidence.models import SessionEvidence, SessionRecord, VerifyRun

from ._local import load_local_config

logger = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "evidence",
        help="Capture and inspect dev-session evidence (plugin-evidence-pipeline)",
    )
    sub = parser.add_subparsers(dest="evidence_command")

    sub.add_parser(
        "record",
        help="Compose a SessionRecord and append to .canon/session-evidence.json",
    )

    list_parser = sub.add_parser(
        "list-verify-runs",
        help="Print records from .canon/verify-log.jsonl",
    )
    list_parser.add_argument(
        "--since",
        help="Only show records with at >= this ISO 8601 timestamp",
    )

    sub.add_parser("show", help="Pretty-print .canon/session-evidence.json")

    push_parser = sub.add_parser(
        "push",
        help="Persist evidence per commit_on_push mode (called by pre-push hook)",
    )
    push_parser.add_argument(
        "--mode",
        choices=["auto", "always", "ask", "never"],
        default="auto",
        help="Override commit_on_push mode (default: read from CANON.yaml)",
    )


def run_evidence(args: argparse.Namespace) -> None:
    cmd = getattr(args, "evidence_command", None)
    if cmd == "record":
        run_record()
    elif cmd == "list-verify-runs":
        run_list_verify_runs(since=args.since)
    elif cmd == "show":
        run_show()
    elif cmd == "push":
        run_push(mode_override=args.mode if args.mode != "auto" else None)
    else:
        # Print subcommand help
        print(
            "usage: canon evidence {record,list-verify-runs,show,push}\n"
            "\n"
            "Plugin → GitHub App evidence pipeline. See plugin-evidence-pipeline.md."
        )


# ─── record ──────────────────────────────────────────────────────────────


def run_record(*, root: Path | None = None) -> None:
    """Compose a SessionRecord and append to .canon/session-evidence.json.

    Exits silently when evidence_pipeline.enabled is false. Best-effort:
    failures do not raise — the Stop hook calls this and we never want to
    break the hook flow. Direct CLI users get a stderr breadcrumb instead
    of a traceback.
    """
    root = root or Path.cwd()

    try:
        config = load_local_config(root)
    except Exception as err:
        print(f"canon evidence record: failed to load config ({err})", file=sys.stderr)
        return

    if not config.ide.evidence_pipeline.enabled:
        return

    try:
        # First-record side effect: when commit_on_push is not "always", add
        # .canon/ to .gitignore so we don't accidentally commit evidence.
        _ensure_gitignore_entry(root, config.ide.evidence_pipeline.commit_on_push)

        record = _compose_session_record(root)
        _append_session_record(root, record)
        print(record.session_id)
    except Exception as err:
        print(f"canon evidence record: failed to record session ({err})", file=sys.stderr)


# ─── push ────────────────────────────────────────────────────────────────


def run_push(*, mode_override: str | None = None, root: Path | None = None) -> None:
    """Persist evidence per commit_on_push mode. Called by the pre-push hook.

    Modes:
    - "always": stage and commit .canon/session-evidence.json automatically
    - "ask": print an advisory to stderr; the hook handles the user prompt
    - "never": no-op for file mode
    - MCP persistence: stub until plugin-evidence-pipeline §6 ships
    """
    root = root or Path.cwd()
    try:
        config = load_local_config(root)
    except Exception:
        # Malformed or missing CANON.yaml — don't block the push.
        return

    if not config.ide.evidence_pipeline.enabled:
        return

    pipeline = config.ide.evidence_pipeline
    persist = pipeline.persist
    mode = mode_override or pipeline.commit_on_push

    evidence_path = root / ".canon" / "session-evidence.json"
    if not evidence_path.exists():
        # Nothing to push
        return

    # File-mode persistence
    if persist in ("file", "both"):
        if mode == "always":
            _commit_evidence_file(root, evidence_path)
        elif mode == "ask":
            print(
                f"canon: evidence captured at {evidence_path}. "
                "Set evidence_pipeline.commit_on_push: always to auto-commit, "
                "or run `git add .canon/session-evidence.json && git commit` manually.",
                file=sys.stderr,
            )
        # mode == "never": do nothing for file persistence

    # MCP persistence (stub)
    if persist in ("mcp", "both"):
        print(
            "canon: evidence_pipeline.persist=mcp is stubbed pending "
            "plugin-evidence-pipeline §6 (record_session_evidence MCP tool). "
            "Falling back to file persistence only.",
            file=sys.stderr,
        )


def _commit_evidence_file(root: Path, evidence_path: Path) -> None:
    """Stage and commit the evidence file. Best-effort."""
    rel_path = str(evidence_path.relative_to(root))
    try:
        subprocess.run(
            ["git", "add", rel_path],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=5,
        )
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "chore(canon): record session evidence",
                "--",
                rel_path,
            ],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=10,
        )
        print(f"canon: committed {rel_path}", file=sys.stderr)
    except (subprocess.SubprocessError, OSError) as err:
        print(f"canon: failed to commit evidence ({err})", file=sys.stderr)


def _compose_session_record(root: Path) -> SessionRecord:
    now_utc = datetime.now(UTC)
    started_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    git_branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    git_base = _resolve_base_branch(root)

    files_modified = []
    diff_output = _git(root, "diff", "--name-only", "HEAD")
    if diff_output:
        files_modified = [line.strip() for line in diff_output.splitlines() if line.strip()]

    verify_runs = _read_verify_log_since(root, since=None)

    session_id = _generate_session_id(git_branch, started_at)

    return SessionRecord(
        session_id=session_id,
        started_at=started_at,
        ended_at=started_at,  # Stop hook fires once at session end; both stamps are "now"
        git_branch=git_branch,
        git_base=git_base,
        files_modified=files_modified,
        verify_runs=verify_runs,
    )


def _generate_session_id(branch: str, ts: str) -> str:
    """YYYYMMDD-HHMMSS-<short-hash> where the hash is short and stable per session."""
    short_hash = hashlib.sha256(f"{branch}:{ts}:{os.getpid()}".encode()).hexdigest()[:4]
    compact_ts = ts.replace("-", "").replace(":", "").replace("T", "-").rstrip("Z")
    return f"{compact_ts}-{short_hash}"


@contextlib.contextmanager
def _evidence_file_lock(canon_dir: Path):
    """Acquire an exclusive flock on a sentinel file in `canon_dir`.

    Two parallel Claude sessions in the same worktree can both call
    `canon evidence record` simultaneously. Without a lock, both read N
    sessions from the file, each append their own, race on the rename, and
    one record gets silently dropped. The flock serializes the
    read-modify-write so concurrent appends compose instead of clobbering.

    Linux/macOS only — `fcntl.flock` is not available on Windows. The Stop
    hook calling this is a Unix shell script anyway, so this is fine for
    the supported platforms.
    """
    lock_path = canon_dir / ".evidence.lock"
    # 'a' so multiple processes can open the same file without truncating
    with lock_path.open("a") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _append_session_record(root: Path, record: SessionRecord) -> None:
    """Atomic append: read existing file, append, write to unique tmp, rename.

    Uses an `flock`-protected critical section to serialize concurrent
    writers in the same worktree. On parse failure of the existing file,
    rotates the corrupt file aside (rather than overwriting it with an
    empty document) so prior session data isn't silently lost.
    """
    canon_dir = root / ".canon"
    canon_dir.mkdir(exist_ok=True)
    evidence_path = canon_dir / "session-evidence.json"

    with _evidence_file_lock(canon_dir):
        if evidence_path.exists():
            try:
                existing = SessionEvidence.model_validate_json(evidence_path.read_text())
            except (ValueError, ValidationError, OSError) as err:
                # Don't silently overwrite — preserve the corrupted file so
                # prior sessions aren't lost. Operators can recover from
                # the .corrupt-* backup if needed.
                ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                backup = canon_dir / f"session-evidence.json.corrupt-{ts}"
                try:
                    evidence_path.rename(backup)
                    logger.warning(
                        "session-evidence.json is corrupt; preserved as %s (parse error: %s)",
                        backup,
                        err,
                    )
                except OSError as rename_err:
                    logger.error(
                        "Failed to preserve corrupt session-evidence.json as %s: %s; "
                        "refusing to overwrite to prevent data loss",
                        backup,
                        rename_err,
                    )
                    raise
                existing = SessionEvidence()
        else:
            existing = SessionEvidence()

        existing.sessions.append(record)

        # Unique tmp filename per process so concurrent writers (in the rare
        # case the lock is bypassed or this runs from a different mount) don't
        # clobber each other's tmp file mid-write.
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".session-evidence.",
            suffix=".tmp",
            dir=str(canon_dir),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(tmp_fd, "w") as f:
                f.write(existing.model_dump_json(indent=2))
            tmp_path.replace(evidence_path)
        except Exception:
            # Clean up the tmp file on any failure so we don't leak
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise


CANON_GITIGNORE_MARKER = "# canon evidence pipeline (auto-managed)"


def _ensure_gitignore_entry(root: Path, commit_on_push: str) -> None:
    """Add `.canon/` to .gitignore unless commit_on_push is 'always'.

    Idempotent: re-running is a no-op once the marker block is present.
    Best-effort: failures here never raise.
    """
    if commit_on_push == "always":
        return

    gitignore = root / ".gitignore"
    try:
        existing = gitignore.read_text() if gitignore.exists() else ""
    except OSError:
        return

    if CANON_GITIGNORE_MARKER in existing:
        return

    block = f"\n{CANON_GITIGNORE_MARKER}\n.canon/\n"
    try:
        with gitignore.open("a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(block)
    except OSError:
        pass


def _resolve_base_branch(root: Path) -> str | None:
    """Best-effort: find the merge base against origin/main, fallback to main."""
    for ref in ("origin/main", "main", "origin/master", "master"):
        merge_base = _git(root, "merge-base", "HEAD", ref)
        if merge_base:
            return ref
    return None


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


# ─── list-verify-runs ────────────────────────────────────────────────────


def run_list_verify_runs(*, since: str | None = None, root: Path | None = None) -> None:
    root = root or Path.cwd()
    runs = _read_verify_log_since(root, since=since)
    for run in runs:
        print(run.model_dump_json())


def _read_verify_log_since(root: Path, *, since: str | None) -> list[VerifyRun]:
    log_path = root / ".canon" / "verify-log.jsonl"
    if not log_path.exists():
        return []

    runs: list[VerifyRun] = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            run = VerifyRun.model_validate(payload)
        except (ValueError, KeyError, ValidationError):
            # ValidationError is required: pydantic v2's ValidationError
            # inherits from Exception, NOT ValueError, so omitting it would
            # let a single bad log line crash the whole list operation.
            continue
        if since:
            try:
                run_ts = datetime.fromisoformat(run.at.replace("Z", "+00:00"))
                since_ts = datetime.fromisoformat(since.replace("Z", "+00:00"))
                if run_ts < since_ts:
                    continue
            except (ValueError, AttributeError):
                # Unparseable timestamp — keep the entry rather than silently dropping
                pass
        runs.append(run)
    return runs


# ─── show ────────────────────────────────────────────────────────────────


def run_show(*, root: Path | None = None) -> None:
    root = root or Path.cwd()
    evidence_path = root / ".canon" / "session-evidence.json"
    if not evidence_path.exists():
        print("No session evidence recorded yet.")
        return
    try:
        ev = SessionEvidence.model_validate_json(evidence_path.read_text())
    except (ValueError, ValidationError, OSError) as err:
        print(f"Failed to parse evidence file: {err}")
        return
    print(ev.model_dump_json(indent=2))
