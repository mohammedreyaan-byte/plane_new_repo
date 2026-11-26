# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import Count, Q
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, ProjectPageCommentPermission
from plane.app.serializers import PageCommentSerializer
from plane.bgtasks.page_comment_task import notify_page_comment
from plane.db.models import Page, PageComment, ProjectMember
from plane.utils.paginator import BasePaginator

# Local imports
from ..base import BaseViewSet


class PageCommentViewSet(BaseViewSet, BasePaginator):
    """Page scoped comment endpoints."""

    model = PageComment
    serializer_class = PageCommentSerializer
    permission_classes = [ProjectPageCommentPermission]
    search_fields = ["comment_stripped"]

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(
                workspace__slug=self.kwargs.get("slug"),
                project_id=self.kwargs.get("project_id"),
                page_id=self.kwargs.get("page_id"),
                deleted_at__isnull=True,
            )
            .annotate(reply_count=Count("replies", filter=Q(replies__deleted_at__isnull=True), distinct=True))
            .select_related("actor", "workspace", "project", "page")
            .order_by("-created_at")
        )

    def get_page(self):
        return Page.objects.filter(
            pk=self.kwargs.get("page_id"),
            workspace__slug=self.kwargs.get("slug"),
            projects__id=self.kwargs.get("project_id"),
            project_pages__deleted_at__isnull=True,
        ).first()

    def list(self, request, slug, project_id, page_id):
        if self.get_page() is None:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)

        queryset = self.filter_queryset(self.get_queryset())
        return self.paginate(
            request=request,
            queryset=queryset,
            order_by="-created_at",
            on_results=lambda comments: PageCommentSerializer(comments, many=True, context={"request": request}).data,
            default_per_page=20,
            max_per_page=100,
        )

    def retrieve(self, request, slug, project_id, page_id, pk=None):
        comment = self.get_queryset().filter(pk=pk).first()
        if comment is None:
            return Response({"error": "Comment not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = PageCommentSerializer(comment, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request, slug, project_id, page_id):
        page = self.get_page()
        if page is None:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = PageCommentSerializer(
            data=request.data,
            context={
                "request": request,
                "page_id": page.id,
                "project_id": project_id,
                "workspace_id": page.workspace_id,
            },
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        comment = serializer.save(
            page=page,
            project_id=project_id,
            workspace_id=page.workspace_id,
            actor=request.user,
            created_by=request.user,
            updated_by=request.user,
        )

        # Notifications are best effort: a broken broker must not fail the API call.
        try:
            notify_page_comment.delay(comment_id=str(comment.id))
        except Exception:
            pass

        serializer = PageCommentSerializer(comment, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, slug, project_id, page_id, pk=None):
        comment = self.get_queryset().filter(pk=pk).first()
        if comment is None:
            return Response({"error": "Comment not found"}, status=status.HTTP_404_NOT_FOUND)

        if comment.actor_id != request.user.id:
            return Response({"error": "You can only edit your own comments"}, status=status.HTTP_403_FORBIDDEN)

        serializer = PageCommentSerializer(
            comment,
            data=request.data,
            partial=True,
            context={
                "request": request,
                "page_id": comment.page_id,
                "project_id": project_id,
                "workspace_id": comment.workspace_id,
            },
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save(edited_at=timezone.now())
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, slug, project_id, page_id, pk=None):
        comment = self.get_queryset().filter(pk=pk).first()
        if comment is None:
            return Response({"error": "Comment not found"}, status=status.HTTP_404_NOT_FOUND)

        is_admin = ProjectMember.objects.filter(
            project_id=project_id,
            member=request.user,
            is_active=True,
            role=ROLE.ADMIN.value,
        ).exists()
        if comment.actor_id != request.user.id and not is_admin:
            return Response({"error": "You can only delete your own comments"}, status=status.HTTP_403_FORBIDDEN)

        PageComment.objects.filter(pk=comment.pk).update(deleted_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)
