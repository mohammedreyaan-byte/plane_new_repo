# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_delete, post_save

from .project import ProjectBaseModel


class ReportDefinition(ProjectBaseModel):
    """A saved report: a built-in report type plus filters and a chart type.

    Results are never stored. They are computed on request (and cached for a minute).
    """

    BUGS_BY_STATE = "bugs_by_state"
    BUGS_BY_PRIORITY = "bugs_by_priority"
    CREATED_VS_RESOLVED = "created_vs_resolved"
    CYCLE_BURNDOWN = "cycle_burndown"
    CYCLE_SCOPE = "cycle_scope"
    MODULE_PROGRESS = "module_progress"

    REPORT_TYPE_CHOICES = (
        (BUGS_BY_STATE, "Open bugs by state"),
        (BUGS_BY_PRIORITY, "Open bugs by priority"),
        (CREATED_VS_RESOLVED, "Created vs resolved"),
        (CYCLE_BURNDOWN, "Cycle burndown"),
        (CYCLE_SCOPE, "Cycle scope changes"),
        (MODULE_PROGRESS, "Module progress"),
    )
    CHART_TYPE_CHOICES = (
        ("bar", "Bar"),
        ("line", "Line"),
        ("table", "Table"),
        ("donut", "Donut"),
    )

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    report_type = models.CharField(max_length=50, choices=REPORT_TYPE_CHOICES)
    filters = models.JSONField(default=dict)
    group_by = models.CharField(max_length=50, blank=True, default="")
    chart_type = models.CharField(max_length=20, choices=CHART_TYPE_CHOICES, default="bar")
    is_shared = models.BooleanField(default=False)
    owned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_reports",
    )

    class Meta:
        verbose_name = "Report Definition"
        verbose_name_plural = "Report Definitions"
        db_table = "report_definitions"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name"],
                condition=Q(deleted_at__isnull=True),
                name="report_definition_unique_project_name_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.project_id} - {self.name}"


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------
# Report responses are cached per project for a short time. Every write to the
# tables a report reads bumps a per-project version number that is part of the
# cache key, so a stale response can never outlive a change made through the ORM.
# Bulk ``QuerySet.update()`` calls do not fire signals; the 60 second TTL covers those.

REPORT_CACHE_VERSION_KEY = "reports:version:{project_id}"


def bump_report_cache_version(project_id):
    if not project_id:
        return
    key = REPORT_CACHE_VERSION_KEY.format(project_id=project_id)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, None)
    except Exception:  # cache backend down: reports fall back to the TTL only
        pass


def _bump(sender, instance, **kwargs):
    bump_report_cache_version(getattr(instance, "project_id", None))


def register_report_cache_signals():
    from .cycle import CycleIssue
    from .issue import Issue, IssueLabel
    from .module import ModuleIssue
    from .state import State

    for model in (Issue, State, CycleIssue, ModuleIssue, IssueLabel):
        post_save.connect(_bump, sender=model, dispatch_uid=f"report_cache_save_{model.__name__}")
        post_delete.connect(_bump, sender=model, dispatch_uid=f"report_cache_delete_{model.__name__}")
