# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import IssueCreateSerializer
from plane.app.views.base import BaseAPIView
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue
from plane.utils.host import base_host
from plane.utils.workflow.transition import WorkflowError

BULK_LIMIT = 100

# Properties a bulk update may set. Cycle and module moves have their own endpoints.
BULK_PROPERTIES = (
    "state_id",
    "type_id",
    "priority",
    "start_date",
    "target_date",
    "assignee_ids",
    "label_ids",
    "estimate_point",
)


def _failure(issue_id, code, message):
    return {"issue_id": str(issue_id), "code": code, "message": message}


class BulkOperationIssuesEndpoint(BaseAPIView):
    """Update several work items at once.

    Every item goes through the same rules as a single update (types, hierarchy and workflow transitions),
    so a bulk move can never do what a single move would refuse. One item failing does not stop the others:
    the response lists what was updated and what failed, with the reason for each.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id):
        issue_ids = request.data.get("issue_ids") or []
        properties = request.data.get("properties") or {}

        if not isinstance(issue_ids, list) or not issue_ids:
            return Response({"error": "issue_ids is required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(issue_ids) > BULK_LIMIT:
            return Response(
                {"error": f"At most {BULK_LIMIT} work items can be updated at once."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        unsupported = [key for key in properties if key not in BULK_PROPERTIES]
        if not properties or unsupported:
            return Response(
                {"error": "Unsupported properties.", "unsupported": unsupported, "supported": list(BULK_PROPERTIES)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        issues = {
            str(issue.id): issue
            for issue in Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk__in=issue_ids)
        }
        updated, failed = [], []

        for issue_id in issue_ids:
            issue = issues.get(str(issue_id))
            if issue is None:
                failed.append(_failure(issue_id, "not_found", "Work item not found."))
                continue

            current_instance = json.dumps(
                {
                    "state_id": str(issue.state_id) if issue.state_id else None,
                    "type_id": str(issue.type_id) if issue.type_id else None,
                    "priority": issue.priority,
                },
                cls=DjangoJSONEncoder,
            )
            try:
                with transaction.atomic():
                    serializer = IssueCreateSerializer(
                        issue, data=dict(properties), partial=True, context={"project_id": project_id}
                    )
                    serializer.is_valid(raise_exception=True)
                    serializer.save()
            except WorkflowError as error:
                failed.append(_failure(issue_id, error.code, error.message))
                continue
            except ValidationError as error:
                failed.append(_failure(issue_id, "invalid", json.dumps(error.detail, default=str)))
                continue

            updated.append(str(issue_id))
            issue_activity.delay(
                type="issue.activity.updated",
                requested_data=json.dumps(properties, cls=DjangoJSONEncoder),
                actor_id=str(request.user.id),
                issue_id=str(issue_id),
                project_id=str(project_id),
                current_instance=current_instance,
                epoch=int(timezone.now().timestamp()),
                notification=True,
                origin=base_host(request=request, is_app=True),
            )

        # 207 would hide partial failure from simple clients; the body says what happened.
        return Response({"updated": updated, "failed": failed}, status=status.HTTP_200_OK)
