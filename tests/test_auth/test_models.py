"""Tests for CurrentUser model."""

from __future__ import annotations

import pytest

from canon.auth.models import ANONYMOUS_USER, CurrentUser, PermissionDenied
from canon.auth.permissions import Permission


class TestCurrentUser:
    def test_has_permission_true(self):
        user = CurrentUser(
            sub="u1",
            permissions=frozenset({Permission.SPECS_READ, Permission.SPECS_WRITE}),
        )
        assert user.has_permission(Permission.SPECS_READ) is True
        assert user.has_permission(Permission.SPECS_WRITE) is True

    def test_has_permission_false(self):
        user = CurrentUser(
            sub="u1",
            permissions=frozenset({Permission.SPECS_READ}),
        )
        assert user.has_permission(Permission.SPECS_ADMIN) is False

    def test_require_permission_passes(self):
        user = CurrentUser(
            sub="u1",
            permissions=frozenset({Permission.SPECS_ADMIN}),
        )
        # Should not raise
        user.require_permission(Permission.SPECS_ADMIN)

    def test_require_permission_raises_permission_denied(self):
        user = CurrentUser(
            sub="u1",
            permissions=frozenset({Permission.SPECS_READ}),
        )
        with pytest.raises(PermissionDenied) as exc_info:
            user.require_permission(Permission.SPECS_ADMIN)
        assert exc_info.value.permission == Permission.SPECS_ADMIN
        assert "specs:admin" in str(exc_info.value)

    def test_is_anonymous(self):
        user = CurrentUser(auth_method="anonymous")
        assert user.is_anonymous is True

    def test_is_not_anonymous(self):
        user = CurrentUser(auth_method="session", sub="u1")
        assert user.is_anonymous is False

    def test_frozen(self):
        user = CurrentUser(sub="u1")
        with pytest.raises(AttributeError):
            user.sub = "u2"  # type: ignore[misc]


class TestAnonymousUser:
    def test_has_all_permissions(self):
        for p in Permission:
            assert ANONYMOUS_USER.has_permission(p) is True

    def test_is_anonymous(self):
        assert ANONYMOUS_USER.is_anonymous is True

    def test_auth_method(self):
        assert ANONYMOUS_USER.auth_method == "anonymous"


class TestSuperAdminRole:
    def test_super_admin_has_all_permissions(self):
        from canon.auth.permissions import Permission, Role, permissions_for_role

        perms = permissions_for_role(Role.SUPER_ADMIN)
        for p in Permission:
            assert p in perms, f"SUPER_ADMIN missing {p}"

    def test_super_admin_has_platform_manage(self):
        from canon.auth.permissions import Permission, Role, permissions_for_role

        perms = permissions_for_role(Role.SUPER_ADMIN)
        assert Permission.PLATFORM_MANAGE in perms

    def test_admin_does_not_have_platform_manage(self):
        from canon.auth.permissions import Permission, Role, permissions_for_role

        perms = permissions_for_role(Role.ADMIN)
        assert Permission.PLATFORM_MANAGE not in perms

    def test_role_hierarchy_order(self):
        from canon.auth.permissions import Role

        roles = list(Role)
        assert roles.index(Role.VIEWER) < roles.index(Role.EDITOR)
        assert roles.index(Role.EDITOR) < roles.index(Role.ADMIN)
        assert roles.index(Role.ADMIN) < roles.index(Role.SUPER_ADMIN)
