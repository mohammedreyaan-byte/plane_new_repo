# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from plane.db.models import PageComment
from plane.utils.content_validator import validate_html_content

from .base import BaseSerializer
from .user import UserLiteSerializer


class PageCommentSerializer(BaseSerializer):
    """Serializer for page comments.

    ``comment_html``/``comment_stripped`` follow the naming used by work item
    comments, while ``content``/``content_stripped`` are read-only aliases for
    clients that prefer a neutral field name.
    """

    actor_detail = UserLiteSerializer(read_only=True, source="actor")
    content = serializers.CharField(source="comment_html", read_only=True)
    content_stripped = serializers.CharField(source="comment_stripped", read_only=True)
    comment_stripped = serializers.CharField(read_only=True)
    is_own = serializers.SerializerMethodField()
    reply_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = PageComment
        fields = [
            "id",
            "page",
            "workspace",
            "project",
            "actor",
            "actor_detail",
            "parent",
            "comment_html",
            "comment_stripped",
            "content",
            "content_stripped",
            "reply_count",
            "is_own",
            "edited_at",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        read_only_fields = [
            "page",
            "workspace",
            "project",
            "actor",
            "edited_at",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]

    def get_is_own(self, obj):
        request = self.context.get("request")
        return bool(request and request.user.is_authenticated and obj.actor_id == request.user.id)

    def validate(self, attrs):
        comment_html = attrs.get("comment_html")
        if not comment_html:
            raise serializers.ValidationError({"comment_html": "Comment content is required"})

        is_valid, error_message, sanitized_html = validate_html_content(comment_html)
        if not is_valid:
            raise serializers.ValidationError({"comment_html": error_message or "HTML content is not valid"})
        if sanitized_html is not None:
            attrs["comment_html"] = sanitized_html

        parent = attrs.get("parent")
        page_id = self.context.get("page_id")
        if parent is not None:
            if parent.page_id != page_id:
                raise serializers.ValidationError({"parent": "Parent comment belongs to another page"})
            if parent.deleted_at is not None:
                raise serializers.ValidationError({"parent": "Parent comment has been deleted"})
        return attrs
