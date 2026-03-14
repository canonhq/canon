#!/usr/bin/env python3
"""Generate MCP tools reference markdown from server tool metadata.

Parses the MCP server source code using AST to extract tool definitions
(name, description, parameters) and writes docs-site/reference/mcp.md.
"""

import ast
import sys
from datetime import UTC, datetime
from pathlib import Path

DOCS_SITE = Path(__file__).resolve().parent.parent.parent
OUTPUT = DOCS_SITE / "reference" / "mcp.md"
PROJECT_ROOT = DOCS_SITE.parent
SERVER_PY = PROJECT_ROOT / "src" / "canon" / "mcp" / "server.py"

# Parameters to skip (injected by FastMCP, not user-facing)
SKIP_PARAMS = {"ctx", "context", "request_context"}


def resolve_type(node: ast.expr) -> str:
    """Convert an AST annotation node to a readable type string."""
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{resolve_type(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        base = resolve_type(node.value)
        sl = resolve_type(node.slice)
        return f"{base}[{sl}]"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return f"{resolve_type(node.left)} | {resolve_type(node.right)}"
    if isinstance(node, ast.Tuple):
        return ", ".join(resolve_type(e) for e in node.elts)
    return "any"


def resolve_constant(node: ast.expr) -> str:
    """Resolve an AST node to a string value (for decorator kwargs)."""
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.JoinedStr):
        # f-string — just return a placeholder
        return "<f-string>"
    # Handle string concatenation via parenthesized multi-line strings
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return resolve_constant(node.left) + resolve_constant(node.right)
    return ""


def extract_tools() -> list[dict]:
    """Parse server.py AST to extract @mcp.tool() decorated functions."""
    if not SERVER_PY.exists():
        print(f"Error: {SERVER_PY} not found", file=sys.stderr)
        return []

    source = SERVER_PY.read_text()
    tree = ast.parse(source, filename=str(SERVER_PY))
    tools = []

    # Walk all function definitions (including nested ones)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Check if this function has a @mcp.tool(...) decorator
        tool_decorator = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                func = dec.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "tool"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "mcp"
                ):
                    tool_decorator = dec
                    break

        if tool_decorator is None:
            continue

        # Extract name and description from decorator kwargs
        name = node.name
        description = ""
        for kw in tool_decorator.keywords:
            if kw.arg == "name":
                name = resolve_constant(kw.value)
            elif kw.arg == "description":
                description = resolve_constant(kw.value)

        # Extract parameters from function signature
        params = []
        args = node.args
        # Get defaults aligned with args (defaults are right-aligned)
        num_defaults = len(args.defaults)
        num_args = len(args.args)

        for i, arg in enumerate(args.args):
            if arg.arg in SKIP_PARAMS or arg.arg == "self":
                continue

            ptype = resolve_type(arg.annotation) if arg.annotation else "any"

            # Check if this arg has a default
            default_idx = i - (num_args - num_defaults)
            has_default = default_idx >= 0
            default_val = None
            if has_default:
                default_node = args.defaults[default_idx]
                if isinstance(default_node, ast.Constant):
                    default_val = repr(default_node.value)
                elif isinstance(default_node, ast.Name):
                    default_val = default_node.id

            p: dict = {
                "name": arg.arg,
                "type": ptype,
                "required": not has_default,
            }
            if default_val is not None:
                p["default"] = default_val
            params.append(p)

        tools.append(
            {
                "name": name,
                "description": description.strip(),
                "parameters": params,
            }
        )

    return tools


def generate(tools: list[dict]) -> str:
    """Generate the MCP reference markdown."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    parts = [
        "---",
        "# This file is auto-generated. Do not edit manually.",
        f"# Generated: {now}",
        "---",
        "",
        "# MCP Tools Reference",
        "",
        "::: tip Auto-Generated",
        f"This page was auto-generated from MCP server tool metadata on {now}.",
        "See [source script](https://github.com/canonhq/canon/blob/main/docs-site/.vitepress/scripts/gen-mcp-ref.py).",
        ":::",
        "",
        "The Canon MCP server exposes tools for coding agents (Claude Code, Cursor, VS Code Copilot) to query and update the spec knowledge base.",
        "",
        "## Setup",
        "",
        "### Claude Code",
        "",
        "Add to your project's `.mcp.json`:",
        "",
        "```json",
        "{",
        '  "mcpServers": {',
        '    "canon": {',
        '      "command": "uvx",',
        '      "args": ["canon", "mcp"]',
        "    }",
        "  }",
        "}",
        "```",
        "",
        "### Cursor / VS Code",
        "",
        "Add to your MCP configuration with the same command and args.",
        "",
        f"## Tools ({len(tools)})",
        "",
    ]

    for tool in tools:
        parts.append(f"### `{tool['name']}`")
        parts.append("")
        parts.append(tool["description"])
        parts.append("")

        params = tool.get("parameters", [])
        if params:
            parts.append("**Parameters:**")
            parts.append("")
            parts.append("| Name | Type | Required | Default |")
            parts.append("|------|------|----------|---------|")
            for p in params:
                req = "Yes" if p["required"] else "No"
                default = p.get("default", "—")
                if default in ("None", "'None'"):
                    default = "—"
                parts.append(f"| `{p['name']}` | `{p['type']}` | {req} | {default} |")
            parts.append("")

        parts.append("---")
        parts.append("")

    return "\n".join(parts)


def main():
    tools = extract_tools()
    if not tools:
        print("Warning: No tools found", file=sys.stderr)
    else:
        print(f"Found {len(tools)} MCP tools")

    content = generate(tools)
    OUTPUT.write_text(content)
    print(f"Generated {OUTPUT} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
