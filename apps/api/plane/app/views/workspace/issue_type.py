# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party modules
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import WorkspaceViewerPermission
from plane.app.views.base import BaseAPIView
from plane.db.models import Workspace
from plane.utils.default_issue_types import ensure_default_issue_types


class WorkspaceIssueTypesEndpoint(BaseAPIView):
    """List the workspace's issue types (Epic, Story, Task, Bug, Sub-task).

    Default types are created on first request, so existing workspaces need no migration.
    """

    permission_classes = [WorkspaceViewerPermission]

    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        issue_types = ensure_default_issue_types(workspace).order_by("-level", "name")
        data = [
            {
                "id": issue_type.id,
                "name": issue_type.name,
                "description": issue_type.description,
                "logo_props": issue_type.logo_props,
                "is_epic": issue_type.is_epic,
                "is_default": issue_type.is_default,
                "level": issue_type.level,
            }
            for issue_type in issue_types
        ]
        return Response(data, status=status.HTTP_200_OK)
