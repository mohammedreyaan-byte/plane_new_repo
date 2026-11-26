# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""CRUD endpoints for reusable work item templates."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import allow_permission, ROLE
from plane.app.serializers import WorkItemTemplateSerializer
from plane.db.models import Issue, Workspace, WorkspaceMember, WorkItemTemplate

from .base import BaseAPIView


def visible_templates(queryset, request, slug):
    """Private templates are visible to their author and workspace admins only."""
    is_admin = WorkspaceMember.objects.filter(
        workspace__slug=slug, member=request.user, role=ROLE.ADMIN.value, is_active=True
    ).exists()
    if is_admin:
        return queryset
    return queryset.filter(Q(is_public=True) | Q(created_by=request.user))


class WorkspaceWorkItemTemplateOptionsEndpoint(BaseAPIView):
    """Workspace-level options for template fields that are not project-scoped."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        members = WorkspaceMember.objects.filter(workspace__slug=slug, is_active=True).values(
            "member_id", "member__display_name", "member__email"
        )
        return Response(
            {
                "states": [],
                "labels": [],
                "types": [],
                "modules": [],
                "cycles": [],
                "members": [
                    {
                        "id": str(item["member_id"]),
                        "display_name": item["member__display_name"] or item["member__email"],
                    }
                    for item in members
                ],
                "priorities": [
                    {"value": value, "label": label}
                    for value, label in Issue.PRIORITY_CHOICES
                    if value != "none"
                ],
            }
        )


class WorkspaceWorkItemTemplateEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        queryset = WorkItemTemplate.objects.filter(workspace__slug=slug, project__isnull=True)
        queryset = visible_templates(queryset, request, slug)
        return Response(WorkItemTemplateSerializer(queryset, many=True).data)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def post(self, request, slug):
        serializer = WorkItemTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(workspace=Workspace.objects.get(slug=slug))
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WorkspaceWorkItemTemplateDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug, pk):
        queryset = visible_templates(WorkItemTemplate.objects.filter(workspace__slug=slug, project__isnull=True), request, slug)
        template = get_object_or_404(queryset, pk=pk)
        return Response(WorkItemTemplateSerializer(template).data)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def patch(self, request, slug, pk):
        queryset = visible_templates(WorkItemTemplate.objects.filter(workspace__slug=slug, project__isnull=True), request, slug)
        template = get_object_or_404(queryset, pk=pk)
        serializer = WorkItemTemplateSerializer(template, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def delete(self, request, slug, pk):
        queryset = visible_templates(WorkItemTemplate.objects.filter(workspace__slug=slug, project__isnull=True), request, slug)
        template = get_object_or_404(queryset, pk=pk)
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectWorkItemTemplateEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id):
        queryset = WorkItemTemplate.objects.filter(workspace__slug=slug, project_id=project_id)
        queryset = visible_templates(queryset, request, slug)
        return Response(WorkItemTemplateSerializer(queryset, many=True).data)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="PROJECT")
    def post(self, request, slug, project_id):
        serializer = WorkItemTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(project_id=project_id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ProjectWorkItemTemplateDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id, pk):
        queryset = visible_templates(WorkItemTemplate.objects.filter(workspace__slug=slug, project_id=project_id), request, slug)
        template = get_object_or_404(queryset, pk=pk)
        return Response(WorkItemTemplateSerializer(template).data)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="PROJECT")
    def patch(self, request, slug, project_id, pk):
        queryset = visible_templates(WorkItemTemplate.objects.filter(workspace__slug=slug, project_id=project_id), request, slug)
        template = get_object_or_404(queryset, pk=pk)
        serializer = WorkItemTemplateSerializer(template, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="PROJECT")
    def delete(self, request, slug, project_id, pk):
        queryset = visible_templates(WorkItemTemplate.objects.filter(workspace__slug=slug, project_id=project_id), request, slug)
        template = get_object_or_404(queryset, pk=pk)
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
