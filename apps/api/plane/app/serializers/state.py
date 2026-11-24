# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Module imports
import re

from .base import BaseSerializer
from rest_framework import serializers

from plane.db.models import State, StateGroup

HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class StateSerializer(BaseSerializer):
    order = serializers.FloatField(required=False)

    class Meta:
        model = State
        fields = [
            "id",
            "project_id",
            "workspace_id",
            "name",
            "color",
            "group",
            "default",
            "description",
            "sequence",
            "order",
        ]
        read_only_fields = ["workspace", "project"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("State name is required.")
        project_id = self.context.get("project_id")
        if project_id:
            duplicate = State.objects.filter(project_id=project_id, name__iexact=value)
            instance = getattr(self, "instance", None)
            if instance is not None and getattr(instance, "pk", None):
                duplicate = duplicate.exclude(pk=instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError(
                    {"code": "duplicate_state_name", "message": "A state with this name already exists."}
                )
        return value

    def validate_color(self, value):
        value = (value or "").strip()
        if value and not HEX_COLOR.match(value):
            raise serializers.ValidationError(
                {"code": "invalid_state_color", "message": "Color must be a hex value such as #1f2937."}
            )
        return value

    def validate(self, attrs):
        if attrs.get("group") == StateGroup.TRIAGE.value:
            raise serializers.ValidationError("Cannot create triage state")
        if self.instance is None:
            # Sequence is server managed on create; reordering uses the update endpoint.
            attrs.pop("sequence", None)
        return attrs


class StateLiteSerializer(BaseSerializer):
    class Meta:
        model = State
        fields = ["id", "name", "color", "group"]
        read_only_fields = fields
