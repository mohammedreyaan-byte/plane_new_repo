# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Rule evaluation and execution for project automations."""

import json
from typing import Any, Dict, List

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from plane.db.models import (
    AutomationRule,
    AutomationRun,
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    Label,
    Notification,
    ProjectMember,
    State,
    User,
)
from plane.utils.workflow.transition import transition_issue


def infer_trigger(requested_data: Dict[str, Any], current_instance: Dict[str, Any] | None) -> str:
    if current_instance is None:
        return "created"
    changed = set(current_instance.keys()) & set(requested_data.keys())
    changed = {key for key in changed if current_instance.get(key) != requested_data.get(key)}
    if "assignee_ids" in changed:
        return "assigned"
    if "state" in changed:
        return "state_changed"
    if "priority" in changed:
        return "priority_changed"
    if "target_date" in changed or "start_date" in changed:
        return "due_date"
    return "updated"


def _field_values(issue: Issue, field: str) -> List[str]:
    if field == "state":
        return [issue.state.name if issue.state_id else ""]
    if field == "priority":
        return [issue.priority or ""]
    if field == "type":
        return [issue.type.name if issue.type_id else ""]
    if field == "assignee":
        return [user.display_name or user.email for user in issue.assignees.all()]
    if field == "label":
        return [label.name for label in issue.labels.all()]
    return []


def _condition_matches(issue: Issue, condition: Dict[str, Any]) -> bool:
    values = [value.lower() for value in _field_values(issue, condition.get("field", "")) if value]
    expected = str(condition.get("value", "")).strip().lower()
    operator = condition.get("operator", "is")
    if operator == "is":
        return expected in values
    if operator == "is not":
        return expected not in values
    if operator == "contains":
        return any(expected in value for value in values)
    return False


def _find_user(project, value: str):
    member_ids = ProjectMember.objects.filter(project_id=project.id, is_active=True).values_list("member_id", flat=True)
    return User.objects.filter(id__in=member_ids, email__iexact=value).first() or User.objects.filter(
        id__in=member_ids, display_name__iexact=value
    ).first()


def _apply_actions(rule: AutomationRule, issue: Issue, actor) -> List[str]:
    messages: List[str] = []
    project = issue.project
    for action in rule.actions:
        action_type = action.get("type")
        value = str(action.get("value", "")).strip()
        if action_type == "change_state":
            state = State.objects.filter(project_id=project.id, name__iexact=value).first()
            if not state:
                raise ValueError(f"State '{value}' does not exist in this project")
            transition_issue(issue.id, state.id, actor, source="automation")
            messages.append(f"State changed to {state.name}")
        elif action_type == "assign_user":
            user = _find_user(project, value)
            if not user:
                raise ValueError(f"User '{value}' is not an active project member")
            IssueAssignee.objects.get_or_create(
                issue=issue,
                assignee=user,
                project_id=project.id,
                workspace_id=project.workspace_id,
                defaults={"created_by_id": actor.id if actor else None},
            )
            messages.append(f"Assigned to {user.display_name or user.email}")
        elif action_type == "add_label":
            label = Label.objects.filter(project_id=project.id, name__iexact=value).first()
            if not label:
                raise ValueError(f"Label '{value}' does not exist in this project")
            IssueLabel.objects.get_or_create(
                issue=issue,
                label=label,
                project_id=project.id,
                workspace_id=project.workspace_id,
                defaults={"created_by_id": actor.id if actor else None},
            )
            messages.append(f"Label {label.name} added")
        elif action_type == "add_comment":
            IssueComment.objects.create(
                issue=issue,
                actor=actor,
                project_id=project.id,
                workspace_id=project.workspace_id,
                comment_stripped=value,
                comment_html=f"<p>{value}</p>",
                external_source="automation",
                external_id=str(rule.id),
            )
            messages.append("Comment added")
        elif action_type == "set_priority":
            priority = value.lower()
            if priority not in ("urgent", "high", "medium", "low"):
                raise ValueError("Priority must be urgent, high, medium or low")
            issue.priority = priority
            issue.save(update_fields=["priority"])
            messages.append(f"Priority set to {priority}")
        elif action_type == "send_notification":
            receiver = _find_user(project, value)
            if not receiver:
                raise ValueError(f"User '{value}' is not an active project member")
            Notification.objects.create(
                workspace_id=project.workspace_id,
                project_id=project.id,
                entity_identifier=issue.id,
                entity_name="issue",
                title=f"Automation: {rule.name}",
                message={"text": f"{issue.project.identifier}-{issue.sequence_id} matched automation {rule.name}"},
                sender="automation",
                triggered_by=actor,
                receiver=receiver,
            )
            messages.append(f"Notification sent to {receiver.display_name or receiver.email}")
    return messages


@shared_task(bind=True)
def evaluate_issue_event(
    self,
    trigger: str,
    project_id: str,
    issue_id: str,
    actor_id: str | None = None,
    rule_id: str | None = None,
    dry_run: bool = False,
) -> List[str]:
    """Evaluate active rules and persist a run for each matching rule."""

    issue = Issue.objects.select_related("project", "state", "type").get(pk=issue_id)
    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    rules = AutomationRule.objects.filter(project_id=project_id, is_active=True)
    if rule_id:
        rules = rules.filter(pk=rule_id)
    else:
        rules = rules.filter(trigger=trigger)
    run_ids: List[str] = []

    for rule in rules:
        if not rule_id and any(not _condition_matches(issue, condition) for condition in rule.conditions):
            continue
        try:
            if dry_run:
                messages = [f"Would {action.get('type', '').replace('_', ' ')}: {action.get('value', '')}" for action in rule.actions]
                status = AutomationRun.Status.SUCCESS
            else:
                with transaction.atomic():
                    messages = _apply_actions(rule, issue, actor)
                status = AutomationRun.Status.SUCCESS
            message = "; ".join(messages) or "Rule matched; no actions were configured"
        except Exception as exc:
            status = AutomationRun.Status.FAILED
            message = f"{type(exc).__name__}: {exc}"
        run = AutomationRun.objects.create(
            project_id=project_id,
            workspace_id=issue.workspace_id,
            rule=rule,
            work_item=issue,
            trigger=trigger,
            status=status,
            message=message,
            details={"actions": rule.actions, "conditions": rule.conditions, "dry_run": dry_run},
            dry_run=dry_run,
        )
        run_ids.append(str(run.id))
        AutomationRule.objects.filter(pk=rule.pk).update(last_evaluated_at=timezone.now())
    return run_ids
