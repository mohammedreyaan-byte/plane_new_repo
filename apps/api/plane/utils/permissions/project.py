# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third Party imports
from rest_framework.permissions import SAFE_METHODS, BasePermission

# Module import
from plane.db.models.project import ROLE
from plane.utils.role_compat import expand_roles


class ProjectBasePermission(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_anonymous:
            return False

        # Imported here because this package imports the app permissions at
        # module load time; a top-level import creates an import cycle.
        from plane.utils.permissions import project_scope

        slug = view.workspace_slug
        project_id = view.project_id

        # Safe methods are filtered by the view's queryset.
        if request.method in SAFE_METHODS:
            return project_scope.active_workspace_membership(request.user, slug)

        # Only workspace owners or admins can create projects.
        if request.method == "POST":
            return project_scope.active_workspace_membership(
                request.user, slug, roles=expand_roles([ROLE.ADMIN.value, ROLE.MEMBER.value])
            )

        if project_scope.active_project_membership(
            request.user, project_id=project_id, workspace_slug=slug, roles=[ROLE.ADMIN.value]
        ):
            return True

        if project_scope.active_project_membership(
            request.user, project_id=project_id, workspace_slug=slug
        ) and project_scope.active_workspace_membership(request.user, slug, roles=[ROLE.ADMIN.value]):
            project_scope.log_project_admin_override(request.user, project_id=project_id, slug=slug, request=request)
            return True
        return False


class ProjectMemberPermission(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_anonymous:
            return False

        # Imported here because this package imports the app permissions at
        # module load time; a top-level import creates an import cycle.
        from plane.utils.permissions import project_scope

        slug = view.workspace_slug
        project_id = view.project_id

        if request.method in SAFE_METHODS:
            return project_scope.active_project_membership(request.user, project_id=project_id, workspace_slug=slug)

        if request.method == "POST":
            return project_scope.active_workspace_membership(
                request.user, slug, roles=expand_roles([ROLE.ADMIN.value, ROLE.MEMBER.value])
            )

        return project_scope.active_project_membership(
            request.user,
            project_id=project_id,
            workspace_slug=slug,
            roles=expand_roles([ROLE.ADMIN.value, ROLE.MEMBER.value]),
        )


class ProjectEntityPermission(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_anonymous:
            return False

        # Imported here because this package imports the app permissions at
        # module load time; a top-level import creates an import cycle.
        from plane.utils.permissions import project_scope

        slug = view.workspace_slug
        project_identifier = getattr(view, "project_identifier", None)

        if project_identifier and request.method in SAFE_METHODS:
            return project_scope.active_project_membership(
                request.user, workspace_slug=slug, project_identifier=project_identifier
            )

        if request.method in SAFE_METHODS:
            return project_scope.active_project_membership(
                request.user, project_id=view.project_id, workspace_slug=slug
            )

        return project_scope.active_project_membership(
            request.user,
            project_id=view.project_id,
            workspace_slug=slug,
            roles=expand_roles([ROLE.ADMIN.value, ROLE.MEMBER.value]),
        )


class ProjectAdminPermission(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_anonymous:
            return False

        # Imported here because this package imports the app permissions at
        # module load time; a top-level import creates an import cycle.
        from plane.utils.permissions import project_scope

        return project_scope.active_project_membership(
            request.user,
            project_id=view.project_id,
            workspace_slug=view.workspace_slug,
            roles=[ROLE.ADMIN.value],
        )


class ProjectLitePermission(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_anonymous:
            return False

        # Imported here because this package imports the app permissions at
        # module load time; a top-level import creates an import cycle.
        from plane.utils.permissions import project_scope

        return project_scope.active_project_membership(
            request.user, project_id=view.project_id, workspace_slug=view.workspace_slug
        )
