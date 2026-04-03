"""Permission and Role enums for multi-tenant RBAC."""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    """Fine-grained permissions for Canon resources."""

    SPECS_READ = "specs:read"
    SPECS_WRITE = "specs:write"
    SPECS_ADMIN = "specs:admin"
    ORG_MANAGE = "org:manage"
    PLATFORM_MANAGE = "platform:manage"


class Role(StrEnum):
    """Pre-defined roles that map to permission sets.

    In single-tenant OSS mode (``auth0_orgs_enabled=False``), ``users.role`` is
    looked up from the DB and mapped to permissions via ``ROLE_PERMISSIONS`` in
    ``deps._resolve_permissions``.  In multi-tenant cloud mode
    (``auth0_orgs_enabled=True``), permissions come directly from JWT claims.
    """

    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


#: Mapping from role → granted permissions (cumulative).
#: Used by ``_resolve_permissions`` in ``deps.py`` for single-tenant OSS
#: user resolution.
#: ADMIN gets all permissions except PLATFORM_MANAGE; SUPER_ADMIN gets all.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.SPECS_READ}),
    Role.EDITOR: frozenset({Permission.SPECS_READ, Permission.SPECS_WRITE}),
    Role.ADMIN: frozenset(p for p in Permission if p != Permission.PLATFORM_MANAGE),
    Role.SUPER_ADMIN: frozenset(Permission),  # all permissions
}


def permissions_for_role(role: Role) -> frozenset[Permission]:
    """Return the set of permissions granted by a role."""
    return ROLE_PERMISSIONS.get(role, frozenset())


#: All valid permission strings (for validation).
ALL_PERMISSION_VALUES: frozenset[str] = frozenset(p.value for p in Permission)

#: Human-readable descriptions for each permission.
#: Every ``Permission`` member must have an entry (enforced by tests).
PERMISSION_DESCRIPTIONS: dict[str, str] = {
    Permission.SPECS_READ.value: "Read access to specs",
    Permission.SPECS_WRITE.value: "Create and edit specs",
    Permission.SPECS_ADMIN.value: "Manage spec settings and configuration",
    Permission.ORG_MANAGE.value: "Manage organization settings",
    Permission.PLATFORM_MANAGE.value: "Manage platform-wide settings and super-admin operations",
}
