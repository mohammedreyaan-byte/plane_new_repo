# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Report queries.

Definitions (see PLN-019):

* Open      - state group in backlog, unstarted, started; not archived, deleted or draft.
* Resolved  - state group completed (``completed_at`` is the resolution time).
* Cancelled - state group cancelled. Reported separately, never counted as resolved.
* Bug       - issue type key ``bug``. Projects with work item types switched off fall back to
              the legacy ``type: bug`` label and say so in ``meta.deprecation_note``.

Triage (intake) items and drafts are never counted. Archived items are not "open" but still
count as created/resolved/cancelled, so auto-archiving completed work does not rewrite history.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone

from plane.db.models import (
    Cycle,
    CycleIssue,
    Issue,
    IssueAssignee,
    IssueLabel,
    Module,
    ModuleIssue,
    State,
)
from plane.utils.analytics_plot import burndown_plot
from plane.utils.reports.filters import ALL_TYPES, ReportFilterError, resolve_date_range

OPEN_GROUPS = ("backlog", "unstarted", "started")
GROUP_ORDER = {"backlog": 0, "unstarted": 1, "started": 2, "completed": 3, "cancelled": 4}
PRIORITY_ORDER = ("urgent", "high", "medium", "low", "none")
PRIORITY_LABELS = {"urgent": "Urgent", "high": "High", "medium": "Medium", "low": "Low", "none": "None"}
OPEN_DEFINITION = (
    "state group in (backlog, unstarted, started); not archived, not deleted, not draft. "
    "Cancelled work is reported separately and never counted as resolved."
)
LEGACY_BUG_LABEL = "type: bug"


class ReportNotFound(Exception):
    """A cycle/module referenced by a filter does not exist in this project."""


class ReportContext:
    def __init__(self, project, filters, now=None):
        self.project = project
        self.filters = filters
        self.tz = ZoneInfo(project.timezone or "UTC")
        self.now = now or timezone.now()
        self.today = self.now.astimezone(self.tz).date()

    def local_bounds(self, date_from, date_to):
        """Aware [start, end) datetimes covering the local dates date_from..date_to inclusive."""
        start = datetime.combine(date_from, time.min, tzinfo=self.tz)
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=self.tz)
        return start, end


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


def _all_issues(ctx):
    """Every real work item of the project: not deleted, not draft, not triage."""
    return (
        Issue.objects.filter(project=ctx.project, is_draft=False)
        .exclude(state__group="triage")
        .exclude(project__archived_at__isnull=False)
    )


def _open(qs):
    return qs.filter(archived_at__isnull=True, state__group__in=OPEN_GROUPS)


def _scope(ctx, default_bugs):
    """Return (Q, info) for the work item type scope of a report."""
    type_id = ctx.filters.get("type_id")
    if type_id == ALL_TYPES:
        return Q(), {"mode": "all", "label": "All work items"}
    if type_id:
        return Q(type_id=type_id), {"mode": "type", "label": "Selected work item type"}
    if not default_bugs:
        return Q(), {"mode": "all", "label": "All work items"}
    if ctx.project.is_issue_type_enabled:
        return Q(type__key="bug"), {"mode": "type", "label": "Bugs"}
    labelled = IssueLabel.objects.filter(project=ctx.project, label__name__iexact=LEGACY_BUG_LABEL).values("issue_id")
    return Q(id__in=labelled), {
        "mode": "label",
        "label": "Bugs",
        "deprecation_note": (
            "Work item types are not enabled for this project, so bugs are identified by the legacy "
            f'"{LEGACY_BUG_LABEL}" label. Enable work item types to report on the Bug type.'
        ),
    }


def _common_filters(ctx, qs, with_dates):
    f = ctx.filters
    if f.get("cycle_id"):
        qs = qs.filter(id__in=CycleIssue.objects.filter(project=ctx.project, cycle_id=f["cycle_id"]).values("issue_id"))
    if f.get("module_id"):
        qs = qs.filter(
            id__in=ModuleIssue.objects.filter(project=ctx.project, module_id=f["module_id"]).values("issue_id")
        )
    if f.get("assignee_id"):
        qs = qs.filter(
            id__in=IssueAssignee.objects.filter(project=ctx.project, assignee_id=f["assignee_id"]).values("issue_id")
        )
    if f.get("label_id"):
        qs = qs.filter(id__in=IssueLabel.objects.filter(project=ctx.project, label_id=f["label_id"]).values("issue_id"))
    if f.get("priority"):
        qs = qs.filter(priority=f["priority"])
    if with_dates and (f.get("date_from") or f.get("date_to")):
        date_from = f.get("date_from") or (f["date_to"] - timedelta(days=730))
        date_to = f.get("date_to") or ctx.today
        start, end = ctx.local_bounds(date_from, date_to)
        qs = qs.filter(created_at__gte=start, created_at__lt=end)
    return qs


def _base(ctx, default_bugs, with_dates=True):
    scope, info = _scope(ctx, default_bugs)
    qs = _common_filters(ctx, _all_issues(ctx).filter(scope), with_dates)
    return qs, info


def _summary(ctx, base):
    """Open / resolved / cancelled counts for the same scope and filters."""
    return {
        "open": _open(base).count(),
        "resolved": base.filter(state__group="completed").count(),
        "cancelled": base.filter(state__group="cancelled").count(),
    }


def _periods(date_from, date_to, interval):
    if interval == "month":
        cursor = date_from.replace(day=1)
        while cursor <= date_to:
            yield cursor
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        cursor = date_from - timedelta(days=date_from.weekday())
        while cursor <= date_to:
            yield cursor
            cursor += timedelta(days=7)


def _project_cycle(ctx, cycle_id):
    cycle = Cycle.objects.filter(pk=cycle_id, project=ctx.project).first()
    if not cycle:
        raise ReportNotFound("cycle")
    return cycle


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def bugs_by_state(ctx):
    base, info = _base(ctx, default_bugs=True)
    counts = {
        row["state_id"]: row
        for row in _open(base)
        .values("state_id", "state__name", "state__group", "state__sequence")
        .annotate(count=Count("id", distinct=True))
    }
    rows = []
    for state_id, row in counts.items():
        rows.append(
            {
                "state_id": str(state_id),
                "state": row["state__name"],
                "group": row["state__group"],
                "count": row["count"],
                "_sort": (GROUP_ORDER.get(row["state__group"], 9), row["state__sequence"] or 0, row["state__name"]),
            }
        )
    # Active open states with no items still get a row so the chart shape is stable.
    for state in State.objects.filter(project=ctx.project, group__in=OPEN_GROUPS):
        if state.id not in counts:
            rows.append(
                {
                    "state_id": str(state.id),
                    "state": state.name,
                    "group": state.group,
                    "count": 0,
                    "_sort": (GROUP_ORDER.get(state.group, 9), state.sequence or 0, state.name),
                }
            )
    rows.sort(key=lambda r: r["_sort"])
    for row in rows:
        del row["_sort"]
    return {
        "total": sum(r["count"] for r in rows),
        "rows": rows,
        "columns": [
            {"key": "state", "label": "State"},
            {"key": "group", "label": "Group"},
            {"key": "count", "label": "Open items"},
        ],
        "meta": {"scope": info, "summary": _summary(ctx, base)},
    }


def bugs_by_priority(ctx):
    base, info = _base(ctx, default_bugs=True)
    counts = {
        row["priority"]: row["count"]
        for row in _open(base).values("priority").annotate(count=Count("id", distinct=True))
    }
    rows = [
        {"priority": p, "label": PRIORITY_LABELS[p], "count": counts.get(p, 0)}
        for p in PRIORITY_ORDER  # "none" is its own bucket, never merged into "low"
    ]
    return {
        "total": sum(r["count"] for r in rows),
        "rows": rows,
        "columns": [
            {"key": "label", "label": "Priority"},
            {"key": "count", "label": "Open items"},
        ],
        "meta": {"scope": info, "summary": _summary(ctx, base)},
    }


def created_vs_resolved(ctx):
    interval = ctx.filters.get("interval") or "week"
    date_from, date_to = resolve_date_range(ctx.filters, ctx.today)
    start, end = ctx.local_bounds(date_from, date_to)
    base, info = _base(ctx, default_bugs=True, with_dates=False)
    trunc = TruncMonth if interval == "month" else TruncWeek

    created = defaultdict(int)
    for row in (
        base.filter(created_at__gte=start, created_at__lt=end)
        .annotate(period=trunc("created_at", tzinfo=ctx.tz))
        .values("period")
        .annotate(count=Count("id", distinct=True))
    ):
        created[row["period"].astimezone(ctx.tz).date()] += row["count"]

    resolved = defaultdict(int)
    for row in (
        base.filter(state__group="completed", completed_at__gte=start, completed_at__lt=end)
        .annotate(period=trunc("completed_at", tzinfo=ctx.tz))
        .values("period")
        .annotate(count=Count("id", distinct=True))
    ):
        resolved[row["period"].astimezone(ctx.tz).date()] += row["count"]

    rows = [
        {"period": p.isoformat(), "created": created.get(p, 0), "resolved": resolved.get(p, 0)}
        for p in _periods(date_from, date_to, interval)
    ]
    return {
        "total": sum(r["created"] for r in rows),
        "rows": rows,
        "columns": [
            {"key": "period", "label": "Week starting" if interval == "week" else "Month"},
            {"key": "created", "label": "Created"},
            {"key": "resolved", "label": "Resolved"},
        ],
        "meta": {
            "scope": info,
            "interval": interval,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "summary": _summary(ctx, base),
        },
    }


def cycle_burndown(ctx):
    cycle_id = ctx.filters["cycle_id"]
    _project_cycle(ctx, cycle_id)
    plot = ctx.filters.get("plot") or "issues"
    cycle = Cycle.objects.annotate(
        total_issues=Count(
            "issue_cycle__issue__id",
            distinct=True,
            filter=Q(
                issue_cycle__issue__archived_at__isnull=True,
                issue_cycle__issue__is_draft=False,
                issue_cycle__deleted_at__isnull=True,
                issue_cycle__issue__deleted_at__isnull=True,
            ),
        )
    ).get(pk=cycle_id, project=ctx.project)

    if plot == "points":
        project = ctx.project
        if not (project.estimate_id and project.estimate and project.estimate.type == "points"):
            raise ReportFilterError("points_unavailable", "This project does not use point estimates.")

    note = None
    if not (cycle.start_date and cycle.end_date):
        chart = {}
        note = "The cycle has no start and end date, so there is nothing to plot."
    else:
        # Same function the cycle page uses, so the numbers always match the existing chart.
        chart = burndown_plot(
            queryset=cycle,
            slug=ctx.project.workspace.slug,
            project_id=ctx.project.id,
            plot_type=plot,
            cycle_id=cycle_id,
        )

    dates = list(chart.keys())
    total = float(cycle.total_issues) if plot == "issues" else float(next(iter(chart.values()), 0) or 0)
    rows = []
    for index, day in enumerate(dates):
        remaining = chart[day]
        ideal = round(total * (1 - index / (len(dates) - 1)), 2) if len(dates) > 1 else total
        rows.append({"date": day, "remaining": remaining, "ideal": ideal})
    return {
        "total": cycle.total_issues,
        "rows": rows,
        "columns": [
            {"key": "date", "label": "Date"},
            {"key": "remaining", "label": "Remaining points" if plot == "points" else "Remaining items"},
            {"key": "ideal", "label": "Ideal"},
        ],
        "meta": {
            "plot": plot,
            "cycle": {"id": str(cycle.id), "name": cycle.name},
            "note": note,
            "filters_ignored": ["assignee_id", "label_id", "priority", "type_id", "module_id", "date_from", "date_to"],
        },
    }


def cycle_scope(ctx):
    cycle = _project_cycle(ctx, ctx.filters["cycle_id"])
    items = CycleIssue.all_objects.filter(project=ctx.project, cycle=cycle).filter(
        issue__deleted_at__isnull=True, issue__is_draft=False
    )
    start = cycle.start_date
    initial = added = removed = 0
    per_day = defaultdict(lambda: {"added": 0, "removed": 0})
    for created_at, deleted_at in items.values_list("created_at", "deleted_at"):
        if start is None or created_at <= start:
            initial += 1
        else:
            added += 1
            per_day[created_at.astimezone(ctx.tz).date()]["added"] += 1
        if deleted_at is not None:
            removed += 1
            per_day[deleted_at.astimezone(ctx.tz).date()]["removed"] += 1
    rows = [{"date": d.isoformat(), **per_day[d]} for d in sorted(per_day)]
    current = items.filter(deleted_at__isnull=True).count()
    return {
        "total": added + removed,
        "rows": rows,
        "columns": [
            {"key": "date", "label": "Date"},
            {"key": "added", "label": "Added"},
            {"key": "removed", "label": "Removed"},
        ],
        "meta": {
            "cycle": {"id": str(cycle.id), "name": cycle.name},
            "summary": {"initial": initial, "added": added, "removed": removed, "current": current},
        },
    }


def module_progress(ctx):
    base, info = _base(ctx, default_bugs=False, with_dates=True)
    base = base.filter(archived_at__isnull=True)
    modules = Module.objects.filter(project=ctx.project, archived_at__isnull=True).order_by("name")
    if ctx.filters.get("module_id"):
        modules = modules.filter(pk=ctx.filters["module_id"])

    stats = defaultdict(lambda: {"total": 0, "completed": 0, "cancelled": 0, "total_points": 0.0, "points_done": 0.0})
    links = ModuleIssue.objects.filter(project=ctx.project, issue_id__in=base.values("id")).values_list(
        "module_id", "issue__state__group", "issue__estimate_point__value"
    )
    for module_id, group, point in links:
        entry = stats[module_id]
        try:
            value = float(point) if point is not None else 0.0
        except (TypeError, ValueError):
            value = 0.0
        entry["total"] += 1
        entry["total_points"] += value
        if group == "completed":
            entry["completed"] += 1
            entry["points_done"] += value
        elif group == "cancelled":
            entry["cancelled"] += 1

    rows = []
    for module in modules:
        entry = stats[module.id]
        rows.append(
            {
                "module_id": str(module.id),
                "module": module.name,
                "status": module.status,
                "total": entry["total"],
                "completed": entry["completed"],
                "cancelled": entry["cancelled"],
                "progress": round(entry["completed"] * 100 / entry["total"], 1) if entry["total"] else 0,
                "total_points": entry["total_points"],
                "completed_points": entry["points_done"],
            }
        )
    return {
        "total": len(rows),
        "rows": rows,
        "columns": [
            {"key": "module", "label": "Module"},
            {"key": "status", "label": "Status"},
            {"key": "total", "label": "Items"},
            {"key": "completed", "label": "Completed"},
            {"key": "cancelled", "label": "Cancelled"},
            {"key": "progress", "label": "Progress %"},
            {"key": "total_points", "label": "Points"},
            {"key": "completed_points", "label": "Points done"},
        ],
        "meta": {"scope": info},
    }


REPORTS = {
    "bugs_by_state": bugs_by_state,
    "bugs_by_priority": bugs_by_priority,
    "created_vs_resolved": created_vs_resolved,
    "cycle_burndown": cycle_burndown,
    "cycle_scope": cycle_scope,
    "module_progress": module_progress,
}

# URL slug -> report type for the built-in endpoints
BUILT_IN_SLUGS = {
    "bugs-by-state": "bugs_by_state",
    "bugs-by-priority": "bugs_by_priority",
    "created-vs-resolved": "created_vs_resolved",
    "cycle-burndown": "cycle_burndown",
    "cycle-scope": "cycle_scope",
    "module-progress": "module_progress",
}

REPORT_TITLES = {
    "bugs_by_state": "Open bugs by state",
    "bugs_by_priority": "Open bugs by priority",
    "created_vs_resolved": "Created vs resolved",
    "cycle_burndown": "Cycle burndown",
    "cycle_scope": "Cycle scope changes",
    "module_progress": "Module progress",
}
