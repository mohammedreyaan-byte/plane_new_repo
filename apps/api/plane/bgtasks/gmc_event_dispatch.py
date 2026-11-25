# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Fan out real Plane work item activity to GMC automation and Slack tasks."""

import json
from typing import Any, Dict

from plane.bgtasks.gmc_automation_task import evaluate_issue_event, infer_trigger
from plane.bgtasks.gmc_slack_task import dispatch_slack_event
from plane.db.models import AutomationRule


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def dispatch_gmc_issue_event(
    *,
    activity_type: str,
    requested_data: Any,
    current_instance: Any,
    issue_id: str,
    project_id: str,
    actor_id: str,
    origin: str | None,
) -> None:
    """Queue GMC work for an activity recorded by the core issue pipeline."""

    automation_trigger: str | None = None
    slack_event: str | None = None

    if activity_type == "issue.activity.created":
        automation_trigger = "created"
        slack_event = "work_item.created"
    elif activity_type == "issue.activity.updated":
        automation_trigger = infer_trigger(_as_dict(requested_data), _as_dict(current_instance))
        if automation_trigger == "created":
            automation_trigger = None
        elif automation_trigger == "assigned":
            slack_event = "work_item.assigned"
        elif automation_trigger == "state_changed":
            slack_event = "work_item.state_changed"
        elif automation_trigger in ("priority_changed", "due_date"):
            slack_event = None
    elif activity_type == "issue.activity.deleted":
        slack_event = "work_item.deleted"
    elif activity_type == "comment.activity.created":
        slack_event = "work_item.commented"

    if automation_trigger and AutomationRule.objects.filter(
        project_id=project_id, is_active=True, trigger=automation_trigger
    ).exists():
        evaluate_issue_event.delay(
            trigger=automation_trigger,
            project_id=str(project_id),
            issue_id=str(issue_id),
            actor_id=str(actor_id) if actor_id else None,
        )

    if slack_event:
        dispatch_slack_event.delay(
            event_type=slack_event,
            project_id=str(project_id),
            issue_id=str(issue_id),
            actor_id=str(actor_id) if actor_id else None,
            origin=origin,
        )
