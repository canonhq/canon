"""CANON.yaml parser with Pydantic validation."""

from __future__ import annotations

import re
from typing import Literal

import yaml
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from canon.parser.models import Diagnostic
from canon.sync.mapping import (
    AuthProfile,
    RoutingRule,
    TicketMappingConfig,
    TicketSystemConfig,
)

# ─── Config Models ────────────────────────────────────────

TicketSystem = Literal["jira", "linear", "github"]
VALID_TICKET_SYSTEMS: list[str] = ["jira", "linear", "github"]

KNOWN_TOP_KEYS = {
    "team",
    "ticket_system",
    "project_key",
    "slack_channel",
    "specs",
    "agents",
    "ticket_systems",
    "routing",
    "auth_profiles",
}
KNOWN_SPECS_KEYS = {"auto_tickets", "require_review", "doc_paths"}
KNOWN_AGENTS_KEYS = {"doc_updates", "pr_analysis", "stale_detection", "realization_check"}

DURATION_RE = re.compile(r"^\d+d$")


class SpecsConfig(BaseModel):
    auto_tickets: bool = True
    require_review: bool = True
    doc_paths: list[str] = ["docs/specs/*.md"]


class AgentsConfig(BaseModel):
    doc_updates: bool = True
    pr_analysis: bool = True
    realization_check: bool = True
    stale_detection: str | Literal[False] = "30d"


class SpecwrightConfig(BaseModel):
    team: str | None = None
    ticket_system: TicketSystem | None = None
    project_key: str | None = None
    slack_channel: str | None = None
    specs: SpecsConfig = SpecsConfig()
    agents: AgentsConfig = AgentsConfig()
    ticket_mapping: TicketMappingConfig | None = None


class ConfigResult(BaseModel):
    config: SpecwrightConfig
    diagnostics: list[Diagnostic]


DEFAULT_CONFIG = SpecwrightConfig()

# Canonical aliases — SpecwrightConfig/parse_specwright_yaml are deprecated
CanonConfig = SpecwrightConfig


# ─── Public API ───────────────────────────────────────────


def parse_specwright_yaml(raw: str) -> ConfigResult:
    """Parse and validate CANON.yaml content."""
    diagnostics: list[Diagnostic] = []

    if not raw.strip():
        return ConfigResult(
            config=SpecwrightConfig(),
            diagnostics=[
                Diagnostic(
                    severity="warning",
                    message="CANON.yaml is empty, using defaults",
                )
            ],
        )

    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as err:
        return ConfigResult(
            config=SpecwrightConfig(),
            diagnostics=[Diagnostic(severity="error", message=f"Invalid YAML: {err}")],
        )

    if not isinstance(parsed, dict):
        return ConfigResult(
            config=SpecwrightConfig(),
            diagnostics=[
                Diagnostic(
                    severity="error",
                    message="CANON.yaml must be a YAML mapping, not a scalar or list",
                )
            ],
        )

    obj: dict[str, object] = parsed

    # Warn on unknown top-level keys
    for key in obj:
        if key not in KNOWN_TOP_KEYS:
            diagnostics.append(
                Diagnostic(severity="warning", message=f'Unknown config key: "{key}"')
            )

    # Validate ticket_system
    if obj.get("ticket_system") is not None and obj["ticket_system"] not in VALID_TICKET_SYSTEMS:
        diagnostics.append(
            Diagnostic(
                severity="error",
                message=(
                    f'Invalid ticket_system: "{obj["ticket_system"]}", '
                    f"must be one of: {', '.join(VALID_TICKET_SYSTEMS)}"
                ),
            )
        )
        del obj["ticket_system"]

    # Validate string fields
    for key in ("team", "project_key", "slack_channel"):
        if key in obj and obj[key] is not None and not isinstance(obj[key], str):
            diagnostics.append(Diagnostic(severity="error", message=f'"{key}" must be a string'))
            del obj[key]

    # Validate specs section
    if "specs" in obj:
        if not isinstance(obj["specs"], dict):
            diagnostics.append(Diagnostic(severity="error", message='"specs" must be a mapping'))
            del obj["specs"]
        else:
            specs = obj["specs"]
            assert isinstance(specs, dict)
            for key in list(specs.keys()):
                if key not in KNOWN_SPECS_KEYS:
                    diagnostics.append(
                        Diagnostic(severity="warning", message=f'Unknown specs key: "{key}"')
                    )
            for key in ("auto_tickets", "require_review"):
                if key in specs and not isinstance(specs[key], bool):
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message=f'"specs.{key}" must be a boolean',
                        )
                    )
                    del specs[key]

            if "doc_paths" in specs:
                dp = specs["doc_paths"]
                if not isinstance(dp, list) or not all(isinstance(p, str) for p in dp):
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message='"specs.doc_paths" must be a list of strings',
                        )
                    )
                    del specs["doc_paths"]
                elif len(dp) == 0:
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message='"specs.doc_paths" must not be empty',
                        )
                    )
                    del specs["doc_paths"]

    # Validate agents section
    if "agents" in obj:
        if not isinstance(obj["agents"], dict):
            diagnostics.append(Diagnostic(severity="error", message='"agents" must be a mapping'))
            del obj["agents"]
        else:
            agents = obj["agents"]
            assert isinstance(agents, dict)
            for key in list(agents.keys()):
                if key not in KNOWN_AGENTS_KEYS:
                    diagnostics.append(
                        Diagnostic(
                            severity="warning",
                            message=f'Unknown agents key: "{key}"',
                        )
                    )
            for key in ("doc_updates", "pr_analysis", "realization_check"):
                if key in agents and not isinstance(agents[key], bool):
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message=f'"agents.{key}" must be a boolean',
                        )
                    )
                    del agents[key]

            if "stale_detection" in agents:
                sd = agents["stale_detection"]
                if sd is False:
                    pass  # Explicitly disabled — valid
                elif not isinstance(sd, str):
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message='"agents.stale_detection" must be a duration string (e.g. "30d") or false',
                        )
                    )
                    del agents["stale_detection"]
                elif not DURATION_RE.match(sd):
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message=f'Invalid stale_detection duration: "{sd}", expected format like "30d" or "7d"',
                        )
                    )
                    del agents["stale_detection"]

    # Validate ticket_systems / routing / auth_profiles
    ticket_mapping = _parse_ticket_mapping(obj, diagnostics)

    config = _merge_with_defaults(obj, ticket_mapping)
    return ConfigResult(config=config, diagnostics=diagnostics)


# Canonical alias
parse_canon_yaml = parse_specwright_yaml


# ─── Internal ─────────────────────────────────────────────


def _parse_ticket_mapping(
    obj: dict[str, object],
    diagnostics: list[Diagnostic],
) -> TicketMappingConfig | None:
    """Parse ticket_systems, routing, and auth_profiles into a TicketMappingConfig."""
    has_new = any(k in obj for k in ("ticket_systems", "routing", "auth_profiles"))
    if not has_new:
        return None

    validated_auth: dict[str, AuthProfile] = {}
    validated_systems: dict[str, TicketSystemConfig] = {}
    validated_routing: list[RoutingRule] = []

    # Parse auth_profiles
    if "auth_profiles" in obj:
        if not isinstance(obj["auth_profiles"], dict):
            diagnostics.append(
                Diagnostic(severity="error", message='"auth_profiles" must be a mapping')
            )
        else:
            for name, profile_data in obj["auth_profiles"].items():
                if not isinstance(profile_data, dict):
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message=f'"auth_profiles.{name}" must be a mapping',
                        )
                    )
                    continue
                try:
                    validated_auth[name] = AuthProfile(**profile_data)
                except PydanticValidationError as err:
                    for e in err.errors():
                        diagnostics.append(
                            Diagnostic(
                                severity="error",
                                message=f"auth_profiles.{name}: {e['msg']}",
                            )
                        )

    # Parse ticket_systems
    if "ticket_systems" in obj:
        if not isinstance(obj["ticket_systems"], dict):
            diagnostics.append(
                Diagnostic(severity="error", message='"ticket_systems" must be a mapping')
            )
        else:
            for name, sys_data in obj["ticket_systems"].items():
                if not isinstance(sys_data, dict):
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message=f'"ticket_systems.{name}" must be a mapping',
                        )
                    )
                    continue
                try:
                    validated_systems[name] = TicketSystemConfig(**sys_data)
                except PydanticValidationError as err:
                    for e in err.errors():
                        diagnostics.append(
                            Diagnostic(
                                severity="error",
                                message=f"ticket_systems.{name}: {e['msg']}",
                            )
                        )

    # Parse routing
    if "routing" in obj:
        if not isinstance(obj["routing"], list):
            diagnostics.append(Diagnostic(severity="error", message='"routing" must be a list'))
        else:
            for i, rule_data in enumerate(obj["routing"]):
                if not isinstance(rule_data, dict):
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message=f'"routing[{i}]" must be a mapping',
                        )
                    )
                    continue
                try:
                    validated_routing.append(RoutingRule(**rule_data))
                except PydanticValidationError as err:
                    for e in err.errors():
                        diagnostics.append(
                            Diagnostic(
                                severity="error",
                                message=f"routing[{i}]: {e['msg']}",
                            )
                        )

    # Build the TicketMappingConfig (validates cross-references)
    try:
        mapping = TicketMappingConfig(
            auth_profiles=validated_auth,
            ticket_systems=validated_systems,
            routing=validated_routing,
        )
        # Warn about incomplete status maps
        for name, sys_config in mapping.ticket_systems.items():
            missing = sys_config.status_map.missing_forward_states()
            if sys_config.status_map.forward and missing:
                diagnostics.append(
                    Diagnostic(
                        severity="warning",
                        message=(
                            f"ticket_systems.{name}.status_map is missing forward mappings "
                            f"for: {', '.join(missing)}"
                        ),
                    )
                )
        return mapping
    except PydanticValidationError as err:
        for e in err.errors():
            diagnostics.append(Diagnostic(severity="error", message=e["msg"]))
        return None


def _merge_with_defaults(
    partial: dict[str, object],
    ticket_mapping: TicketMappingConfig | None = None,
) -> SpecwrightConfig:
    """Merge partial config dict with defaults."""
    specs_data = partial.get("specs")
    agents_data = partial.get("agents")

    specs = SpecsConfig()
    if isinstance(specs_data, dict):
        doc_paths_raw = specs_data.get("doc_paths")
        doc_paths = (
            doc_paths_raw
            if isinstance(doc_paths_raw, list)
            and all(isinstance(p, str) for p in doc_paths_raw)
            and len(doc_paths_raw) > 0
            else ["docs/specs/*.md"]
        )
        specs = SpecsConfig(
            auto_tickets=specs_data.get("auto_tickets", True)
            if isinstance(specs_data.get("auto_tickets"), bool)
            else True,
            require_review=specs_data.get("require_review", True)
            if isinstance(specs_data.get("require_review"), bool)
            else True,
            doc_paths=doc_paths,
        )

    agents = AgentsConfig()
    if isinstance(agents_data, dict):
        doc_updates = agents_data.get("doc_updates")
        pr_analysis = agents_data.get("pr_analysis")
        realization_check = agents_data.get("realization_check")
        stale_detection = agents_data.get("stale_detection")
        agents = AgentsConfig(
            doc_updates=doc_updates if isinstance(doc_updates, bool) else True,
            pr_analysis=pr_analysis if isinstance(pr_analysis, bool) else True,
            realization_check=realization_check if isinstance(realization_check, bool) else True,
            stale_detection=stale_detection
            if isinstance(stale_detection, str) or stale_detection is False
            else "30d",
        )

    return SpecwrightConfig(
        team=partial["team"] if isinstance(partial.get("team"), str) else None,
        ticket_system=partial["ticket_system"]
        if isinstance(partial.get("ticket_system"), str)
        and partial["ticket_system"] in VALID_TICKET_SYSTEMS
        else None,  # type: ignore[arg-type]
        project_key=partial["project_key"] if isinstance(partial.get("project_key"), str) else None,
        slack_channel=partial["slack_channel"]
        if isinstance(partial.get("slack_channel"), str)
        else None,
        specs=specs,
        agents=agents,
        ticket_mapping=ticket_mapping,
    )
