# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Additive board metadata for workflow-aware Kanban boards (PLN-009).

The metadata is returned through the paginator's ``extra_stats`` field so the
existing list/board response shape is untouched for legacy clients.
"""

import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from django.db.models import Count

from plane.db.models import IssueType, Workflow, WorkflowState


def _requested_type_ids(request) -> List[str]:
    """Read type filters from direct params or the rich ``filters`` JSON param."""
    values: List[str] = []
    for key in ("type_id", "issue_type", "type_ids"):
        raw = request.GET.get(key)
        if raw:
            values.extend(item for item in str(raw).split(",") if item and item != "null")
    raw_in = request.GET.get("type_id__in")
    if raw_in:
        values.extend(item for item in str(raw_in).split(",") if item and item != "null")

    raw_filters = request.GET.get("filters")
    if raw_filters:
        try:
            parsed = json.loads(raw_filters)
        except (TypeError, ValueError):
            parsed = {}
        stack = [parsed]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            for key, value in node.items():
                if key in ("type_id", "type_id__in", "issue_type"):
                    if isinstance(value, (list, tuple)):
                        values.extend(str(item) for item in value if item and item != "null")
                    elif value and value != "null":
                        values.extend(str(value).split(","))
                else:
                    stack.append(value)

    valid = []
    for value in values:
        try:
            valid.append(str(UUID(str(value))))
        except (ValueError, TypeError, AttributeError):
            continue
    return list(dict.fromkeys(valid))


def _serialize_columns(workflow, workflow_states, counts: Dict[str, int]) -> List[Dict[str, Any]]:
    columns = []
    for ws in workflow_states:
        state = ws.state
        columns.append(
            {
                "state_id": str(ws.state_id),
                "name": state.name if state else None,
                "group": state.group if state else None,
                "color": getattr(state, "color", None),
                "sequence": ws.sequence,
                "wip_limit": ws.wip_limit,
                "count": counts.get(str(ws.state_id), 0),
                "is_initial": ws.is_initial,
                "is_final": ws.is_final,
            }
        )
    return columns


def _workflow_payload(workflow) -> Dict[str, Any]:
    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "type_id": str(workflow.issue_type_id) if workflow.issue_type_id else None,
    }


def build_board_metadata(project, queryset, request) -> Optional[Dict[str, Any]]:
    """Return board columns/workflow/swimlanes, or ``None`` for legacy boards."""
    if not project.is_issue_type_enabled:
        return None
    board_like = request.GET.get("layout") == "board" or request.GET.get("group_by") == "state_id"
    if not board_like:
        return None

    counts = {
        str(row["state_id"]): row["count"]
        for row in queryset.values("state_id").annotate(count=Count("id")).order_by()
    }
    workflows = Workflow.objects.filter(project=project, is_active=True).select_related("issue_type")
    requested_type_ids = _requested_type_ids(request)

    if requested_type_ids:
        workflows = workflows.filter(issue_type_id__in=requested_type_ids)
        workflows = list(workflows)
        if not workflows:
            missing_type = IssueType.objects.filter(id__in=requested_type_ids).first()
            return {
                "health": "no_workflow",
                "columns": [],
                "workflow": None,
                "swimlanes": [],
                "type_id": str(missing_type.id) if missing_type else requested_type_ids[0],
                "board_wip_hard_limit": project.board_wip_hard_limit,
            }
        workflow = workflows[0]
        states = (
            WorkflowState.objects.filter(workflow=workflow, deleted_at__isnull=True)
            .select_related("state")
            .order_by("sequence")
        )
        return {
            "health": "ok",
            "columns": _serialize_columns(workflow, states, counts),
            "workflow": _workflow_payload(workflow),
            "swimlanes": [],
            "type_id": str(workflow.issue_type_id) if workflow.issue_type_id else None,
            "board_wip_hard_limit": project.board_wip_hard_limit,
        }

    # All-types mode: each type keeps its own workflow columns; states are never merged.
    workflows = list(workflows)
    swimlanes = []
    for workflow in workflows:
        states = (
            WorkflowState.objects.filter(workflow=workflow, deleted_at__isnull=True)
            .select_related("state")
            .order_by("sequence")
        )
        swimlanes.append(
            {
                "type_id": str(workflow.issue_type_id) if workflow.issue_type_id else None,
                "type_name": workflow.issue_type.name if workflow.issue_type else workflow.name,
                "workflow": _workflow_payload(workflow),
                "columns": _serialize_columns(workflow, states, counts),
            }
        )
    first = workflows[0] if workflows else None
    return {
        "health": "ok" if workflows else "no_workflow",
        "columns": _serialize_columns(first, [], counts) if first else [],
        "workflow": _workflow_payload(first) if first else None,
        "swimlanes": swimlanes,
        "type_id": None,
        "board_wip_hard_limit": project.board_wip_hard_limit,
    }
