"""canon search — full-text search across spec files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ._local import _flatten_sections, load_local_config, parse_all_local_specs
from ._output import get_stdout, status_badge


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("search", help="Search specs by keyword")
    parser.add_argument("query", help="Search terms")
    parser.add_argument("--status", help="Filter by section status")
    parser.add_argument("--spec", help="Limit to a specific spec file")
    parser.add_argument("--json", action="store_true", help="JSON output")


def run_search(
    *,
    query: str,
    status: str | None = None,
    spec: str | None = None,
    json_output: bool = False,
    root: Path | None = None,
) -> int:
    """Search spec content for matching terms. Returns exit code."""
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if spec:
        docs = [d for d in docs if spec in d.file_path]

    if not docs:
        if json_output:
            print(json.dumps({"results": [], "count": 0}, indent=2))
        else:
            print("No spec files found.")
        return 1

    # Build search terms (case-insensitive)
    terms = query.lower().split()
    results: list[dict] = []

    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        for section in all_sections:
            if status and section.status.state != status:
                continue

            # Search in title, body, and AC text
            searchable = section.title.lower()
            if section.content:
                searchable += " " + section.content.lower()
            for ac in section.acceptance_criteria:
                searchable += " " + ac.text.lower()

            # Count how many terms match
            matches = sum(1 for t in terms if t in searchable)
            if matches == 0:
                continue

            # Build a snippet — find first matching line
            snippet = ""
            all_lines: list[str] = []
            if section.content:
                all_lines = section.content.strip().split("\n")
            for ac in section.acceptance_criteria:
                all_lines.append(ac.text)

            for line in all_lines:
                if any(t in line.lower() for t in terms):
                    snippet = line.strip()[:100]
                    break
            if not snippet and all_lines:
                snippet = all_lines[0].strip()[:100]

            results.append(
                {
                    "spec": doc.frontmatter.title,
                    "file": doc.file_path,
                    "section": f"{section.section_number or section.id}. {section.title}",
                    "status": section.status.state,
                    "snippet": snippet,
                    "relevance": matches,
                }
            )

    # Sort by relevance (more matching terms first)
    results.sort(key=lambda r: r["relevance"], reverse=True)

    if json_output:
        print(json.dumps({"results": results, "count": len(results)}, indent=2))
        return 0 if results else 1

    if not results:
        get_stdout().print(f"[muted]No results for '{query}'[/muted]")
        return 1

    get_stdout().print(
        f"\n[heading]Search results for '{query}'[/heading]  ({len(results)} matches)\n"
    )

    for r in results:
        get_stdout().print(f"  [key]{r['spec']}[/key] > {r['section']}  ", end="")
        get_stdout().print(status_badge(r["status"]))
        if r["snippet"]:
            # Highlight matching terms in the snippet
            snippet = r["snippet"]
            get_stdout().print(f"    [muted]{snippet}[/muted]")
        get_stdout().print()

    return 0
