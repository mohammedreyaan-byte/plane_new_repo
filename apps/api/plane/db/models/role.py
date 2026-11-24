# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models

# Module imports
from .base import BaseModel


class Role(BaseModel):
    """A role definition.

    `workspace` is null for system roles that are available to every workspace.
    Workspace scoped roles allow customers to add custom roles later without
    changing the membership tables again.
    """

    workspace = models.ForeignKey(
        "db.Workspace",
        on_delete=models.CASCADE,
        related_name="roles",
        null=True,
        blank=True,
    )
    key = models.SlugField(max_length=50)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    # Compatibility with the legacy integer role column. Developer/QA/Viewer
    # reuse unused integer values so old integer comparisons keep a meaning.
    legacy_id = models.PositiveSmallIntegerField(null=True, blank=True, unique=True)
    level = models.PositiveSmallIntegerField(default=0)
    capabilities = models.JSONField(default=list)
    is_system = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Role"
        verbose_name_plural = "Roles"
        db_table = "roles"
        ordering = ("-level", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "key"],
                condition=models.Q(deleted_at__isnull=True),
                name="role_unique_workspace_key_when_deleted_at_null",
            ),
            models.UniqueConstraint(
                fields=["key"],
                condition=models.Q(workspace__isnull=True, deleted_at__isnull=True),
                name="role_unique_system_key_when_deleted_at_null",
            ),
        ]

    def __str__(self):
        return f"{self.name} <{self.workspace or 'system'}>"

    def save(self, *args, **kwargs):
        # System role keys are lower case slugs.
        if self.key:
            self.key = self.key.strip().lower()
        super().save(*args, **kwargs)


class RoleAuditLog(BaseModel):
    """Audit trail for role changes.

    This deliberately lives beside the Role model instead of IssueActivity so
    that membership changes are auditable even when no project exists yet.
    """

    SCOPE_WORKSPACE = "workspace"
    SCOPE_PROJECT = "project"
    SCOPE_CHOICES = ((SCOPE_WORKSPACE, "Workspace"), (SCOPE_PROJECT, "Project"))

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="role_audit_logs")
    project = models.ForeignKey(
        "db.Project",
        on_delete=models.CASCADE,
        related_name="role_audit_logs",
        null=True,
        blank=True,
    )
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_WORKSPACE)
    actor = models.ForeignKey(
        "db.User",
        on_delete=models.SET_NULL,
        related_name="role_changes_made",
        null=True,
        blank=True,
    )
    target = models.ForeignKey(
        "db.User",
        on_delete=models.SET_NULL,
        related_name="role_changes_received",
        null=True,
        blank=True,
    )
    old_role = models.CharField(max_length=50, blank=True)
    new_role = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name = "Role Audit Log"
        verbose_name_plural = "Role Audit Logs"
        db_table = "role_audit_logs"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.target_id}: {self.old_role} -> {self.new_role}"
