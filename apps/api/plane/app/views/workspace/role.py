# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import WorkspaceEntityPermission
from plane.app.serializers import RoleSerializer
from plane.app.views.base import BaseAPIView
from plane.db.models import Role


class WorkspaceRolesEndpoint(BaseAPIView):
    """List the roles available in a workspace.

    System roles are shared by every workspace. Workspace scoped roles are
    merged in and win when the key collides, which lets a workspace override a
    system role later without changing the API.
    """

    permission_classes = [WorkspaceEntityPermission]
    use_read_replica = True

    def get(self, request, slug):
        roles = (
            Role.objects.filter(is_active=True)
            .filter(Q(workspace__slug=slug) | Q(workspace__isnull=True))
            .select_related("workspace")
            .order_by("-level", "name")
        )

        merged = {}
        for role in roles:
            # Workspace roles are listed after system roles, so they override.
            if role.key not in merged or role.workspace_id is not None:
                merged[role.key] = role

        serializer = RoleSerializer(merged.values(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WorkspaceRoleDetailEndpoint(BaseAPIView):
    permission_classes = [WorkspaceEntityPermission]

    def get(self, request, slug, role_key):
        role = (
            Role.objects.filter(is_active=True, key=role_key)
            .filter(Q(workspace__slug=slug) | Q(workspace__isnull=True))
            .order_by("-workspace_id")
            .first()
        )
        if role is None:
            return Response({"error": "Role not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RoleSerializer(role).data, status=status.HTTP_200_OK)


__all__ = [
    "WorkspaceRolesEndpoint",
    "WorkspaceRoleDetailEndpoint",
]
