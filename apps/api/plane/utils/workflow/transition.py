# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The workflow transition engine (PLN-005 / PLN-013).

Every code path that changes ``Issue.state`` must go through this module. The rules live
on the server only: the UI asks ``get_allowed_transitions`` and never decides by itself.

A project is "governed" when work item types are enabled on it and it has at least one
active workflow. Projects that are not governed keep the free state changes of Plane
1.4.2, so enabling the engine is an explicit per-project step.
"""

import logging

from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import APIException

from plane.db.models import Issue, IssueAssignee, Project, State, Workflow, WorkflowState, WorkflowTransition
from plane.utils.permissions.capabilities import get_user_project_role, has_capability

logger = logging.getLogger("plane.workflow")

TRANSITION_CAPABILITY = "work_item.transition"

# Field names accepted in WorkflowTransition.required_fields.
REQUIRED_FIELD_CHECKS = {
    "assignee": lambda issue: IssueAssignee.objects.filter(issue=issue).exists(),
    "estimate": lambda issue: issue.estimate_point_id is not None,
    "priority": lambda issue: issue.priority not in (None, "", "none"),
    "description": lambda issue: bool((issue.description_stripped or "").strip()),
    "due_date": lambda issue: issue.target_date is not None,
}


class WorkflowError(APIException):
    """An error with the machine readable contract described in PLN-013."""

    def __init__(self, code, message, http_status=status.HTTP_400_BAD_REQUEST, **details):
        self.status_code = http_status
        self.code = code
        self.message = message
        self.error_details = details
        super().__init__(detail={"error": {"code": code, "message": message, "details": details}})


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def project_is_governed(project_id):
    """True when state changes in this project must follow a workflow."""
    return (
        Project.objects.filter(pk=project_id, is_issue_type_enabled=True).exists()
        and Workflow.objects.filter(project_id=project_id, is_active=True).exists()
    )


def get_workflow_for_issue(issue):
    """Type specific default workflow first, then the project wide default."""
    base = Workflow.objects.filter(project_id=issue.project_id, is_active=True, is_default=True)
    if issue.type_id:
        workflow = base.filter(issue_type_id=issue.type_id).first()
        if workflow:
            return workflow
    return base.filter(issue_type__isnull=True).first()


def _role_key(user, issue):
    role = get_user_project_role(user, issue.workspace_id, issue.project_id)
    return role.key if role else None


def _is_admin(role_key):
    return role_key == "admin"


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------


def _evaluate(transition, role_key, user, issue):
    """Return (allowed, reason, override_used) for one transition and user."""
    if not has_capability(user, issue.workspace_id, TRANSITION_CAPABILITY, project=issue.project_id):
        return False, "You cannot change the state of work items.", False

    roles = list(transition.allowed_roles or [])
    if not roles or role_key in roles:
        return True, None, False
    if transition.admin_override and _is_admin(role_key):
        return True, None, True
    return False, _roles_message(roles), False


def _roles_message(roles):
    names = [r.upper() if r == "qa" else r.capitalize() for r in roles]
    if len(names) == 1:
        return f"Only {names[0]} can make this move."
    return f"Requires one of: {', '.join(names)}."


def _missing_fields(transition, issue):
    missing = []
    for field in transition.required_fields or []:
        check = REQUIRED_FIELD_CHECKS.get(field)
        if check is not None and not check(issue):
            missing.append(field)
    return missing


def _transitions_from(workflow, from_state_id):
    return (
        WorkflowTransition.objects.filter(workflow=workflow, from_state_id=from_state_id, is_active=True)
        .select_related("to_state")
        .order_by("to_state__sequence")
    )


def get_allowed_transitions(issue, user):
    """What this user can do with this issue now.

    Returns ``{"workflow", "allowed": [...], "denied": [...]}``. The denied list is for
    admins only: other users should not see the whole workflow.
    """
    workflow = get_workflow_for_issue(issue)
    if workflow is None:
        return {"workflow": None, "allowed": [], "denied": []}

    role_key = _role_key(user, issue)
    allowed, denied = [], []
    for transition in _transitions_from(workflow, issue.state_id):
        ok, reason, _ = _evaluate(transition, role_key, user, issue)
        entry = {
            "transition_id": transition.id,
            "to_state_id": transition.to_state_id,
            "to_state_name": transition.to_state.name,
            "to_state_group": transition.to_state.group,
            "requires_comment": transition.requires_comment,
            "required_fields": list(transition.required_fields or []),
            "allowed": ok,
            "reason": reason,
        }
        if ok:
            allowed.append(entry)
        else:
            entry["required_roles"] = list(transition.allowed_roles or [])
            denied.append(entry)
    return {"workflow": workflow, "allowed": allowed, "denied": denied if _is_admin(role_key) else []}


def _check_epic_children(issue, to_state):
    """An epic cannot be completed while it still has open children."""
    if to_state.group != "completed" or issue.type is None or not issue.type.is_epic:
        return
    open_children = Issue.objects.filter(parent_id=issue.id).exclude(state__group__in=["completed", "cancelled"])
    count = open_children.count()
    if count:
        raise WorkflowError(
            "epic_has_open_children",
            f"This epic still has {count} open work item{'s' if count != 1 else ''}.",
            issue_id=str(issue.id),
            count=count,
            sample_ids=[str(pk) for pk in open_children.values_list("id", flat=True)[:5]],
        )


def validate_transition(issue, to_state, user, *, comment=None, source="api"):
    """Check a move. Returns the transition used, or None if the project is not governed.

    Raises WorkflowError (400, 403, 503) when the move is not allowed.
    """
    if to_state.id == issue.state_id:
        return None
    if not project_is_governed(issue.project_id):
        return None

    workflow = get_workflow_for_issue(issue)
    if workflow is None:
        raise WorkflowError(
            "workflow_unavailable",
            "This work item type has no workflow, so its state cannot be changed right now.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            issue_id=str(issue.id),
        )

    in_workflow = set(WorkflowState.objects.filter(workflow=workflow).values_list("state_id", flat=True))
    if to_state.id not in in_workflow:
        raise WorkflowError(
            "state_not_in_workflow",
            f"'{to_state.name}' is not part of the {workflow.name}.",
            issue_id=str(issue.id),
            to_state_id=str(to_state.id),
        )

    transition = WorkflowTransition.objects.filter(
        workflow=workflow, from_state_id=issue.state_id, to_state_id=to_state.id, is_active=True
    ).first()

    if transition is None:
        initial = WorkflowState.objects.filter(workflow=workflow, is_initial=True).first()
        if issue.state_id not in in_workflow and initial and initial.state_id == to_state.id:
            # Recovery path for work items left in a state outside the workflow.
            return None
        if issue.state_id not in in_workflow:
            raise WorkflowError(
                "state_not_in_workflow",
                "This work item is in a state that is not part of its workflow. "
                "Move it to the first state of the workflow.",
                issue_id=str(issue.id),
            )
        raise WorkflowError(
            "transition_not_allowed",
            f"A work item cannot move from its current state to '{to_state.name}'.",
            issue_id=str(issue.id),
            from_state_id=str(issue.state_id),
            to_state_id=str(to_state.id),
            allowed_transitions=[
                {"to_state_id": str(t["to_state_id"]), "to_state_name": t["to_state_name"]}
                for t in get_allowed_transitions(issue, user)["allowed"]
            ],
        )

    _check_epic_children(issue, to_state)

    role_key = _role_key(user, issue)
    ok, reason, override_used = _evaluate(transition, role_key, user, issue)
    if not ok:
        logger.info(
            "workflow denied actor=%s issue=%s from=%s to=%s reason=%s",
            user.id,
            issue.id,
            issue.state_id,
            to_state.id,
            "forbidden",
        )
        raise WorkflowError(
            "transition_forbidden",
            reason,
            status.HTTP_403_FORBIDDEN,
            issue_id=str(issue.id),
            from_state_id=str(issue.state_id),
            to_state_id=str(to_state.id),
            required_roles=list(transition.allowed_roles or []),
            allowed_transitions=[
                {"to_state_id": str(t["to_state_id"]), "to_state_name": t["to_state_name"]}
                for t in get_allowed_transitions(issue, user)["allowed"]
            ],
        )

    if transition.requires_comment and not (comment or "").strip():
        raise WorkflowError(
            "comment_required",
            "A comment is required for this move. Use the transition endpoint and include a comment.",
            issue_id=str(issue.id),
            to_state_id=str(to_state.id),
        )

    missing = _missing_fields(transition, issue)
    if missing:
        raise WorkflowError(
            "fields_required",
            f"Fill in {', '.join(missing)} before making this move.",
            issue_id=str(issue.id),
            to_state_id=str(to_state.id),
            missing_fields=missing,
        )

    if override_used:
        logger.info(
            "workflow admin_override actor=%s issue=%s from=%s to=%s transition=%s",
            user.id,
            issue.id,
            issue.state_id,
            to_state.id,
            transition.id,
        )
    return transition


# ---------------------------------------------------------------------------
# The one place that writes Issue.state
# ---------------------------------------------------------------------------


@transaction.atomic
def transition_issue(issue_id, to_state_id, user, *, comment=None, source="api"):
    """Move a work item to another state, enforcing the workflow. Returns (issue, old_state_id)."""
    issue = Issue.objects.select_for_update().get(pk=issue_id)
    to_state = State.all_state_objects.filter(pk=to_state_id, project_id=issue.project_id).first()
    if to_state is None:
        raise WorkflowError("invalid_state", "That state does not belong to this project.", issue_id=str(issue.id))

    old_state_id = issue.state_id
    validate_transition(issue, to_state, user, comment=comment, source=source)
    if to_state.id == old_state_id:
        return issue, old_state_id

    # Issue.save() keeps completed_at in sync with the state group.
    issue.state = to_state
    issue.save(update_fields=["state", "updated_at"])
    return issue, old_state_id
