"""canon new — scaffold a new spec from a template.

Non-interactive scaffolding for spec creation. Wraps the existing
:func:`canon.parser.templates.get_template` source so the CLI and the
new-spec GitHub Action produce identical output.

Designed for CI consumption: every input is a flag, no prompts, no
network. The action layer slugifies the title to a filename and opens
a PR with the result.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from canon.parser.models import VALID_DOC_TYPES
from canon.parser.templates import get_template

from ._local import load_local_config


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "new",
        help="Scaffold a new spec from a template",
    )
    parser.add_argument(
        "--title",
        required=True,
        help='Spec title (e.g. "Auth Hardening")',
    )
    parser.add_argument(
        "--type",
        dest="doc_type",
        default="spec",
        choices=sorted(VALID_DOC_TYPES),
        help="Document type (default: spec)",
    )
    parser.add_argument(
        "--owner",
        default="",
        help="Owner GitHub handle or name",
    )
    parser.add_argument(
        "--team",
        default="",
        help="Owning team",
    )
    parser.add_argument(
        "--output",
        help=(
            "Explicit output path. Defaults to <doc_paths_directory>/<slug>.md "
            "based on CANON.yaml's first doc_paths entry."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists",
    )


def run_new(
    *,
    title: str,
    doc_type: str = "spec",
    owner: str = "",
    team: str = "",
    output: str | None = None,
    force: bool = False,
    root: Path | None = None,
) -> int:
    """Scaffold a new spec file. Returns exit code."""
    root = root or Path.cwd()

    if not title.strip():
        print("error: --title cannot be empty", file=sys.stderr)
        return 2

    template = get_template(doc_type)
    body = _fill_template(template, title=title, owner=owner, team=team)

    output_path = _resolve_output_path(root, title, output)

    if output_path.exists() and not force:
        print(
            f"error: {output_path.relative_to(root) if output_path.is_absolute() else output_path} "
            "already exists. Pass --force to overwrite.",
            file=sys.stderr,
        )
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(body)
    print(str(output_path.relative_to(root) if output_path.is_absolute() else output_path))
    return 0


# ─── Helpers ───────────────────────────────────────────────


def slugify(title: str) -> str:
    """Turn a title into a filesystem-safe lowercase-hyphenated slug.

    Mirrors the slug heuristic the GitHub App and Claude plugin use so
    a spec scaffolded by `canon new` looks identical to one created
    interactively elsewhere in the suite.
    """
    slug = title.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


def _fill_template(template: str, *, title: str, owner: str, team: str) -> str:
    """Substitute frontmatter placeholders in the bundled spec template.

    Replaces the well-known empty/placeholder values from the template
    with the user-supplied ones plus today's date. Keeps every other
    line of the template intact so the rendered file matches whatever
    canon-private's template generator currently produces.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out = template

    # Replace the H1 heading anywhere in the template body. The bundled
    # template uses "Untitled Spec" as the placeholder and we replace
    # both the frontmatter title field and the H1 in one pass.
    out = re.sub(
        r'^title: ".*?"',
        f'title: "{_escape_yaml(title)}"',
        out,
        count=1,
        flags=re.MULTILINE,
    )
    out = re.sub(
        r"^# Untitled Spec.*$",
        f"# {title}",
        out,
        count=1,
        flags=re.MULTILINE,
    )
    out = re.sub(
        r'^owner: ""',
        f'owner: "{_escape_yaml(owner)}"',
        out,
        count=1,
        flags=re.MULTILINE,
    )
    out = re.sub(
        r'^team: ""',
        f'team: "{_escape_yaml(team)}"',
        out,
        count=1,
        flags=re.MULTILINE,
    )
    out = re.sub(
        r'^created: ""',
        f'created: "{today}"',
        out,
        count=1,
        flags=re.MULTILINE,
    )
    out = re.sub(
        r'^updated: ""',
        f'updated: "{today}"',
        out,
        count=1,
        flags=re.MULTILINE,
    )

    return out


def _escape_yaml(value: str) -> str:
    """Escape a value for inclusion inside a double-quoted YAML string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _resolve_output_path(root: Path, title: str, override: str | None) -> Path:
    """Pick the output path for a new spec.

    When the user passed --output, that wins (relative paths resolved
    against the repo root). Otherwise, look at CANON.yaml's first
    doc_paths glob, derive the directory, and append <slug>.md.
    """
    if override:
        path = Path(override)
        return path if path.is_absolute() else root / path

    config = load_local_config(root)
    doc_paths = config.specs.doc_paths or ["docs/specs/*.md"]
    first_glob = doc_paths[0]
    # Strip the trailing glob fragment to get the directory
    glob_dir = first_glob.split("*", 1)[0].rstrip("/")
    if not glob_dir:
        glob_dir = "docs/specs"

    slug = slugify(title)
    return root / glob_dir / f"{slug}.md"
