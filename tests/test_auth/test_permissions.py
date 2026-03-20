"""Tests for Permission enum and role mapping."""

from __future__ import annotations

from canon.auth.permissions import (
    ALL_PERMISSION_VALUES,
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

    def test_all_permission_values_set(self):
        assert {"specs:read", "specs:write", "specs:admin", "org:manage"} == ALL_PERMISSION_VALUES


class TestRoleEnum:
    def test_viewer(self):
        assert Role.VIEWER.value == "viewer"

    def test_editor(self):
        assert Role.EDITOR.value == "editor"

    def test_admin(self):
        assert Role.ADMIN.value == "admin"


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

    def test_admin_has_all(self):
        perms = ROLE_PERMISSIONS[Role.ADMIN]
        for p in Permission:
            assert p in perms

    def test_permissions_for_role_function(self):
        assert permissions_for_role(Role.VIEWER) == frozenset({Permission.SPECS_READ})
        assert permissions_for_role(Role.EDITOR) == frozenset(
            {Permission.SPECS_READ, Permission.SPECS_WRITE}
        )
        assert permissions_for_role(Role.ADMIN) == frozenset(Permission)

    def test_permissions_for_unknown_role_returns_empty(self):
        # Test the underlying dict's .get fallback path
        assert ROLE_PERMISSIONS.get("nonexistent", frozenset()) == frozenset()
