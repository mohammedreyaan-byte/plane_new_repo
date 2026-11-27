# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Module imports
from rest_framework import serializers

from .base import BaseSerializer
from plane.db.models import ExporterHistory
from plane.utils.permissions.project_scope import active_project_membership
from .user import UserLiteSerializer


class ExporterHistorySerializer(BaseSerializer):
    initiated_by_detail = UserLiteSerializer(source="initiated_by", read_only=True)
    url = serializers.SerializerMethodField()

    def get_url(self, obj: ExporterHistory):
        """Re-check project membership before exposing a download URL."""
        request = self.context.get("request")
        if not request or obj.initiated_by_id != request.user.id:
            return None
        slug = obj.workspace.slug if obj.workspace_id else None
        for project_id in obj.project or []:
            if not active_project_membership(request.user, project_id=project_id, workspace_slug=slug):
                return None
        return obj.url

    class Meta:
        model = ExporterHistory
        fields = [
            "id",
            "created_at",
            "updated_at",
            "project",
            "provider",
            "status",
            "url",
            "initiated_by",
            "initiated_by_detail",
            "token",
            "created_by",
            "updated_by",
        ]
        read_only_fields = fields
