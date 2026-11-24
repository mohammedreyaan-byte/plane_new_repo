# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import Count, Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Issue, Module


class EpicModulesEndpoint(BaseAPIView):
    """Modules that deliver an epic, with how far each one is."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        epic = (
            Issue.objects.filter(pk=issue_id, project_id=project_id, workspace__slug=slug)
            .select_related("type")
            .first()
        )
        if epic is None:
            return Response({"error": "Epic not found"}, status=status.HTTP_404_NOT_FOUND)
        if epic.type is None or not epic.type.is_epic:
            return Response({"error": "This work item is not an epic."}, status=status.HTTP_400_BAD_REQUEST)

        live = Q(issue_module__deleted_at__isnull=True, issue_module__issue__deleted_at__isnull=True)
        modules = (
            Module.objects.filter(epic_id=issue_id, project_id=project_id, archived_at__isnull=True)
            .annotate(
                total_issues=Count("issue_module__issue", filter=live, distinct=True),
                completed_issues=Count(
                    "issue_module__issue",
                    filter=live & Q(issue_module__issue__state__group="completed"),
                    distinct=True,
                ),
            )
            .order_by("sort_order", "name")
            .values("id", "name", "status", "start_date", "target_date", "total_issues", "completed_issues")
        )
        rows = list(modules)
        total = sum(row["total_issues"] for row in rows)
        completed = sum(row["completed_issues"] for row in rows)
        return Response(
            {
                "epic_id": epic.id,
                "modules": rows,
                "total_issues": total,
                "completed_issues": completed,
                "progress": round(completed * 100 / total) if total else 0,
            },
            status=status.HTTP_200_OK,
        )
