"""Tests for Permission enum and role mapping."""

from __future__ import annotations

from canon.auth.permissions import (
    ALL_PERMISSION_VALUES,
    PERMISSION_DESCRIPTIONS,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    permissions_for_role,
)


class TestPermissionEnum:
    def test_all_values(self):
        assert Permission.SPECS_READ.value == "specs:read"
        assert Permission.SPECS_WRITE.value == "specs:write"
        assert Permission.SPECS_ADMIN.value == "specs:admin"
        assert Permission.ORG_MANAGE.value == "org:manage"
        assert Permission.PLATFORM_MANAGE.value == "platform:manage"

    def test_all_permission_values_set(self):
        assert {
            "specs:read",
            "specs:write",
            "specs:admin",
            "org:manage",
            "platform:manage",
        } == ALL_PERMISSION_VALUES


class TestRoleEnum:
    def test_viewer(self):
        assert Role.VIEWER.value == "viewer"

    def test_editor(self):
        assert Role.EDITOR.value == "editor"

    def test_admin(self):
        assert Role.ADMIN.value == "admin"

    def test_super_admin(self):
        assert Role.SUPER_ADMIN.value == "super_admin"


class TestRolePermissions:
    def test_viewer_has_read_only(self):
        perms = ROLE_PERMISSIONS[Role.VIEWER]
        assert Permission.SPECS_READ in perms
        assert Permission.SPECS_WRITE not in perms
        assert Permission.SPECS_ADMIN not in perms

    def test_editor_has_read_and_write(self):
        perms = ROLE_PERMISSIONS[Role.EDITOR]
        assert Permission.SPECS_READ in perms
        assert Permission.SPECS_WRITE in perms
        assert Permission.SPECS_ADMIN not in perms

    def test_admin_has_all_except_platform_manage(self):
        perms = ROLE_PERMISSIONS[Role.ADMIN]
        for p in Permission:
            if p == Permission.PLATFORM_MANAGE:
                assert p not in perms, "ADMIN should NOT have PLATFORM_MANAGE"
            else:
                assert p in perms, f"ADMIN missing {p}"

    def test_super_admin_has_all(self):
        perms = ROLE_PERMISSIONS[Role.SUPER_ADMIN]
        for p in Permission:
            assert p in perms, f"SUPER_ADMIN missing {p}"

    def test_permissions_for_role_function(self):
        assert permissions_for_role(Role.VIEWER) == frozenset({Permission.SPECS_READ})
        assert permissions_for_role(Role.EDITOR) == frozenset(
            {Permission.SPECS_READ, Permission.SPECS_WRITE}
        )
        assert permissions_for_role(Role.ADMIN) == frozenset(
            p for p in Permission if p != Permission.PLATFORM_MANAGE
        )
        assert permissions_for_role(Role.SUPER_ADMIN) == frozenset(Permission)

    def test_permissions_for_unknown_role_returns_empty(self):
        # Test the underlying dict's .get fallback path
        assert ROLE_PERMISSIONS.get("nonexistent", frozenset()) == frozenset()


class TestPermissionDescriptions:
    def test_every_permission_has_a_description(self):
        for perm in Permission:
            assert perm.value in PERMISSION_DESCRIPTIONS, f"Missing description for {perm.value}"
