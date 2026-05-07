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
    "slack",
    "ticket_systems",
    "routing",
    "auth_profiles",
    "extensions",
    "triage",
}
KNOWN_SPECS_KEYS = {"auto_tickets", "require_review", "doc_paths", "lifecycle_sync"}
KNOWN_AGENTS_KEYS = {"doc_updates", "pr_analysis", "stale_detection", "realization_check"}
KNOWN_IDE_KEYS = {"auto_context", "auto_verify", "ai_exposure"}
KNOWN_IDE_AUTO_CONTEXT_KEYS = {"enabled", "on_session_start", "on_prompt", "max_specs"}
KNOWN_IDE_AUTO_VERIFY_KEYS = {"enabled", "on_stop", "on_commit", "confidence"}
KNOWN_IDE_AI_EXPOSURE_KEYS = {"default", "restricted_tags"}
KNOWN_SRE_KEYS = {"alerts_channel", "auto_triage", "weekly_digest", "error_spike_threshold"}
KNOWN_SLACK_KEYS = {
    "default_channel",
    "sre_channel",
    "notifications",
    "quiet_hours",
    "digest",
    "dashboard_refresh",
    "team_digests",
    "allow_shared_channels",
}
KNOWN_SLACK_NOTIFICATION_KEYS = {
    "spec_status_change",
    "spec_created",
    "coverage_regression",
    "stale_spec_warning",
    "pr_analysis_summary",
    "ticket_sync_failure",
    "review_requested",
    "coverage_threshold",
}
# When a notification type value is a dict, these are the valid keys
_NOTIFICATION_TYPE_SUBKEYS = {"enabled", "channel"}
KNOWN_SLACK_QUIET_HOURS_KEYS = {"start", "end"}
KNOWN_SLACK_DIGEST_KEYS = {"channel", "schedule", "team_digests"}

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


EvidencePersist = Literal["file", "mcp", "both"]
EvidenceCommitOnPush = Literal["ask", "always", "never"]


class EvidencePipelineConfig(BaseModel):
    """Plugin → GitHub App evidence pipeline (plugin-evidence-pipeline.md §3.2).

    Off by default; users opt in per-repo via CANON.yaml. When enabled, the
    Stop hook records dev-session evidence to .canon/session-evidence.json
    and the canon-verify gate writes to .canon/verify-log.jsonl.
    """

    enabled: bool = False
    persist: EvidencePersist = "file"
    commit_on_push: EvidenceCommitOnPush = "ask"


class SreConfig(BaseModel):
    alerts_channel: str = "#canon-alerts"
    auto_triage: bool = True
    weekly_digest: bool = True
    error_spike_threshold: int = 10


class SlackNotificationConfig(BaseModel):
    spec_status_change: bool = True
    spec_created: bool = True
    coverage_regression: bool = True
    stale_spec_warning: bool = True
    pr_analysis_summary: bool = True
    ticket_sync_failure: bool = True
    review_requested: bool = True
    coverage_threshold: int = 80
    # Per-notification-type channel overrides (type name -> channel)
    channel_overrides: dict[str, str] = {}


class SlackQuietHoursConfig(BaseModel):
    start: str = "22:00"
    end: str = "08:00"


class TeamDigestConfig(BaseModel):
    channel: str
    schedule: str = "monday 09:00"


class SlackDigestConfig(BaseModel):
    channel: str = ""
    schedule: str = "monday 09:00"
    team_digests: dict[str, TeamDigestConfig] = {}


class SlackTeamDigestConfig(BaseModel):
    channel: str
    schedule: str = "monday 09:00"


DashboardRefresh = Literal["daily", "weekly", False]


class SlackConfig(BaseModel):
    default_channel: str = "#canon-specs"
    sre_channel: str = ""
    notifications: SlackNotificationConfig = SlackNotificationConfig()
    quiet_hours: SlackQuietHoursConfig | None = None
    digest: SlackDigestConfig = SlackDigestConfig()
    dashboard_refresh: DashboardRefresh = False
    team_digests: dict[str, SlackTeamDigestConfig] = {}
    allow_shared_channels: bool = False


class IdeConfig(BaseModel):
    auto_context: AutoContextConfig = AutoContextConfig()
    auto_verify: AutoVerifyConfig = AutoVerifyConfig()
    ai_exposure: AiExposureConfig = AiExposureConfig()
    evidence_pipeline: EvidencePipelineConfig = EvidencePipelineConfig()


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


class TriageConfig(BaseModel):
    enabled: bool = True
    auto_create_specs: bool = False
    classify_labels: bool = True
    ignore_labels: list[str] = []
    ignore_authors: list[str] = []
    spec_template: str = "docs/specs/_template.md"
    confidence_threshold: float = 0.7


class CanonConfig(BaseModel):
    team: str | None = None
    ticket_system: TicketSystem | None = None
    project_key: str | None = None
    slack_channel: str | None = None
    specs: SpecsConfig = SpecsConfig()
    agents: AgentsConfig = AgentsConfig()
    ide: IdeConfig = IdeConfig()
    sre: SreConfig = SreConfig()
    slack: SlackConfig = SlackConfig()
    triage: TriageConfig = TriageConfig()
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

    # Validate slack section
    if "slack" in obj:
        if not isinstance(obj["slack"], dict):
            diagnostics.append(Diagnostic(severity="error", message='"slack" must be a mapping'))
            del obj["slack"]
        else:
            slack = obj["slack"]
            assert isinstance(slack, dict)
            for key in list(slack.keys()):
                if key not in KNOWN_SLACK_KEYS:
                    diagnostics.append(
                        Diagnostic(severity="warning", message=f'Unknown slack key: "{key}"')
                    )
            for key in ("default_channel", "sre_channel"):
                if key in slack and not isinstance(slack[key], str):
                    diagnostics.append(
                        Diagnostic(severity="error", message=f'"slack.{key}" must be a string')
                    )
                    del slack[key]
            if "notifications" in slack:
                if not isinstance(slack["notifications"], dict):
                    diagnostics.append(
                        Diagnostic(
                            severity="error", message='"slack.notifications" must be a mapping'
                        )
                    )
                    del slack["notifications"]
                else:
                    notif = slack["notifications"]
                    assert isinstance(notif, dict)
                    for key in list(notif.keys()):
                        if key not in KNOWN_SLACK_NOTIFICATION_KEYS:
                            diagnostics.append(
                                Diagnostic(
                                    severity="warning",
                                    message=f'Unknown slack.notifications key: "{key}"',
                                )
                            )
                        elif isinstance(notif[key], dict):
                            # Validate dict-form: {enabled: bool, channel: str}
                            for subkey in list(notif[key].keys()):
                                if subkey not in _NOTIFICATION_TYPE_SUBKEYS:
                                    diagnostics.append(
                                        Diagnostic(
                                            severity="warning",
                                            message=f'Unknown slack.notifications.{key} key: "{subkey}"',
                                        )
                                    )
            if "quiet_hours" in slack and not isinstance(slack["quiet_hours"], dict):
                diagnostics.append(
                    Diagnostic(severity="error", message='"slack.quiet_hours" must be a mapping')
                )
                del slack["quiet_hours"]
            if "digest" in slack:
                if not isinstance(slack["digest"], dict):
                    diagnostics.append(
                        Diagnostic(severity="error", message='"slack.digest" must be a mapping')
                    )
                    del slack["digest"]
                else:
                    digest = slack["digest"]
                    assert isinstance(digest, dict)
                    for key in list(digest.keys()):
                        if key not in KNOWN_SLACK_DIGEST_KEYS:
                            diagnostics.append(
                                Diagnostic(
                                    severity="warning",
                                    message=f'Unknown slack.digest key: "{key}"',
                                )
                            )
                    # Validate team_digests sub-key
                    if "team_digests" in digest:
                        td = digest["team_digests"]
                        if not isinstance(td, dict):
                            diagnostics.append(
                                Diagnostic(
                                    severity="error",
                                    message='"slack.digest.team_digests" must be a mapping',
                                )
                            )
                            del digest["team_digests"]
                        else:
                            for team_name, team_data in list(td.items()):
                                if not isinstance(team_data, dict):
                                    diagnostics.append(
                                        Diagnostic(
                                            severity="error",
                                            message=f'"slack.digest.team_digests.{team_name}" must be a mapping',
                                        )
                                    )
                                    del td[team_name]
                                elif "channel" not in team_data or not isinstance(
                                    team_data.get("channel"), str
                                ):
                                    diagnostics.append(
                                        Diagnostic(
                                            severity="error",
                                            message=f'"slack.digest.team_digests.{team_name}.channel" is required and must be a string',
                                        )
                                    )
                                    del td[team_name]

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
    # ⚠️ When you add a new field to IdeConfig, you MUST also add explicit
    # parsing for it here. This function does NOT use IdeConfig.model_validate
    # — it constructs IdeConfig field-by-field with hand-rolled type guards
    # so that invalid YAML degrades gracefully to defaults instead of raising.
    # New fields without explicit parsing here will silently fall back to
    # the model default and ignore the user's CANON.yaml value.
    # See: plugin-evidence-pipeline.md execution notes (Phase C foundation
    # surfaced this gotcha when adding evidence_pipeline).
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

        ep_data = ide_data.get("evidence_pipeline")
        evidence_pipeline = EvidencePipelineConfig()
        if isinstance(ep_data, dict):
            valid_persist = {"file", "mcp", "both"}
            valid_commit = {"ask", "always", "never"}
            evidence_pipeline = EvidencePipelineConfig(
                enabled=ep_data["enabled"] if isinstance(ep_data.get("enabled"), bool) else False,
                persist=ep_data["persist"]
                if isinstance(ep_data.get("persist"), str) and ep_data["persist"] in valid_persist
                else "file",
                commit_on_push=ep_data["commit_on_push"]
                if isinstance(ep_data.get("commit_on_push"), str)
                and ep_data["commit_on_push"] in valid_commit
                else "ask",
            )

        ide = IdeConfig(
            auto_context=auto_context,
            auto_verify=auto_verify,
            ai_exposure=ai_exposure,
            evidence_pipeline=evidence_pipeline,
        )

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

    slack_data = partial.get("slack")
    slack = SlackConfig()
    if isinstance(slack_data, dict):
        notif_data = slack_data.get("notifications")
        notifications = SlackNotificationConfig()
        if isinstance(notif_data, dict):
            kwargs: dict = {}
            channel_overrides: dict[str, str] = {}
            for key in (
                "spec_status_change",
                "spec_created",
                "coverage_regression",
                "stale_spec_warning",
                "pr_analysis_summary",
                "ticket_sync_failure",
                "review_requested",
            ):
                val = notif_data.get(key)
                if isinstance(val, bool):
                    kwargs[key] = val
                elif isinstance(val, dict):
                    # Dict form: {enabled: bool, channel: str}
                    if isinstance(val.get("enabled"), bool):
                        kwargs[key] = val["enabled"]
                    if isinstance(val.get("channel"), str):
                        channel_overrides[key] = val["channel"]
            if isinstance(notif_data.get("coverage_threshold"), int) and not isinstance(
                notif_data.get("coverage_threshold"), bool
            ):
                kwargs["coverage_threshold"] = notif_data["coverage_threshold"]
            if channel_overrides:
                kwargs["channel_overrides"] = channel_overrides
            notifications = SlackNotificationConfig(**kwargs)

        qh_data = slack_data.get("quiet_hours")
        quiet_hours = None
        if isinstance(qh_data, dict):
            quiet_hours = SlackQuietHoursConfig(
                start=qh_data["start"] if isinstance(qh_data.get("start"), str) else "22:00",
                end=qh_data["end"] if isinstance(qh_data.get("end"), str) else "08:00",
            )

        digest_data = slack_data.get("digest")
        digest = SlackDigestConfig()
        if isinstance(digest_data, dict):
            # Parse team_digests
            team_digests_data = digest_data.get("team_digests")
            team_digests: dict[str, TeamDigestConfig] = {}
            if isinstance(team_digests_data, dict):
                for team_name, td in team_digests_data.items():
                    if isinstance(td, dict) and isinstance(td.get("channel"), str):
                        team_digests[team_name] = TeamDigestConfig(
                            channel=td["channel"],
                            schedule=td["schedule"]
                            if isinstance(td.get("schedule"), str)
                            else "monday 09:00",
                        )

            digest = SlackDigestConfig(
                channel=digest_data["channel"]
                if isinstance(digest_data.get("channel"), str)
                else "",
                schedule=digest_data["schedule"]
                if isinstance(digest_data.get("schedule"), str)
                else "monday 09:00",
                team_digests=team_digests,
            )

        # Parse dashboard_refresh (daily/weekly/false)
        dr_raw = slack_data.get("dashboard_refresh", False)
        dashboard_refresh: DashboardRefresh = False
        if dr_raw in ("daily", "weekly"):
            dashboard_refresh = dr_raw  # type: ignore[assignment]

        # Parse team_digests
        team_digests: dict[str, SlackTeamDigestConfig] = {}
        td_data = slack_data.get("team_digests")
        if isinstance(td_data, dict):
            for team_name, td_entry in td_data.items():
                if isinstance(td_entry, dict) and isinstance(td_entry.get("channel"), str):
                    team_digests[team_name] = SlackTeamDigestConfig(
                        channel=td_entry["channel"],
                        schedule=td_entry["schedule"]
                        if isinstance(td_entry.get("schedule"), str)
                        else "monday 09:00",
                    )

        slack = SlackConfig(
            default_channel=slack_data["default_channel"]
            if isinstance(slack_data.get("default_channel"), str)
            else "#canon-specs",
            sre_channel=slack_data["sre_channel"]
            if isinstance(slack_data.get("sre_channel"), str)
            else "",
            notifications=notifications,
            quiet_hours=quiet_hours,
            digest=digest,
            dashboard_refresh=dashboard_refresh,
            team_digests=team_digests,
            allow_shared_channels=bool(slack_data.get("allow_shared_channels", False)),
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
        slack=slack,
        ticket_mapping=ticket_mapping,
    )
