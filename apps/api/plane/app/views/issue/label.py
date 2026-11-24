# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging
import random

# Django imports
from django.db import IntegrityError, transaction

# Third Party imports
from rest_framework.response import Response
from rest_framework import status

# Module imports
from .. import BaseViewSet, BaseAPIView
from plane.app.serializers import LabelSerializer
from plane.app.permissions import allow_permission, ProjectBasePermission, ROLE
from plane.db.models import IssueLabel, Project, Label
from plane.utils.cache import invalidate_cache
from plane.utils.labels import label_issue_count, merge_labels

logger = logging.getLogger("plane.labels")


class LabelViewSet(BaseViewSet):
    serializer_class = LabelSerializer
    model = Label
    permission_classes = [ProjectBasePermission]

    def get_queryset(self):
        return self.filter_queryset(
            super()
            .get_queryset()
            .filter(workspace__slug=self.kwargs.get("slug"))
            .filter(project_id=self.kwargs.get("project_id"))
            .filter(project__project_projectmember__member=self.request.user)
            .select_related("project")
            .select_related("workspace")
            .select_related("parent")
            .distinct()
            .order_by("sort_order")
        )

    @invalidate_cache(path="/api/workspaces/:slug/labels/", url_params=True, user=False, multiple=True)
    @allow_permission([ROLE.ADMIN])
    def create(self, request, slug, project_id):
        try:
            serializer = LabelSerializer(data=request.data, context={"project_id": project_id})
            if serializer.is_valid():
                serializer.save(project_id=project_id)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response(
                {"error": "Label with the same name already exists in the project"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @invalidate_cache(path="/api/workspaces/:slug/labels/", url_params=True, user=False)
    @allow_permission([ROLE.ADMIN])
    def partial_update(self, request, *args, **kwargs):
        # Check if the label name is unique within the project
        if (
            "name" in request.data
            and Label.objects.filter(project_id=kwargs["project_id"], name=request.data["name"])
            .exclude(pk=kwargs["pk"])
            .exists()
        ):
            return Response(
                {"error": "Label with the same name already exists in the project"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = LabelSerializer(
            instance=self.get_object(),
            data=request.data,
            context={"project_id": kwargs["project_id"]},
            partial=True,
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @invalidate_cache(path="/api/workspaces/:slug/labels/", url_params=True, user=False)
    @allow_permission([ROLE.ADMIN])
    def destroy(self, request, *args, **kwargs):
        label = self.get_object()
        usage_count = label_issue_count(label)
        force = str(request.query_params.get("force", "false")).lower() == "true"
        comment = (request.data.get("comment") or request.query_params.get("comment") or "").strip()
        if usage_count and not force:
            return Response(
                {
                    "error": {
                        "code": "label_in_use",
                        "message": "This label is used by work items. Pass force=true to remove those links.",
                        "details": {"issue_count": usage_count},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )
        if usage_count and force and not comment:
            return Response(
                {
                    "error": {
                        "code": "comment_required",
                        "message": "A comment is required when force deleting a label in use.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            if usage_count:
                IssueLabel.objects.filter(label=label, deleted_at__isnull=True).delete()
                logger.info(
                    "label force delete slug=%s project=%s label=%s removed_links=%s comment=%s",
                    kwargs.get("slug"),
                    kwargs.get("project_id"),
                    label.id,
                    usage_count,
                    comment,
                )
            label.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LabelMergeEndpoint(BaseAPIView):
    """Admin-only duplicate resolution with a preview/apply contract."""

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        target_id = request.data.get("target_id")
        source_ids = request.data.get("source_ids") or []
        if not target_id or not isinstance(source_ids, list) or len(source_ids) < 1:
            return Response(
                {"error": "target_id and at least one source_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dry_run = str(request.data.get("preview", request.query_params.get("preview", True))).lower() != "false"
        try:
            result = merge_labels(
                workspace_slug=slug,
                target_id=target_id,
                source_ids=source_ids,
                actor=request.user,
                dry_run=dry_run,
            )
        except ValueError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)


class BulkCreateIssueLabelsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        label_data = request.data.get("label_data", [])

        project = Project.objects.get(pk=project_id)

        labels = Label.objects.bulk_create(
            [
                Label(
                    name=label.get("name", "Migrated"),
                    description=label.get("description", "Migrated Issue"),
                    color=f"#{random.randint(0, 0xFFFFFF + 1):06X}",
                    project_id=project_id,
                    workspace_id=project.workspace_id,
                    created_by=request.user,
                    updated_by=request.user,
                )
                for label in label_data
            ],
            batch_size=50,
            ignore_conflicts=True,
        )

        return Response(
            {"labels": LabelSerializer(labels, many=True).data},
            status=status.HTTP_201_CREATED,
        )
