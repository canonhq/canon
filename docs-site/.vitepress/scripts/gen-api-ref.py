#!/usr/bin/env python3
"""Generate REST API reference markdown from FastAPI's OpenAPI schema.

Imports the FastAPI app, extracts the OpenAPI schema, and writes
docs-site/reference/api.md with structured endpoint documentation.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

DOCS_SITE = Path(__file__).resolve().parent.parent.parent
OUTPUT = DOCS_SITE / "reference" / "api.md"

PROJECT_ROOT = DOCS_SITE.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# HTTP method display order
METHOD_ORDER = {"GET": 0, "POST": 1, "PUT": 2, "PATCH": 3, "DELETE": 4}


def get_openapi_schema() -> dict:
    """Import FastAPI app and extract OpenAPI schema."""
    import os

    # Set required env vars to allow import without full config
    os.environ.setdefault("GITHUB_APP_ID", "0")
    os.environ.setdefault("GITHUB_PRIVATE_KEY", "dummy")
    os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "dummy")
    os.environ.setdefault("AUTH0_DOMAIN", "dummy.auth0.com")
    os.environ.setdefault("AUTH0_CLIENT_ID", "dummy")
    os.environ.setdefault("AUTH0_CLIENT_SECRET", "dummy")
    os.environ.setdefault("AUTH0_AUDIENCE", "dummy")

    try:
        from specwright.main import app

        return app.openapi()
    except Exception as e:
        print(f"Warning: Could not import FastAPI app: {e}", file=sys.stderr)
        return {}


def infer_group(path: str) -> str:
    """Infer a group name from the URL path prefix."""
    if path.startswith("/auth/device"):
        return "Device Authorization"
    if path.startswith("/auth/github"):
        return "GitHub OAuth"
    if path.startswith("/auth"):
        return "Authentication"
    if "/api/tickets" in path:
        return "Ticket Proxy"
    if "/api/profile" in path:
        return "Profile"
    if "/editor/" in path:
        return "Editor"
    if "/api/" in path:
        return "JSON API"
    if "/admin/" in path:
        return "Admin"
    if "/settings/" in path:
        return "Settings"
    if path in ("/healthz", "/readyz", "/webhook"):
        return "Infrastructure"
    if path.startswith("/app/"):
        return "Web UI"
    return "Public"


def group_by_tag(schema: dict) -> dict[str, list[dict]]:
    """Group endpoints by tag or inferred path prefix."""
    groups: dict[str, list[dict]] = {}
    paths = schema.get("paths", {})

    for path, methods in sorted(paths.items()):
        for method, details in methods.items():
            if method.upper() in ("OPTIONS", "HEAD"):
                continue
            tags = details.get("tags", [])
            tag = tags[0] if tags else infer_group(path)
            entry = {
                "method": method.upper(),
                "path": path,
                "summary": details.get("summary", ""),
                "description": details.get("description", ""),
                "parameters": details.get("parameters", []),
                "request_body": details.get("requestBody"),
                "responses": details.get("responses", {}),
                "security": details.get("security", []),
            }
            groups.setdefault(tag, []).append(entry)

    # Sort each group by path then method
    for tag in groups:
        groups[tag].sort(key=lambda e: (e["path"], METHOD_ORDER.get(e["method"], 9)))

    return groups


def format_parameters(params: list[dict]) -> str:
    """Format path/query parameters as a markdown table."""
    if not params:
        return ""

    rows = []
    for p in params:
        name = p.get("name", "")
        location = p.get("in", "")
        required = "Yes" if p.get("required") else "No"
        schema = p.get("schema", {})
        ptype = schema.get("type", "string")
        desc = p.get("description", "")
        rows.append(f"| `{name}` | {location} | `{ptype}` | {required} | {desc} |")

    if not rows:
        return ""

    header = "| Name | In | Type | Required | Description |\n|------|-----|------|----------|-------------|"
    return header + "\n" + "\n".join(rows)


def format_request_body(body: dict | None, schemas: dict) -> str:
    """Format request body as markdown."""
    if not body:
        return ""

    content = body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})

    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        ref_schema = schemas.get(ref_name, {})
        props = ref_schema.get("properties", {})
        required = set(ref_schema.get("required", []))

        if not props:
            return f"**Request Body:** `{ref_name}`\n"

        rows = []
        for name, prop in props.items():
            ptype = prop.get("type", "")
            if not ptype and "$ref" in prop:
                ptype = prop["$ref"].split("/")[-1]
            req = "Yes" if name in required else "No"
            desc = prop.get("description", "")
            rows.append(f"| `{name}` | `{ptype}` | {req} | {desc} |")

        header = f"**Request Body** (`{ref_name}`):\n\n| Field | Type | Required | Description |\n|-------|------|----------|-------------|"
        return header + "\n" + "\n".join(rows)

    return ""


def generate(schema: dict) -> str:
    """Generate the API reference markdown."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    schemas = schema.get("components", {}).get("schemas", {})

    parts = [
        "---",
        "# This file is auto-generated. Do not edit manually.",
        f"# Generated: {now}",
        "---",
        "",
        "# REST API Reference",
        "",
        "::: tip Auto-Generated",
        f"This page was auto-generated from the FastAPI OpenAPI schema on {now}.",
        "See [source script](https://github.com/canonhq/canon/blob/main/docs-site/.vitepress/scripts/gen-api-ref.py).",
        ":::",
        "",
        "## Base URL",
        "",
        "- **Hosted**: `https://canonhq.co`",
        "- **Self-hosted**: `https://<your-domain>`",
        "",
        "## Authentication",
        "",
        "API requests use Bearer token authentication:",
        "",
        "```",
        "Authorization: Bearer <token>",
        "```",
        "",
        "Tokens can be:",
        "- **JWT access tokens** from Auth0 login",
        "- **API keys** prefixed with `sw_` (create via Settings > API Keys)",
        "- **Session cookies** for browser-based access",
        "",
    ]

    if not schema.get("paths"):
        parts.append(
            "::: warning\nCould not extract OpenAPI schema. API reference may be incomplete.\n:::"
        )
        parts.append("")
        return "\n".join(parts)

    groups = group_by_tag(schema)

    # Count total endpoints
    total = sum(len(eps) for eps in groups.values())
    parts.append(f"## Endpoints ({total})")
    parts.append("")

    for tag, endpoints in groups.items():
        parts.append(f"### {tag}")
        parts.append("")

        for ep in endpoints:
            badge = ep["method"]
            parts.append(f"#### `{badge} {ep['path']}`")
            parts.append("")
            if ep["summary"]:
                parts.append(ep["summary"])
                parts.append("")
            if ep["description"] and ep["description"] != ep["summary"]:
                parts.append(ep["description"])
                parts.append("")

            param_table = format_parameters(ep["parameters"])
            if param_table:
                parts.append(param_table)
                parts.append("")

            body_md = format_request_body(ep["request_body"], schemas)
            if body_md:
                parts.append(body_md)
                parts.append("")

            # Response codes
            if ep["responses"]:
                resp_items = []
                for code, resp in sorted(ep["responses"].items()):
                    desc = resp.get("description", "")
                    resp_items.append(f"- **{code}**: {desc}")
                if resp_items:
                    parts.append("**Responses:**")
                    parts.append("")
                    parts.extend(resp_items)
                    parts.append("")

            parts.append("---")
            parts.append("")

    return "\n".join(parts)


def main():
    schema = get_openapi_schema()
    paths = schema.get("paths", {})
    total = sum(len(m) for m in paths.values()) if paths else 0
    print(f"Found {total} API endpoints in OpenAPI schema")

    content = generate(schema)
    OUTPUT.write_text(content)
    print(f"Generated {OUTPUT} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
