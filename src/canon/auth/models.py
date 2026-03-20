"""CurrentUser model — unified identity across session, JWT, and API key auth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .permissions import Permission

AuthMethod = Literal["session", "jwt", "api_key", "anonymous"]


class PermissionDenied(Exception):
    """Raised when a user lacks a required permission.

    Framework-agnostic — translated to HTTP 403 by the auth dependency layer.
    """

    def __init__(self, perm: Permission) -> None:
        self.permission = perm
        super().__init__(f"Missing required permission: {perm.value}")


@dataclass(frozen=True)
class CurrentUser:
    """Resolved identity for the current request.

    Built by ``get_current_user`` from whichever auth source is present
    (session cookie, JWT access token, or API key).
    """

    sub: str = ""
    email: str = ""
    name: str = ""
    picture: str = ""
    org_id: str = ""
    org_login: str = ""
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    auth_method: AuthMethod = "anonymous"

    def has_permission(self, perm: Permission) -> bool:
        """Check whether this user has a specific permission."""
        return perm in self.permissions

    def require_permission(self, perm: Permission) -> None:
        """Raise :class:`PermissionDenied` if the user lacks the given permission."""
        if perm not in self.permissions:
            raise PermissionDenied(perm)

    @property
    def is_anonymous(self) -> bool:
        return self.auth_method == "anonymous"


#: Anonymous user with all permissions (used in dev mode / auth disabled).
ANONYMOUS_USER = CurrentUser(
    sub="anonymous",
    email="",
    name="Anonymous",
    permissions=frozenset(Permission),
    auth_method="anonymous",
)
