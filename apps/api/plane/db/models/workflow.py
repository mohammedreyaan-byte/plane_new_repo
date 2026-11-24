# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel


class Workflow(ProjectBaseModel):
    """A set of states and allowed transitions for one work item type in a project.

    States are not owned by a workflow: it maps existing ``State`` rows, so cycles,
    analytics and state filters keep working. ``issue_type`` null means a project wide
    default workflow, used for types that have no workflow of their own.
    """

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    issue_type = models.ForeignKey(
        "db.IssueType",
        on_delete=models.CASCADE,
        related_name="workflows",
        null=True,
        blank=True,
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Workflow"
        verbose_name_plural = "Workflows"
        db_table = "workflows"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["project", "issue_type"],
                condition=Q(deleted_at__isnull=True, is_default=True, is_active=True),
                name="workflow_one_active_default_per_type_when_deleted_at_null",
            ),
        ]

    def __str__(self):
        return f"{self.name} <{self.project_id}>"


class WorkflowState(ProjectBaseModel):
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="workflow_states")
    state = models.ForeignKey("db.State", on_delete=models.CASCADE, related_name="workflow_states")
    sequence = models.FloatField(default=65535)
    is_initial = models.BooleanField(default=False)
    is_final = models.BooleanField(default=False)
    wip_limit = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Workflow State"
        verbose_name_plural = "Workflow States"
        db_table = "workflow_states"
        ordering = ("workflow", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "state"],
                condition=Q(deleted_at__isnull=True),
                name="workflow_state_unique_workflow_state_when_deleted_at_null",
            ),
            models.UniqueConstraint(
                fields=["workflow"],
                condition=Q(deleted_at__isnull=True, is_initial=True),
                name="workflow_state_one_initial_when_deleted_at_null",
            ),
        ]

    def __str__(self):
        return f"{self.workflow_id} - {self.state_id}"


class WorkflowTransition(ProjectBaseModel):
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="transitions")
    from_state = models.ForeignKey("db.State", on_delete=models.CASCADE, related_name="transitions_from")
    to_state = models.ForeignKey("db.State", on_delete=models.CASCADE, related_name="transitions_to")
    # Role keys (admin, member, developer, qa ...). Empty list means any contributor.
    allowed_roles = models.JSONField(default=list, blank=True)
    requires_comment = models.BooleanField(default=False)
    # Issue fields that must be set before the move, e.g. ["assignee", "estimate"].
    required_fields = models.JSONField(default=list, blank=True)
    admin_override = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Workflow Transition"
        verbose_name_plural = "Workflow Transitions"
        db_table = "workflow_transitions"
        ordering = ("workflow", "from_state", "to_state")
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "from_state", "to_state"],
                condition=Q(deleted_at__isnull=True),
                name="workflow_transition_unique_edge_when_deleted_at_null",
            ),
            models.CheckConstraint(
                check=~Q(from_state=models.F("to_state")),
                name="workflow_transition_no_self_transition",
            ),
        ]

    def __str__(self):
        return f"{self.from_state_id} -> {self.to_state_id}"
