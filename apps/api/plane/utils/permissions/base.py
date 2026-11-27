# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from plane.db.models import WorkspaceMember, ProjectMember
from functools import wraps
from rest_framework.response import Response
from rest_framework import status

from enum import Enum

from rest_framework.permissions import SAFE_METHODS

from plane.utils.role_compat import expand_roles


class ROLE(Enum):
    ADMIN = 20
    MEMBER = 15
    GUEST = 5


def _has_required_capability(request, kwargs, capability, level):
    """True when no capability is required, or the user holds it."""
    if not capability:
        return True
    # Imported here to avoid an import cycle with plane.db.models at import time.
    from plane.utils.permissions.capabilities import has_capability_for_slug

    return has_capability_for_slug(
        request.user,
        kwargs["slug"],
        capability,
        project_id=None if level == "WORKSPACE" else kwargs.get("project_id"),
    )


def allow_permission(allowed_roles, level="PROJECT", creator=False, model=None, capability=None):
    """Role based guard for function views.

    ``allowed_roles`` uses the legacy integers. Developer and QA are accepted wherever Member is,
    and Viewer wherever Guest is on read-only requests (see plane.utils.role_compat).
    When ``capability`` is set the user must also hold that capability (for example
    ``cycle.manage``), which is how Developer/QA are kept out of Member-only actions.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(instance, request, *args, **kwargs):
            # Imported here because this package imports the app permissions
            # at module load time; a top-level import creates an import cycle.
            from plane.utils.permissions import project_scope

            # Check for creator if required
            if creator and model:
                if kwargs.get("project_id") and not project_scope.active_project_membership(
                    request.user, project_id=kwargs["project_id"], workspace_slug=kwargs.get("slug")
                ):
                    return Response(
                        {"error": "You don't have the required permissions."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                obj = model.objects.filter(id=kwargs["pk"], created_by=request.user).exists()
                if obj:
                    return view_func(instance, request, *args, **kwargs)

            # Convert allowed_roles to their values if they are enum members
            allowed_role_values = expand_roles(
                [role.value if isinstance(role, ROLE) else role for role in allowed_roles],
                safe=request.method in SAFE_METHODS,
            )

            # Check role permissions
            if level == "WORKSPACE":
                if WorkspaceMember.objects.filter(
                    member=request.user,
                    workspace__slug=kwargs["slug"],
                    role__in=allowed_role_values,
                    is_active=True,
                ).exists():
                    if _has_required_capability(request, kwargs, capability, level):
                        return view_func(instance, request, *args, **kwargs)
            else:
                is_user_has_allowed_role = ProjectMember.objects.filter(
                    member=request.user,
                    workspace__slug=kwargs["slug"],
                    project_id=kwargs["project_id"],
                    role__in=allowed_role_values,
                    is_active=True,
                ).exists()

                # Return if the user has the allowed role else if they are workspace admin and part of the project regardless of the role # noqa: E501
                if is_user_has_allowed_role:
                    if _has_required_capability(request, kwargs, capability, level):
                        return view_func(instance, request, *args, **kwargs)
                elif (
                    ProjectMember.objects.filter(
                        member=request.user,
                        workspace__slug=kwargs["slug"],
                        project_id=kwargs["project_id"],
                        is_active=True,
                    ).exists()
                    and WorkspaceMember.objects.filter(
                        member=request.user,
                        workspace__slug=kwargs["slug"],
                        role=ROLE.ADMIN.value,
                        is_active=True,
                    ).exists()
                ):
                    project_scope.log_project_admin_override(
                        request.user,
                        project_id=kwargs.get("project_id"),
                        slug=kwargs.get("slug"),
                        request=request,
                    )
                    return view_func(instance, request, *args, **kwargs)

            # Return permission denied if no conditions are met
            return Response(
                {"error": "You don't have the required permissions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return _wrapped_view

    return decorator
