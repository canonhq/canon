"""CANON.yaml parser with Pydantic validation."""

from __future__ import annotations

import re
from typing import Literal, get_args

import yaml
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from canon.parser.models import VALID_AI_EXPOSURES as VALID_AI_EXPOSURE_DEFAULTS
from canon.parser.models import AiExposure as AiExposureDefault
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
    "ide",
    "sre",
    "ticket_systems",
    "routing",
    "auth_profiles",
}
KNOWN_SPECS_KEYS = {"auto_tickets", "require_review", "doc_paths", "lifecycle_sync"}
KNOWN_AGENTS_KEYS = {"doc_updates", "pr_analysis", "stale_detection", "realization_check"}
KNOWN_IDE_KEYS = {"auto_context", "auto_verify", "ai_exposure"}
KNOWN_IDE_AUTO_CONTEXT_KEYS = {"enabled", "on_session_start", "on_prompt", "max_specs"}
KNOWN_IDE_AUTO_VERIFY_KEYS = {"enabled", "on_stop", "on_commit", "confidence"}
KNOWN_IDE_AI_EXPOSURE_KEYS = {"default", "restricted_tags"}
KNOWN_SRE_KEYS = {"alerts_channel", "auto_triage", "weekly_digest", "error_spike_threshold"}

ConfidenceLevel = Literal["medium", "high"]
VALID_CONFIDENCE_LEVELS: frozenset[str] = frozenset(get_args(ConfidenceLevel))

DURATION_RE = re.compile(r"^\d+d$")


class AutoContextConfig(BaseModel):
    enabled: bool = True
    on_session_start: bool = True
    on_prompt: bool = True
    max_specs: int = 5


class AutoVerifyConfig(BaseModel):
    enabled: bool = True
    on_stop: bool = True
    on_commit: bool = False
    # Reserved for future use — not yet consumed by hook scripts.
    confidence: ConfidenceLevel = "medium"


class AiExposureConfig(BaseModel):
    default: AiExposureDefault = "full"
    # Tags that auto-restrict matching specs to "metadata" exposure.
    # Cannot enforce "none" — that requires explicit per-spec frontmatter.
    restricted_tags: list[str] = []


class SreConfig(BaseModel):
    alerts_channel: str = "#canon-alerts"
    auto_triage: bool = True
    weekly_digest: bool = True
    error_spike_threshold: int = 10


class IdeConfig(BaseModel):
    auto_context: AutoContextConfig = AutoContextConfig()
    auto_verify: AutoVerifyConfig = AutoVerifyConfig()
    ai_exposure: AiExposureConfig = AiExposureConfig()


class SpecsConfig(BaseModel):
    auto_tickets: bool = True
    require_review: bool = True
    doc_paths: list[str] = ["docs/specs/*.md"]
    lifecycle_sync: bool | Literal["close_only"] = True


class AgentsConfig(BaseModel):
    doc_updates: bool = True
    pr_analysis: bool = True
    realization_check: bool = True
    stale_detection: str | Literal[False] = "30d"


class CanonConfig(BaseModel):
    team: str | None = None
    ticket_system: TicketSystem | None = None
    project_key: str | None = None
    slack_channel: str | None = None
    specs: SpecsConfig = SpecsConfig()
    agents: AgentsConfig = AgentsConfig()
    ide: IdeConfig = IdeConfig()
    sre: SreConfig = SreConfig()
    ticket_mapping: TicketMappingConfig | None = None


# Deprecated alias
SpecwrightConfig = CanonConfig


class ConfigResult(BaseModel):
    config: CanonConfig
    diagnostics: list[Diagnostic]


DEFAULT_CONFIG = CanonConfig()


# ─── Public API ───────────────────────────────────────────


def parse_canon_yaml(raw: str) -> ConfigResult:
    """Parse and validate CANON.yaml content."""
    diagnostics: list[Diagnostic] = []

    if not raw.strip():
        return ConfigResult(
            config=CanonConfig(),
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
            config=CanonConfig(),
            diagnostics=[Diagnostic(severity="error", message=f"Invalid YAML: {err}")],
        )

    if not isinstance(parsed, dict):
        return ConfigResult(
            config=CanonConfig(),
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

            if "lifecycle_sync" in specs:
                ls = specs["lifecycle_sync"]
                if ls is not True and ls is not False and ls != "close_only":
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            message='"specs.lifecycle_sync" must be true, false, or "close_only"',
                        )
                    )
                    del specs["lifecycle_sync"]

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

    # Validate ide section
    if "ide" in obj:
        if not isinstance(obj["ide"], dict):
            diagnostics.append(Diagnostic(severity="error", message='"ide" must be a mapping'))
            del obj["ide"]
        else:
            ide = obj["ide"]
            assert isinstance(ide, dict)
            for key in list(ide.keys()):
                if key not in KNOWN_IDE_KEYS:
                    diagnostics.append(
                        Diagnostic(severity="warning", message=f'Unknown ide key: "{key}"')
                    )

            # Validate auto_context sub-section
            if "auto_context" in ide:
                if not isinstance(ide["auto_context"], dict):
                    diagnostics.append(
                        Diagnostic(severity="error", message='"ide.auto_context" must be a mapping')
                    )
                    del ide["auto_context"]
                else:
                    ac = ide["auto_context"]
                    assert isinstance(ac, dict)
                    for key in list(ac.keys()):
                        if key not in KNOWN_IDE_AUTO_CONTEXT_KEYS:
                            diagnostics.append(
                                Diagnostic(
                                    severity="warning",
                                    message=f'Unknown ide.auto_context key: "{key}"',
                                )
                            )
                    for key in ("enabled", "on_session_start", "on_prompt"):
                        if key in ac and not isinstance(ac[key], bool):
                            diagnostics.append(
                                Diagnostic(
                                    severity="error",
                                    message=f'"ide.auto_context.{key}" must be a boolean',
                                )
                            )
                            del ac[key]
                    if "max_specs" in ac:
                        ms = ac["max_specs"]
                        if isinstance(ms, bool) or not isinstance(ms, int):
                            diagnostics.append(
                                Diagnostic(
                                    severity="error",
                                    message='"ide.auto_context.max_specs" must be an integer',
                                )
                            )
                            del ac["max_specs"]
                        elif ms < 1:
                            diagnostics.append(
                                Diagnostic(
                                    severity="error",
                                    message='"ide.auto_context.max_specs" must be >= 1',
                                )
                            )
                            del ac["max_specs"]

            # Validate auto_verify sub-section
            if "auto_verify" in ide:
                if not isinstance(ide["auto_verify"], dict):
                    diagnostics.append(
                        Diagnostic(severity="error", message='"ide.auto_verify" must be a mapping')
                    )
                    del ide["auto_verify"]
                else:
                    av = ide["auto_verify"]
                    assert isinstance(av, dict)
                    for key in list(av.keys()):
                        if key not in KNOWN_IDE_AUTO_VERIFY_KEYS:
                            diagnostics.append(
                                Diagnostic(
                                    severity="warning",
                                    message=f'Unknown ide.auto_verify key: "{key}"',
                                )
                            )
                    for key in ("enabled", "on_stop", "on_commit"):
                        if key in av and not isinstance(av[key], bool):
                            diagnostics.append(
                                Diagnostic(
                                    severity="error",
                                    message=f'"ide.auto_verify.{key}" must be a boolean',
                                )
                            )
                            del av[key]
                    if "confidence" in av and av["confidence"] not in VALID_CONFIDENCE_LEVELS:
                        diagnostics.append(
                            Diagnostic(
                                severity="error",
                                message=(
                                    f'"ide.auto_verify.confidence" must be one of: '
                                    f"{', '.join(sorted(VALID_CONFIDENCE_LEVELS))}"
                                ),
                            )
                        )
                        del av["confidence"]

            # Validate ai_exposure sub-section
            if "ai_exposure" in ide:
                if not isinstance(ide["ai_exposure"], dict):
                    diagnostics.append(
                        Diagnostic(severity="error", message='"ide.ai_exposure" must be a mapping')
                    )
                    del ide["ai_exposure"]
                else:
                    ae = ide["ai_exposure"]
                    assert isinstance(ae, dict)
                    for key in list(ae.keys()):
                        if key not in KNOWN_IDE_AI_EXPOSURE_KEYS:
                            diagnostics.append(
                                Diagnostic(
                                    severity="warning",
                                    message=f'Unknown ide.ai_exposure key: "{key}"',
                                )
                            )
                    if "default" in ae and ae["default"] not in VALID_AI_EXPOSURE_DEFAULTS:
                        diagnostics.append(
                            Diagnostic(
                                severity="error",
                                message=(
                                    f'"ide.ai_exposure.default" must be one of: '
                                    f"{', '.join(sorted(VALID_AI_EXPOSURE_DEFAULTS))}"
                                ),
                            )
                        )
                        del ae["default"]
                    if "restricted_tags" in ae:
                        rt = ae["restricted_tags"]
                        if not isinstance(rt, list) or not all(isinstance(t, str) for t in rt):
                            diagnostics.append(
                                Diagnostic(
                                    severity="error",
                                    message='"ide.ai_exposure.restricted_tags" must be a list of strings',
                                )
                            )
                            del ae["restricted_tags"]

    # Validate sre section
    if "sre" in obj:
        if not isinstance(obj["sre"], dict):
            diagnostics.append(Diagnostic(severity="error", message='"sre" must be a mapping'))
            del obj["sre"]
        else:
            sre = obj["sre"]
            assert isinstance(sre, dict)
            for key in list(sre.keys()):
                if key not in KNOWN_SRE_KEYS:
                    diagnostics.append(
                        Diagnostic(severity="warning", message=f'Unknown sre key: "{key}"')
                    )
            for key in ("auto_triage", "weekly_digest"):
                if key in sre and not isinstance(sre[key], bool):
                    diagnostics.append(
                        Diagnostic(severity="error", message=f"sre.{key} must be a boolean")
                    )
                    del sre[key]
            if "error_spike_threshold" in sre and (
                not isinstance(sre["error_spike_threshold"], int)
                or isinstance(sre["error_spike_threshold"], bool)
            ):
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        message="sre.error_spike_threshold must be an integer",
                    )
                )
                del sre["error_spike_threshold"]
            if "alerts_channel" in sre and not isinstance(sre["alerts_channel"], str):
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        message="sre.alerts_channel must be a string",
                    )
                )
                del sre["alerts_channel"]

    # Validate ticket_systems / routing / auth_profiles
    ticket_mapping = _parse_ticket_mapping(obj, diagnostics)

    config = _merge_with_defaults(obj, ticket_mapping)
    return ConfigResult(config=config, diagnostics=diagnostics)


# Deprecated alias
parse_specwright_yaml = parse_canon_yaml


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
) -> CanonConfig:
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
        lifecycle_raw = specs_data.get("lifecycle_sync", True)
        lifecycle_sync: bool | str = True
        if lifecycle_raw is True or lifecycle_raw is False:
            lifecycle_sync = lifecycle_raw
        elif lifecycle_raw == "close_only":
            lifecycle_sync = "close_only"

        specs = SpecsConfig(
            auto_tickets=specs_data.get("auto_tickets", True)
            if isinstance(specs_data.get("auto_tickets"), bool)
            else True,
            require_review=specs_data.get("require_review", True)
            if isinstance(specs_data.get("require_review"), bool)
            else True,
            doc_paths=doc_paths,
            lifecycle_sync=lifecycle_sync,
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

    ide_data = partial.get("ide")
    ide = IdeConfig()
    if isinstance(ide_data, dict):
        ac_data = ide_data.get("auto_context")
        auto_context = AutoContextConfig()
        if isinstance(ac_data, dict):
            auto_context = AutoContextConfig(
                enabled=ac_data["enabled"] if isinstance(ac_data.get("enabled"), bool) else True,
                on_session_start=ac_data["on_session_start"]
                if isinstance(ac_data.get("on_session_start"), bool)
                else True,
                on_prompt=ac_data["on_prompt"]
                if isinstance(ac_data.get("on_prompt"), bool)
                else True,
                max_specs=ac_data["max_specs"]
                if isinstance(ac_data.get("max_specs"), int)
                and not isinstance(ac_data.get("max_specs"), bool)
                and ac_data["max_specs"] >= 1
                else 5,
            )

        av_data = ide_data.get("auto_verify")
        auto_verify = AutoVerifyConfig()
        if isinstance(av_data, dict):
            auto_verify = AutoVerifyConfig(
                enabled=av_data["enabled"] if isinstance(av_data.get("enabled"), bool) else True,
                on_stop=av_data["on_stop"] if isinstance(av_data.get("on_stop"), bool) else True,
                on_commit=av_data["on_commit"]
                if isinstance(av_data.get("on_commit"), bool)
                else False,
                confidence=av_data["confidence"]
                if isinstance(av_data.get("confidence"), str)
                and av_data["confidence"] in VALID_CONFIDENCE_LEVELS
                else "medium",
            )

        ae_data = ide_data.get("ai_exposure")
        ai_exposure = AiExposureConfig()
        if isinstance(ae_data, dict):
            rt = ae_data.get("restricted_tags")
            ai_exposure = AiExposureConfig(
                default=ae_data["default"]
                if isinstance(ae_data.get("default"), str)
                and ae_data["default"] in VALID_AI_EXPOSURE_DEFAULTS
                else "full",
                restricted_tags=rt
                if isinstance(rt, list) and all(isinstance(t, str) for t in rt)
                else [],
            )

        ide = IdeConfig(auto_context=auto_context, auto_verify=auto_verify, ai_exposure=ai_exposure)

    sre_data = partial.get("sre")
    sre = SreConfig()
    if isinstance(sre_data, dict):
        sre = SreConfig(
            alerts_channel=sre_data["alerts_channel"]
            if isinstance(sre_data.get("alerts_channel"), str)
            else "#canon-alerts",
            auto_triage=sre_data["auto_triage"]
            if isinstance(sre_data.get("auto_triage"), bool)
            else True,
            weekly_digest=sre_data["weekly_digest"]
            if isinstance(sre_data.get("weekly_digest"), bool)
            else True,
            error_spike_threshold=sre_data["error_spike_threshold"]
            if isinstance(sre_data.get("error_spike_threshold"), int)
            and not isinstance(sre_data.get("error_spike_threshold"), bool)
            else 10,
        )

    return CanonConfig(
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
        ide=ide,
        sre=sre,
        ticket_mapping=ticket_mapping,
    )
