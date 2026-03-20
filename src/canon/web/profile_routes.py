"""Profile API route for the Spec Explorer web app."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import ALL_PERMISSION_VALUES, ROLE_PERMISSIONS, Permission, Role
from .models import ProfileGitHubUser, ProfileResponse

logger = logging.getLogger(__name__)

profile_router = APIRouter()


def _infer_role(permissions: frozenset[Permission]) -> str:
    """Infer the highest role whose permissions are a subset of the user's."""
    # Check from highest to lowest
    for role in (Role.ADMIN, Role.EDITOR, Role.VIEWER):
        if ROLE_PERMISSIONS[role] <= permissions:
            return role.value
    return "viewer"


@profile_router.get("/app/{org}/api/profile", response_model=ProfileResponse)
async def api_profile(
    request: Request,
    org: str,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> ProfileResponse:
    """Return the current user's profile information."""
    # Fetch last_login_at from user store if available
    last_login_at: str | None = None
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is not None and user.sub:
        try:
            db_user = await user_store.get_user_by_sub(user.sub)
            if db_user and db_user.get("last_login_at"):
                last_login_at = db_user["last_login_at"].isoformat()
        except Exception:
            logger.warning("Failed to fetch user from store", exc_info=True)

    # Get GitHub user from session
    github_user: ProfileGitHubUser | None = None
    if hasattr(request, "session"):
        gh = request.session.get("github_user")
        if gh:
            github_user = ProfileGitHubUser(
                login=gh.get("login", ""),
                name=gh.get("name", ""),
            )

    return ProfileResponse(
        sub=user.sub,
        email=user.email,
        name=user.name,
        picture=user.picture,
        org_login=user.org_login,
        permissions=sorted(p.value for p in user.permissions),
        all_permissions=sorted(ALL_PERMISSION_VALUES),
        auth_method=user.auth_method,
        github_user=github_user,
        last_login_at=last_login_at,
        inferred_role=_infer_role(user.permissions),
    )
