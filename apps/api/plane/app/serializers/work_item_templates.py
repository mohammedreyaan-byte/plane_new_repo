# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Serializers for reusable work item templates."""

from uuid import UUID

from rest_framework import serializers

from plane.db.models import WorkItemTemplate

from .base import BaseSerializer
from .user import UserLiteSerializer


class WorkItemTemplateSerializer(BaseSerializer):
    """Validate the small, explicit set of fields a template may pre-fill."""

    created_by = UserLiteSerializer(read_only=True)
    scope = serializers.SerializerMethodField()
    project_id = serializers.SerializerMethodField()
    workspace_id = serializers.SerializerMethodField()

    ALLOWED_FIELDS = {
        "title_template",
        "description_template",
        "priority",
        "label_ids",
        "assignee_id",
        "type_id",
        "state_id",
        "module_id",
        "cycle_id",
    }
    TEXT_FIELDS = {"title_template", "description_template", "priority"}
    ID_FIELDS = {"assignee_id", "type_id", "state_id", "module_id", "cycle_id"}

    class Meta:
        model = WorkItemTemplate
        fields = [
            "id",
            "name",
            "description",
            "template_data",
            "is_public",
            "scope",
            "workspace_id",
            "project_id",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "scope", "workspace_id", "project_id", "created_by", "created_at", "updated_at"]

    def get_scope(self, instance):
        return "project" if instance.project_id else "workspace"

    def get_project_id(self, instance):
        return str(instance.project_id) if instance.project_id else None

    def get_workspace_id(self, instance):
        return str(instance.workspace_id) if instance.workspace_id else None

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Name is required")
        return name

    def validate_template_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("template_data must be an object")
        unknown = set(value) - self.ALLOWED_FIELDS
        if unknown:
            raise serializers.ValidationError(f"Unsupported template fields: {', '.join(sorted(unknown))}")
        for key, item in value.items():
            if key in self.TEXT_FIELDS and not isinstance(item, str):
                raise serializers.ValidationError(f"{key} must be a string")
            if key == "label_ids":
                if not isinstance(item, list) or any(not self._is_uuid(value) for value in item):
                    raise serializers.ValidationError("label_ids must be a list of UUIDs")
            if key in self.ID_FIELDS and item is not None and not self._is_uuid(item):
                raise serializers.ValidationError(f"{key} must be a UUID or null")
        return value

    @staticmethod
    def _is_uuid(value):
        try:
            UUID(str(value))
            return True
        except (TypeError, ValueError):
            return False
