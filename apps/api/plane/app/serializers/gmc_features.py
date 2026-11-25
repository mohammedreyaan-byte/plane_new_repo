# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Serializers for the production GMC feature APIs."""

from rest_framework import serializers

from plane.db.models import (
    AutomationRule,
    AutomationRun,
    ExternalAccountIntegration,
    ExternalMessageLog,
    ExternalRepository,
    ExternalWebhookEvent,
    Initiative,
    SlackChannelSubscription,
)
from plane.db.models.importer import Importer

from .base import BaseSerializer
from .user import UserLiteSerializer


class InitiativeSerializer(BaseSerializer):
    owner = serializers.PrimaryKeyRelatedField(queryset=Initiative._meta.get_field("owner").related_model.objects.all(), required=False, allow_null=True)
    module_ids = serializers.PrimaryKeyRelatedField(
        source="modules", queryset=Initiative._meta.get_field("modules").related_model.objects.all(), many=True, write_only=True, required=False
    )
    epic_ids = serializers.PrimaryKeyRelatedField(
        source="epics", queryset=Initiative._meta.get_field("epics").related_model.objects.all(), many=True, write_only=True, required=False
    )
    owner_detail = UserLiteSerializer(source="owner", read_only=True)
    children = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = Initiative
        fields = [
            "id",
            "name",
            "description",
            "status",
            "start_date",
            "target_date",
            "owner",
            "owner_detail",
            "module_ids",
            "epic_ids",
            "children",
            "progress",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        start_date = attrs.get("start_date", getattr(self.instance, "start_date", None))
        target_date = attrs.get("target_date", getattr(self.instance, "target_date", None))
        if start_date and target_date and start_date > target_date:
            raise serializers.ValidationError("Target date must be on or after the start date")
        return attrs

    @staticmethod
    def _child(record, child_type, completed):
        owner = getattr(record, "lead", None) if child_type == "Module" else None
        if child_type == "Epic":
            assignee_links = list(record.issue_assignee.all())
            owner = assignee_links[0].assignee if assignee_links else None
        return {
            "id": str(record.id),
            "name": record.name,
            "type": child_type,
            "owner": getattr(owner, "display_name", "") if owner else "",
            "start_date": getattr(record, "start_date", None),
            "target_date": getattr(record, "target_date", None),
            "completed": bool(completed),
        }

    def get_children(self, instance):
        children = []
        for module in instance.modules.select_related("lead").all():
            children.append(self._child(module, "Module", module.status == "completed"))
        for epic in instance.epics.select_related("state").prefetch_related("issue_assignee__assignee").all():
            completed = bool(epic.state and epic.state.group == "completed")
            children.append(self._child(epic, "Epic", completed))
        return children

    def get_progress(self, instance):
        children = self.get_children(instance)
        if not children:
            return 100 if instance.status == Initiative.Status.COMPLETED else 0
        return round(sum(1 for child in children if child["completed"]) * 100 / len(children))


class AutomationRuleSerializer(BaseSerializer):
    class Meta:
        model = AutomationRule
        fields = [
            "id",
            "name",
            "description",
            "trigger",
            "conditions",
            "actions",
            "is_active",
            "last_evaluated_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "last_evaluated_at", "created_at", "updated_at"]

    def validate_conditions(self, value):
        allowed_fields = {"state", "priority", "assignee", "label", "type"}
        allowed_operators = {"is", "is not", "contains"}
        for condition in value:
            if not isinstance(condition, dict):
                raise serializers.ValidationError("Each condition must be an object")
            if condition.get("field") not in allowed_fields:
                raise serializers.ValidationError("Unsupported condition field")
            if condition.get("operator") not in allowed_operators:
                raise serializers.ValidationError("Unsupported condition operator")
            if not str(condition.get("value", "")).strip():
                raise serializers.ValidationError("Condition value is required")
        return value

    def validate_actions(self, value):
        allowed_actions = {
            "change_state",
            "assign_user",
            "add_label",
            "add_comment",
            "send_notification",
            "set_priority",
        }
        for action in value:
            if not isinstance(action, dict):
                raise serializers.ValidationError("Each action must be an object")
            if action.get("type") not in allowed_actions:
                raise serializers.ValidationError("Unsupported action type")
            if not str(action.get("value", "")).strip():
                raise serializers.ValidationError("Action value is required")
        return value


class AutomationRunSerializer(BaseSerializer):
    rule_name = serializers.CharField(source="rule.name", read_only=True)
    work_item_identifier = serializers.SerializerMethodField()

    class Meta:
        model = AutomationRun
        fields = [
            "id",
            "rule",
            "rule_name",
            "work_item",
            "work_item_identifier",
            "trigger",
            "status",
            "message",
            "details",
            "dry_run",
            "created_at",
        ]
        read_only_fields = fields

    def get_work_item_identifier(self, instance):
        if not instance.work_item_id:
            return ""
        return f"{instance.work_item.project.identifier}-{instance.work_item.sequence_id}"


class ExternalAccountIntegrationSerializer(BaseSerializer):
    provider_label = serializers.CharField(source="get_provider_display", read_only=True)

    class Meta:
        model = ExternalAccountIntegration
        fields = [
            "id",
            "provider",
            "provider_label",
            "provider_account_id",
            "account_name",
            "host",
            "scopes",
            "metadata",
            "is_active",
            "last_synced_at",
            "created_at",
        ]
        read_only_fields = fields


class ExternalRepositorySerializer(BaseSerializer):
    class Meta:
        model = ExternalRepository
        fields = [
            "id",
            "provider",
            "external_id",
            "full_name",
            "url",
            "is_sync_enabled",
            "last_synced_at",
            "metadata",
        ]
        read_only_fields = ["id", "provider", "external_id", "full_name", "url", "last_synced_at", "metadata"]


class SlackChannelSubscriptionSerializer(BaseSerializer):
    class Meta:
        model = SlackChannelSubscription
        fields = [
            "id",
            "channel_id",
            "channel_name",
            "member_count",
            "is_default",
            "events",
            "is_active",
            "last_posted_at",
            "last_error",
        ]
        read_only_fields = ["id", "last_posted_at", "last_error"]


class ExternalWebhookEventSerializer(BaseSerializer):
    work_item_identifier = serializers.SerializerMethodField()

    class Meta:
        model = ExternalWebhookEvent
        fields = [
            "id",
            "provider",
            "event_type",
            "delivery_id",
            "signature_verified",
            "status",
            "work_item",
            "work_item_identifier",
            "detail",
            "created_at",
        ]
        read_only_fields = fields

    def get_work_item_identifier(self, instance):
        if not instance.work_item_id:
            return ""
        return f"{instance.work_item.project.identifier}-{instance.work_item.sequence_id}"


class ExternalMessageLogSerializer(BaseSerializer):
    work_item_identifier = serializers.SerializerMethodField()

    class Meta:
        model = ExternalMessageLog
        fields = [
            "id",
            "provider",
            "event_type",
            "channel",
            "work_item",
            "work_item_identifier",
            "status",
            "provider_message_id",
            "error",
            "sent_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_work_item_identifier(self, instance):
        if not instance.work_item_id:
            return ""
        return f"{instance.work_item.project.identifier}-{instance.work_item.sequence_id}"


class GmcImporterSerializer(BaseSerializer):
    initiated_by_detail = UserLiteSerializer(source="initiated_by", read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        config = dict(data.get("config") or {})
        for key in ("csv_content", "api_token", "token", "email", "site_url", "owner", "repo", "project_key"):
            if key in config:
                config[key] = "********" if config[key] else ""
        data["config"] = config
        return data

    class Meta:
        model = Importer
        fields = [
            "id",
            "service",
            "status",
            "file_name",
            "metadata",
            "config",
            "data",
            "total_count",
            "created_count",
            "error_count",
            "progress",
            "error_log",
            "started_at",
            "finished_at",
            "created_at",
            "initiated_by",
            "initiated_by_detail",
        ]
        read_only_fields = [
            "id",
            "status",
            "total_count",
            "created_count",
            "error_count",
            "progress",
            "error_log",
            "started_at",
            "finished_at",
            "created_at",
            "initiated_by",
            "initiated_by_detail",
        ]
