# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.db.models import ReportDefinition
from plane.utils.reports.filters import SCHEMA_VERSION, ReportFilterError, parse_filters, serialize_filters

from .base import BaseSerializer


class ReportDefinitionSerializer(BaseSerializer):
    is_owner = serializers.SerializerMethodField()
    filters = serializers.JSONField(required=False)

    class Meta:
        model = ReportDefinition
        fields = [
            "id",
            "name",
            "description",
            "report_type",
            "filters",
            "group_by",
            "chart_type",
            "is_shared",
            "owned_by",
            "is_owner",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "owned_by", "is_owner", "created_at", "updated_at"]

    def get_is_owner(self, obj):
        request = self.context.get("request")
        return bool(request and obj.owned_by_id == request.user.id)

    def validate_name(self, value):
        value = " ".join((value or "").split())
        if not value:
            raise serializers.ValidationError("Name is required.")
        return value

    def validate(self, attrs):
        report_type = attrs.get("report_type") or (self.instance.report_type if self.instance else None)
        raw_filters = attrs.get("filters", self.instance.filters if self.instance else {})
        try:
            parsed = parse_filters(raw_filters, report_type)
        except ReportFilterError as exc:
            raise serializers.ValidationError({"filters": exc.message, "code": exc.code})
        stored = {k: v for k, v in serialize_filters(parsed).items() if v is not None}
        stored["schema_version"] = SCHEMA_VERSION
        attrs["filters"] = stored

        name = attrs.get("name") or (self.instance.name if self.instance else None)
        project_id = self.context["project_id"]
        duplicates = ReportDefinition.objects.filter(project_id=project_id, name__iexact=name)
        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError(
                {"name": "A report with this name already exists.", "code": "duplicate_report_name"}
            )
        return attrs
