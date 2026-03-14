"""Configurable ticket mapping models for enterprise ticket sync.

Defines the schema for mapping spec constructs (sections, statuses, fields)
to ticket system concepts (issue types, statuses, custom fields, hierarchy).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, model_validator

# ─── Valid spec states (mirrors parser.models.SectionStatus) ─────

SPEC_STATES: frozenset[str] = frozenset(
    ["draft", "todo", "in_progress", "done", "blocked", "deprecated"]
)

# ─── Valid sources for field mapping ─────────────────────────────

VALID_FIELD_SOURCES: frozenset[str] = frozenset(
    [
        "frontmatter.title",
        "frontmatter.status",
        "frontmatter.owner",
        "frontmatter.team",
        "frontmatter.tags",
        "frontmatter.doc_type",
        "frontmatter.depends_on",
        "section.title",
        "section.section_number",
        "section.content",
        "section.acceptance_criteria",
        "section.depth",
        "section.id",
    ]
)

VALID_AUTH_METHODS: frozenset[str] = frozenset(
    ["api_token", "personal_access_token", "api_key", "app_installation"]
)

VALID_SYSTEMS: frozenset[str] = frozenset(["jira", "linear", "github"])


# ─── Status Mapping ─────────────────────────────────────────────


class StatusMapConfig(BaseModel):
    """Bidirectional status mapping between spec states and ticket statuses."""

    forward: dict[str, str] = {}
    """spec_state → ticket_status_name"""

    reverse: dict[str, str] = {}
    """ticket_status (name or category key) → spec_state"""

    fallback: str = "draft"
    """Unmapped ticket statuses resolve to this spec state."""

    @model_validator(mode="after")
    def _check_forward_keys(self) -> StatusMapConfig:
        for key in self.forward:
            if key not in SPEC_STATES:
                raise ValueError(
                    f"Invalid spec state in status_map.forward: {key!r}. "
                    f"Valid states: {sorted(SPEC_STATES)}"
                )
        if self.fallback not in SPEC_STATES:
            raise ValueError(
                f"Invalid fallback state: {self.fallback!r}. Valid states: {sorted(SPEC_STATES)}"
            )
        return self

    def missing_forward_states(self) -> list[str]:
        """Return spec states not covered by the forward map."""
        return sorted(SPEC_STATES - set(self.forward.keys()))


# ─── Field Mapping ───────────────────────────────────────────────


class FieldMapConfig(BaseModel):
    """Declarative mapping from spec metadata to ticket fields."""

    standard: dict[str, str] = {}
    """spec_source → ticket_field (e.g. "frontmatter.team": "component")"""

    custom: dict[str, str] = {}
    """custom_field_id → spec_source or "literal:value" """

    @model_validator(mode="after")
    def _check_sources(self) -> FieldMapConfig:
        for source in self.standard:
            if source not in VALID_FIELD_SOURCES:
                raise ValueError(
                    f"Invalid field map source: {source!r}. "
                    f"Valid sources: {sorted(VALID_FIELD_SOURCES)}"
                )
        for _field_id, source in self.custom.items():
            if source.startswith("literal:"):
                continue
            # Allow indexed access like "frontmatter.tags[0]"
            base_source = source.split("[")[0]
            if base_source not in VALID_FIELD_SOURCES:
                raise ValueError(
                    f"Invalid custom field source: {source!r}. "
                    f"Valid sources: {sorted(VALID_FIELD_SOURCES)} "
                    f"or 'literal:<value>'"
                )
        return self


# ─── Hierarchy ───────────────────────────────────────────────────


class HierarchyConfig(BaseModel):
    """Maps spec section depth to ticket issue types."""

    depth_to_type: dict[int, str] = {}
    """section_depth → issue_type (e.g. {2: "Epic", 3: "Story"})"""

    auto_parent: bool = False
    """When True, child section tickets are linked to parent section tickets."""

    default_type: str = "Task"
    """Issue type used when depth is not in depth_to_type."""

    @model_validator(mode="after")
    def _check_types(self) -> HierarchyConfig:
        for depth, issue_type in self.depth_to_type.items():
            if not isinstance(issue_type, str) or not issue_type.strip():
                raise ValueError(f"Issue type for depth {depth} must be a non-empty string")
        if not self.default_type.strip():
            raise ValueError("default_type must be a non-empty string")
        return self


# ─── Templates ───────────────────────────────────────────────────


class TemplateConfig(BaseModel):
    """Configurable templates for ticket summary and description."""

    summary: str | None = None
    """Jinja2-style template for ticket summary."""

    description: str | None = None
    """Jinja2-style template for ticket description body."""


# ─── Auth Profiles ───────────────────────────────────────────────


class AuthProfile(BaseModel):
    """Named credential set for a ticket system connection."""

    system: str
    """Ticket system type: jira, linear, github."""

    auth_method: str
    """Authentication method: api_token, personal_access_token, api_key, app_installation."""

    env_prefix: str
    """Environment variable prefix (e.g. "JIRA_CLOUD_" reads JIRA_CLOUD_HOST, etc.)."""

    @model_validator(mode="after")
    def _check_values(self) -> AuthProfile:
        if self.system not in VALID_SYSTEMS:
            raise ValueError(
                f"Invalid auth profile system: {self.system!r}. Valid: {sorted(VALID_SYSTEMS)}"
            )
        if self.auth_method not in VALID_AUTH_METHODS:
            raise ValueError(
                f"Invalid auth method: {self.auth_method!r}. Valid: {sorted(VALID_AUTH_METHODS)}"
            )
        if not self.env_prefix.strip():
            raise ValueError("env_prefix must be a non-empty string")
        if not re.match(r"^[A-Z][A-Z0-9_]*_$", self.env_prefix):
            raise ValueError(
                f"env_prefix must match ^[A-Z][A-Z0-9_]*_$ (got {self.env_prefix!r}). "
                f"Ensure it ends with an underscore (e.g. 'JIRA_CLOUD_')."
            )
        return self


# ─── Ticket System Config ────────────────────────────────────────


class TicketSystemConfig(BaseModel):
    """Full configuration for a single ticket system connection."""

    system: str
    """Ticket system type: jira, linear, github."""

    project: str | None = None
    """Project key (e.g. "PAY" for Jira, team key for Linear, "org/repo" for GitHub).

    May be None when the project key is provided via spec frontmatter
    ``ticket_project`` at sync time rather than in the config.
    """

    auth_profile: str | None = None
    """Reference to a named AuthProfile. When None, uses default env var detection."""

    host_override: str | None = None
    """Override the default host for this system (e.g. different Jira instance)."""

    status_map: StatusMapConfig = StatusMapConfig()
    field_map: FieldMapConfig = FieldMapConfig()
    hierarchy: HierarchyConfig = HierarchyConfig()
    templates: TemplateConfig = TemplateConfig()
    dedup_enabled: bool = True
    """When True, search for existing tickets before creating new ones."""

    @model_validator(mode="after")
    def _check_system(self) -> TicketSystemConfig:
        if self.system not in VALID_SYSTEMS:
            raise ValueError(
                f"Invalid ticket system: {self.system!r}. Valid: {sorted(VALID_SYSTEMS)}"
            )
        return self


# ─── Routing ─────────────────────────────────────────────────────


class RoutingRule(BaseModel):
    """Route spec sections to ticket systems based on metadata matching."""

    match: dict[str, Any]
    """Match criteria: tags (list), team (str), owner (str), path (glob), default (bool)."""

    target: str
    """Name of the ticket system config to route to."""

    @model_validator(mode="after")
    def _check_match(self) -> RoutingRule:
        valid_keys = {"tags", "team", "owner", "path", "default"}
        for key in self.match:
            if key not in valid_keys:
                raise ValueError(f"Invalid routing match key: {key!r}. Valid: {sorted(valid_keys)}")
        if not self.match:
            raise ValueError("Routing rule must have at least one match criterion")
        if self.match.get("default") is True and len(self.match) > 1:
            raise ValueError(
                "Routing rule with 'default: true' cannot have other match criteria — "
                "default always matches, so additional criteria would be silently ignored"
            )
        return self


# ─── Top-Level Mapping Config ────────────────────────────────────


class TicketMappingConfig(BaseModel):
    """Top-level ticket mapping configuration.

    Combines auth profiles, system configs, and routing rules
    into a single coherent mapping model.
    """

    auth_profiles: dict[str, AuthProfile] = {}
    ticket_systems: dict[str, TicketSystemConfig] = {}
    routing: list[RoutingRule] = []
    org_defaults_source: str | None = None

    @model_validator(mode="after")
    def _check_references(self) -> TicketMappingConfig:
        # Validate auth_profile references
        for name, system_config in self.ticket_systems.items():
            if system_config.auth_profile and system_config.auth_profile not in self.auth_profiles:
                raise ValueError(
                    f"Ticket system {name!r} references unknown auth profile "
                    f"{system_config.auth_profile!r}. "
                    f"Available: {sorted(self.auth_profiles.keys()) or '(none)'}"
                )

        # Validate routing targets
        for i, rule in enumerate(self.routing):
            if rule.target not in self.ticket_systems:
                raise ValueError(
                    f"Routing rule {i} targets unknown ticket system {rule.target!r}. "
                    f"Available: {sorted(self.ticket_systems.keys()) or '(none)'}"
                )

        return self

    def is_empty(self) -> bool:
        """True when no ticket systems are configured."""
        return len(self.ticket_systems) == 0

    def single_system(self) -> TicketSystemConfig | None:
        """Return the sole system config if exactly one is defined, else None."""
        if len(self.ticket_systems) == 1:
            return next(iter(self.ticket_systems.values()))
        return None


# ─── Backward Compatibility ──────────────────────────────────────


def synthesize_mapping_config(
    *,
    ticket_system: str | None,
    project_key: str | None,
    ticket_mapping: TicketMappingConfig | None,
) -> tuple[TicketMappingConfig, bool]:
    """Synthesize a TicketMappingConfig from legacy or new config fields.

    Returns (config, is_deprecated) where ``is_deprecated`` is True when
    both legacy and new-style config coexist (legacy should be removed).

    Priority:
    1. ``ticket_mapping`` (new-style) takes precedence when present
    2. Legacy ``ticket_system`` + ``project_key`` is synthesized into a
       TicketMappingConfig with a single system named "primary"
    3. When neither is set, returns an empty config
    """
    # Legacy config: ticket_system alone is enough (project_key may come from frontmatter)
    has_legacy = ticket_system is not None
    has_new = ticket_mapping is not None and not ticket_mapping.is_empty()

    if has_new and has_legacy:
        return ticket_mapping, True  # deprecation warning

    if has_new:
        return ticket_mapping, False

    if has_legacy:
        assert ticket_system is not None  # for type narrowing
        return TicketMappingConfig(
            ticket_systems={
                "primary": TicketSystemConfig(
                    system=ticket_system,
                    project=project_key or "",
                )
            }
        ), False

    return TicketMappingConfig(), False


# ─── Org-Level Config Deep Merge ─────────────────────────────


def deep_merge_dicts(base: dict, override: dict) -> dict:
    """Deep-merge two dicts: maps merge key-by-key, scalars are overridden.

    Lists are replaced (not appended). An explicit ``None`` value in
    ``override`` removes the key from the result.
    """
    result = dict(base)
    for key, value in override.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def deep_merge_configs(
    org: TicketMappingConfig,
    repo: TicketMappingConfig,
) -> TicketMappingConfig:
    """Deep-merge a repo-level config on top of org-level defaults.

    Merge strategy:
    - ``auth_profiles``: merged key-by-key (repo overrides org)
    - ``ticket_systems``: merged key-by-key; each system's sub-objects
      (status_map, field_map, hierarchy, templates) are deep-merged
    - ``routing``: replaced entirely (repo routing replaces org routing)
    - ``org_defaults_source``: repo value wins if set

    A repo can null-out an org default by setting the value to ``null``
    in YAML (e.g. ``host_override: null``), which produces an explicit
    ``None`` in the override dict that ``deep_merge_dicts`` removes.
    """
    # Merge auth profiles (simple key-by-key)
    merged_profiles = {**org.auth_profiles, **repo.auth_profiles}

    # Merge ticket systems: deep-merge each system's config
    merged_systems: dict[str, TicketSystemConfig] = {}
    all_system_names = set(org.ticket_systems) | set(repo.ticket_systems)
    for name in all_system_names:
        org_sys = org.ticket_systems.get(name)
        repo_sys = repo.ticket_systems.get(name)

        if repo_sys and org_sys:
            # Deep-merge: dump both to dicts and merge.
            # org uses all fields (base layer); repo uses exclude_unset so
            # only explicitly-provided fields participate — otherwise
            # None-defaulting optional fields (project, auth_profile, etc.)
            # would strip the org value via the "None removes key" rule.
            org_dict = org_sys.model_dump(exclude_defaults=False)
            repo_dict = repo_sys.model_dump(exclude_unset=True)
            merged_dict = deep_merge_dicts(org_dict, repo_dict)
            merged_systems[name] = TicketSystemConfig(**merged_dict)
        elif repo_sys:
            merged_systems[name] = repo_sys
        elif org_sys:
            merged_systems[name] = org_sys

    # Routing: repo replaces org entirely (if repo defines any)
    merged_routing = repo.routing if repo.routing else org.routing

    # org_defaults_source: repo wins
    merged_source = repo.org_defaults_source or org.org_defaults_source

    return TicketMappingConfig(
        auth_profiles=merged_profiles,
        ticket_systems=merged_systems,
        routing=merged_routing,
        org_defaults_source=merged_source,
    )
