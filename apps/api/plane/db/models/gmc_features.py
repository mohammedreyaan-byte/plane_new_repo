# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Database models for the production GMC feature backend.

These models back the five UI features delivered in the first five prompts:
initiatives, rule based automations, Slack notifications, GitHub/GitLab
integrations and work item imports.  All provider tokens and webhook secrets are
stored encrypted and are never exposed through serializers.
"""

import uuid

from django.conf import settings
from django.db import models

from .base import BaseModel
from .project import ProjectBaseModel
from .workspace import WorkspaceBaseModel


class Initiative(ProjectBaseModel):
    """A strategic initiative linked to real modules and epics."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(max_length=500)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED, db_index=True)
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="owned_initiatives",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    modules = models.ManyToManyField("db.Module", related_name="initiatives", blank=True)
    epics = models.ManyToManyField("db.Issue", related_name="initiative_epics", blank=True)

    class Meta:
        db_table = "gmc_initiatives"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["project", "status"], name="gmc_init_proj_status_idx")]


class AutomationRule(ProjectBaseModel):
    """A project rule evaluated against real work item events."""

    class Trigger(models.TextChoices):
        CREATED = "created", "Work item created"
        STATE_CHANGED = "state_changed", "State changed"
        PRIORITY_CHANGED = "priority_changed", "Priority changed"
        ASSIGNED = "assigned", "Assignee changed"
        DUE_DATE = "due_date", "Due date reached"

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    trigger = models.CharField(max_length=40, choices=Trigger.choices, db_index=True)
    conditions = models.JSONField(default=list, blank=True)
    actions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    last_evaluated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "gmc_automation_rules"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["project", "is_active"], name="gmc_auto_rule_active_idx")]


class AutomationRun(ProjectBaseModel):
    """Audit record for one automation evaluation."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    rule = models.ForeignKey(AutomationRule, related_name="runs", on_delete=models.CASCADE)
    work_item = models.ForeignKey("db.Issue", related_name="automation_runs", on_delete=models.CASCADE, null=True)
    trigger = models.CharField(max_length=40)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCESS, db_index=True)
    message = models.TextField(blank=True, default="")
    details = models.JSONField(default=dict, blank=True)
    dry_run = models.BooleanField(default=False)

    class Meta:
        db_table = "gmc_automation_runs"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["project", "created_at"], name="gmc_auto_run_project_idx")]


class ExternalAccountIntegration(WorkspaceBaseModel):
    """An OAuth connection to GitHub, GitLab or Slack for one workspace."""

    class Provider(models.TextChoices):
        GITHUB = "github", "GitHub"
        GITLAB = "gitlab", "GitLab"
        SLACK = "slack", "Slack"

    provider = models.CharField(max_length=20, choices=Provider.choices, db_index=True)
    provider_account_id = models.CharField(max_length=255)
    account_name = models.CharField(max_length=500, blank=True, default="")
    host = models.CharField(max_length=500, blank=True, default="")
    access_token = models.TextField(blank=True, default="")
    refresh_token = models.TextField(blank=True, default="")
    scopes = models.JSONField(default=list, blank=True)
    webhook_secret = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    def set_access_token(self, value: str) -> None:
        from plane.license.utils.encryption import encrypt_data

        self.access_token = encrypt_data(value) if value else ""

    def get_access_token(self) -> str:
        from plane.license.utils.encryption import decrypt_data

        return decrypt_data(self.access_token) if self.access_token else ""

    def set_webhook_secret(self, value: str) -> None:
        from plane.license.utils.encryption import encrypt_data

        self.webhook_secret = encrypt_data(value) if value else ""

    def get_webhook_secret(self) -> str:
        from plane.license.utils.encryption import decrypt_data

        return decrypt_data(self.webhook_secret) if self.webhook_secret else ""

    class Meta:
        db_table = "gmc_external_integrations"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "provider", "provider_account_id"],
                name="gmc_ext_int_unique_account",
            )
        ]


class ExternalRepository(WorkspaceBaseModel):
    """A repository discovered through a connected GitHub/GitLab account."""

    integration = models.ForeignKey(
        ExternalAccountIntegration, related_name="repositories", on_delete=models.CASCADE
    )
    provider = models.CharField(max_length=20, db_index=True)
    external_id = models.CharField(max_length=255)
    full_name = models.CharField(max_length=500)
    url = models.URLField(max_length=1000, blank=True, default="")
    is_sync_enabled = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "gmc_external_repositories"
        ordering = ("full_name",)
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "external_id"], name="gmc_ext_repo_unique_ext_id"
            )
        ]


class SlackChannelSubscription(WorkspaceBaseModel):
    """A Slack channel that receives notifications for a workspace/project."""

    integration = models.ForeignKey(
        ExternalAccountIntegration, related_name="slack_channels", on_delete=models.CASCADE
    )
    channel_id = models.CharField(max_length=100)
    channel_name = models.CharField(max_length=300)
    member_count = models.PositiveIntegerField(default=0)
    is_default = models.BooleanField(default=False)
    events = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    last_posted_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "gmc_slack_channel_subscriptions"
        ordering = ("channel_name",)
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "channel_id"], name="gmc_slack_chan_unique"
            )
        ]


class ExternalWebhookEvent(WorkspaceBaseModel):
    """Idempotent audit log for inbound provider webhooks."""

    integration = models.ForeignKey(
        ExternalAccountIntegration,
        related_name="webhook_events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    provider = models.CharField(max_length=20, db_index=True)
    event_type = models.CharField(max_length=255, db_index=True)
    delivery_id = models.CharField(max_length=255, unique=True, default=uuid.uuid4)
    signature_verified = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default="received")
    payload = models.JSONField(default=dict, blank=True)
    work_item = models.ForeignKey(
        "db.Issue", related_name="external_webhook_events", on_delete=models.SET_NULL, null=True, blank=True
    )
    detail = models.TextField(blank=True, default="")

    class Meta:
        db_table = "gmc_external_webhook_events"
        ordering = ("-created_at",)


class ExternalMessageLog(WorkspaceBaseModel):
    """Audit log for messages posted to Slack."""

    integration = models.ForeignKey(
        ExternalAccountIntegration, related_name="message_logs", on_delete=models.CASCADE
    )
    provider = models.CharField(max_length=20, default="slack")
    event_type = models.CharField(max_length=255)
    channel = models.CharField(max_length=300)
    work_item = models.ForeignKey(
        "db.Issue", related_name="external_message_logs", on_delete=models.SET_NULL, null=True, blank=True
    )
    status = models.CharField(max_length=20, default="sent")
    provider_message_id = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "gmc_external_message_logs"
        ordering = ("-created_at",)


class OAuthAuthorizationRequest(BaseModel):
    """Short-lived state record for provider OAuth callbacks."""

    workspace = models.ForeignKey("db.Workspace", related_name="gmc_oauth_requests", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="gmc_oauth_requests", on_delete=models.CASCADE)
    provider = models.CharField(max_length=20)
    state = models.CharField(max_length=255, unique=True, default=uuid.uuid4)
    redirect_uri = models.TextField(blank=True, default="")
    scopes = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "gmc_oauth_authorization_requests"
        ordering = ("-created_at",)
