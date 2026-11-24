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

import json
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.html import escape
from rest_framework import status
from rest_framework.exceptions import APIException

from plane.db.models import (
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    Project,
    State,
    Workflow,
    WorkflowState,
    WorkflowTransition,
)
from plane.utils.permissions.capabilities import (
    SYSTEM_ROLE_CAPABILITIES,
    get_user_project_role,
    has_capability,
)

logger = logging.getLogger("plane.workflow")

TRANSITION_CAPABILITY = "work_item.transition"

WORKFLOW_DENIED_FIELD = "workflow.transition_denied"
WORKFLOW_OVERRIDE_FIELD = "workflow.admin_override"
TRANSITION_ACTIVITY_FIELD = "state"
EPIC_FORCE_FIELD = "workflow.epic_force_complete"
WORKFLOW_AUDIT_FIELDS = (WORKFLOW_DENIED_FIELD, WORKFLOW_OVERRIDE_FIELD, EPIC_FORCE_FIELD)

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


def _audit_actor(user):
    """Never write an anonymous token into an admin audit row."""
    return user if user is not None and getattr(user, "is_authenticated", False) else None


def audit_workflow_denial(issue, user, error, *, to_state_id=None, source="api"):
    """Persist a denied transition attempt after the rejected write has rolled back.

    Denials are deliberately written as ``IssueActivity`` rows so they survive alongside
    the existing override audit without adding another audit model. The admin audit
    endpoint is the only place that exposes these rows.
    """
    details = getattr(error, "error_details", {}) or {}
    safe_details = {
        key: value
        for key, value in details.items()
        if key in ("issue_id", "from_state_id", "to_state_id", "transition_id", "required_roles")
    }
    parts = [f"code={getattr(error, 'code', 'transition_denied')}", f"source={source}"]
    if safe_details:
        parts.append(f"details={json.dumps(safe_details, sort_keys=True, default=str)[:900]}")
    try:
        IssueActivity.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=_audit_actor(user),
            verb="transition",
            field=WORKFLOW_DENIED_FIELD,
            old_value=str(issue.state_id) if issue.state_id else None,
            new_value=str(to_state_id) if to_state_id else None,
            comment="; ".join(parts),
            epoch=timezone.now().timestamp(),
        )
    except Exception:
        # Audit must never turn a clean 403 into a 500. The structured log still records it.
        logger.exception(
            "workflow denial audit failed actor=%s issue=%s code=%s",
            getattr(user, "id", None),
            getattr(issue, "id", None),
            getattr(error, "code", None),
        )


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


def _role_can_transition(role_key):
    """Capability check used by the admin-only 'test as role' preview."""
    return bool(role_key) and TRANSITION_CAPABILITY in SYSTEM_ROLE_CAPABILITIES.get(role_key, [])


def has_transition_capability(user, issue):
    """Viewers, guests and token users without the capability are denied early."""
    return has_capability(user, issue.workspace_id, TRANSITION_CAPABILITY, project=issue.project_id)


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------


def _required_roles(transition):
    """Roles that can perform the move, including the optional admin escape hatch."""
    roles = list(transition.allowed_roles or [])
    if transition.admin_override and "admin" not in roles:
        roles.append("admin")
    return roles


def _evaluate(transition, role_key, user, issue, *, capability=None, target_name=None):
    """Return (allowed, reason, override_used) for one transition and user."""
    if capability is None:
        capability = has_transition_capability(user, issue)
    if not capability:
        # Deliberately generic: a denied viewer/guest must not learn workflow rules.
        return False, "You cannot change the state of work items.", False

    roles = list(transition.allowed_roles or [])
    if not roles or role_key in roles:
        return True, None, False
    if transition.admin_override and _is_admin(role_key):
        return True, None, True
    return False, _roles_message(_required_roles(transition), target_name), False


def _roles_message(roles, target_name=None):
    names = [r.upper() if r == "qa" else r.capitalize() for r in roles]
    suffix = f" to {target_name}." if target_name else " to this state."
    if len(names) == 1:
        return f"{names[0]} can move this work item{suffix}"
    return f"{', '.join(names[:-1])} or {names[-1]} can move this work item{suffix}"


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


def get_allowed_transitions(issue, user, *, workflow=None, role_key=None):
    """What this user (or an admin testing a role) can do with this issue now.

    Returns ``{"workflow", "allowed": [...], "denied": [...]}``. The denied list is for
    admins only: other users should not see the whole workflow.
    """
    workflow = workflow or get_workflow_for_issue(issue)
    if workflow is None:
        return {"workflow": None, "allowed": [], "denied": []}

    preview = role_key is not None
    effective_role = role_key if preview else _role_key(user, issue)
    capability = _role_can_transition(effective_role) if preview else has_transition_capability(user, issue)
    allowed, denied = [], []
    for transition in _transitions_from(workflow, issue.state_id):
        ok, reason, _ = _evaluate(
            transition,
            effective_role,
            user,
            issue,
            capability=capability,
            target_name=transition.to_state.name,
        )
        entry = {
            "transition_id": str(transition.id),
            "to_state_id": str(transition.to_state_id),
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
            entry["required_roles"] = _required_roles(transition)
            denied.append(entry)
    show_denied = _is_admin(_role_key(user, issue)) or preview
    return {"workflow": workflow, "allowed": allowed, "denied": denied if show_denied else []}


def serialize_allowed_transitions(issue, user, *, workflow=None, role_key=None):
    """The exact PLN-013 response envelope (all identifiers are strings)."""
    result = get_allowed_transitions(issue, user, workflow=workflow, role_key=role_key)
    wf = result["workflow"]
    payload = {
        "issue_id": str(issue.id),
        "current_state_id": str(issue.state_id),
        "current_state_name": issue.state.name if issue.state else None,
        "workflow_id": str(wf.id) if wf else None,
        "transitions": result["allowed"],
    }
    if result["denied"]:
        payload["denied"] = result["denied"]
    return payload


def _check_epic_children(issue, to_state, *, force=False, comment=None, user=None):
    """An epic cannot be completed while it still has open children.

    The explicit force path is reserved for users with ``work_item.edit`` and
    requires a comment; it writes a durable audit row so the exception is visible.
    """
    if to_state.group != "completed" or issue.type is None or not issue.type.is_epic:
        return
    open_children = Issue.objects.filter(parent_id=issue.id).exclude(state__group__in=["completed", "cancelled"])
    count = open_children.count()
    if not count:
        return
    if force and comment and user is not None and has_capability(user, issue.workspace_id, "work_item.edit", project=issue.project_id):
        IssueActivity.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=_audit_actor(user),
            verb="transition",
            field=EPIC_FORCE_FIELD,
            old_value=str(issue.state_id) if issue.state_id else None,
            new_value=str(to_state.id),
            comment=f"force=true; count={count}; comment={comment}",
            epoch=timezone.now().timestamp(),
        )
        return
    raise WorkflowError(
        "epic_has_open_children",
        f"This epic still has {count} open work item{'s' if count != 1 else ''}.",
        issue_id=str(issue.id),
        count=count,
        sample_ids=[str(pk) for pk in open_children.values_list("id", flat=True)[:5]],
    )


def _check_wip_limit(issue, to_state):
    """Block a move only when the target column has a hard WIP limit reached."""
    workflow_state = (
        WorkflowState.objects.filter(workflow__project_id=issue.project_id, state_id=to_state.id)
        .order_by("sequence")
        .first()
    )
    if not workflow_state or workflow_state.wip_limit is None:
        return
    project = Project.objects.filter(pk=issue.project_id).only("board_wip_hard_limit").first()
    if not project or not project.board_wip_hard_limit:
        return
    occupied = (
        Issue.issue_objects.filter(project_id=issue.project_id, state_id=to_state.id)
        .exclude(pk=issue.pk)
        .count()
    )
    if occupied >= workflow_state.wip_limit:
        raise WorkflowError(
            "wip_limit_reached",
            f"'{to_state.name}' is at its WIP limit of {workflow_state.wip_limit}.",
            issue_id=str(issue.id),
            state_id=str(to_state.id),
            wip_limit=workflow_state.wip_limit,
            current_count=occupied,
        )


def validate_transition(
    issue, to_state, user, *, comment=None, source="api", expected_transition_id=None, force=False
):
    """Check a move. Returns ``(transition, override_used)``; ``(None, False)`` means ungoverned.

    Raises WorkflowError (400, 403, 409, 503) when the move is not allowed.
    """
    if to_state.id == issue.state_id:
        return None, False
    if not project_is_governed(issue.project_id):
        return None, False
    if not has_transition_capability(user, issue):
        # Generic message: capability denial is not a workflow rule disclosure.
        raise WorkflowError(
            "transition_forbidden",
            "You cannot change the state of work items.",
            status.HTTP_403_FORBIDDEN,
            issue_id=str(issue.id),
        )

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
        if expected_transition_id:
            # The menu offered an edge that no longer exists: make the client refetch.
            raise WorkflowError(
                "stale_workflow",
                "This workflow changed while the work item was open. Refresh and try again.",
                status.HTTP_409_CONFLICT,
                issue_id=str(issue.id),
                transition_id=str(expected_transition_id),
            )
        initial = WorkflowState.objects.filter(workflow=workflow, is_initial=True).first()
        if issue.state_id not in in_workflow and initial and initial.state_id == to_state.id:
            # Recovery path for work items left in a state outside the workflow.
            return None, False
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

    if expected_transition_id and str(transition.id) != str(expected_transition_id):
        raise WorkflowError(
            "stale_workflow",
            "This workflow changed while the work item was open. Refresh and try again.",
            status.HTTP_409_CONFLICT,
            issue_id=str(issue.id),
            transition_id=str(expected_transition_id),
        )

    _check_epic_children(issue, to_state, force=force, comment=comment, user=user)
    _check_wip_limit(issue, to_state)

    role_key = _role_key(user, issue)
    ok, reason, override_used = _evaluate(
        transition, role_key, user, issue, target_name=to_state.name
    )
    if not ok:
        logger.info(
            "workflow denied actor=%s issue=%s from=%s to=%s transition=%s reason=forbidden required_roles=%s",
            user.id,
            issue.id,
            issue.state_id,
            to_state.id,
            transition.id,
            _required_roles(transition),
        )
        raise WorkflowError(
            "transition_forbidden",
            reason,
            status.HTTP_403_FORBIDDEN,
            issue_id=str(issue.id),
            from_state_id=str(issue.state_id),
            to_state_id=str(to_state.id),
            required_roles=_required_roles(transition),
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
    return transition, override_used


# ---------------------------------------------------------------------------
# The one place that writes Issue.state
# ---------------------------------------------------------------------------


def _transition_activity_comment(source, transition=None, comment=None):
    """Machine-readable activity metadata, also consumed by webhook enrichment."""
    payload = {"source": source}
    if transition is not None:
        payload["workflow_id"] = str(transition.workflow_id)
        payload["transition_id"] = str(transition.id)
    if comment:
        payload["comment"] = comment
    return json.dumps(payload, sort_keys=True)


def transition_issue(
    issue_id, to_state_id, user, *, comment=None, source="api", expected_transition_id=None, force=False
):
    """Move a work item to another state, enforcing the workflow. Returns (issue, old_state_id).

    Validation, the state write, the durable activity row and any transition comment
    share one transaction. A denial is audited *after* that transaction rolls back,
    so callers that wrap this service in their own atomic block cannot lose the audit.
    """
    issue = Issue.objects.select_related("state", "type").get(pk=issue_id)
    try:
        with transaction.atomic():
            locked_issue = (
                Issue.objects.select_for_update(of=("self",)).select_related("state", "type").get(pk=issue_id)
            )
            to_state = State.all_state_objects.filter(pk=to_state_id, project_id=locked_issue.project_id).first()
            if to_state is None:
                raise WorkflowError(
                    "invalid_state", "That state does not belong to this project.", issue_id=str(issue.id)
                )

            old_state_id = locked_issue.state_id
            transition, override_used = validate_transition(
                locked_issue,
                to_state,
                user,
                comment=comment,
                source=source,
                expected_transition_id=expected_transition_id,
                force=force,
            )
            if to_state.id == old_state_id:
                return locked_issue, old_state_id

            # Issue.save() keeps completed_at in sync with the state group.
            locked_issue.state = to_state
            locked_issue.save(update_fields=["state", "updated_at"])

            IssueActivity.objects.create(
                issue=locked_issue,
                project_id=locked_issue.project_id,
                workspace_id=locked_issue.workspace_id,
                actor=_audit_actor(user),
                verb="transition",
                field=TRANSITION_ACTIVITY_FIELD,
                old_value=str(old_state_id),
                new_value=str(to_state.id),
                comment=_transition_activity_comment(source, transition, comment),
                epoch=timezone.now().timestamp(),
            )
            if (comment or "").strip():
                IssueComment.objects.create(
                    issue=locked_issue,
                    project_id=locked_issue.project_id,
                    workspace_id=locked_issue.workspace_id,
                    actor=_audit_actor(user),
                    comment_html=f"<p>{escape(comment.strip())}</p>",
                    comment_stripped=comment.strip(),
                )

            if override_used and transition is not None:
                # A durable, admin-only audit row complements the structured logger entry.
                IssueActivity.objects.create(
                    issue=locked_issue,
                    project_id=locked_issue.project_id,
                    workspace_id=locked_issue.workspace_id,
                    actor=_audit_actor(user),
                    verb="transition",
                    field=WORKFLOW_OVERRIDE_FIELD,
                    old_value=str(old_state_id),
                    new_value=str(to_state.id),
                    comment=f"transition={transition.id}; reason=admin_override",
                    epoch=timezone.now().timestamp(),
                )
            return locked_issue, old_state_id
    except WorkflowError as error:
        audit_workflow_denial(issue, user, error, to_state_id=to_state_id, source=source)
        raise


def reset_issue_state(issue_id, to_state_id, *, user=None, reason="type_change", source="api"):
    """System-initiated state reset (for example, a work item type change).

    This is deliberately separate from user transitions: no workflow edge is
    consulted. It still locks the row and writes the same durable activity shape so
    the state-write allowlist and webhook enrichment remain complete.
    """
    issue = Issue.objects.select_related("state", "type").get(pk=issue_id)
    with transaction.atomic():
        locked_issue = Issue.objects.select_for_update(of=("self",)).select_related("state", "type").get(pk=issue_id)
        to_state = State.all_state_objects.filter(pk=to_state_id, project_id=locked_issue.project_id).first()
        if to_state is None:
            raise WorkflowError(
                "invalid_state", "That state does not belong to this project.", issue_id=str(issue.id)
            )
        old_state_id = locked_issue.state_id
        if old_state_id == to_state.id:
            return locked_issue, old_state_id

        locked_issue.state = to_state
        locked_issue.save(update_fields=["state", "updated_at"])
        payload = {"source": source, "reason": reason}
        IssueActivity.objects.create(
            issue=locked_issue,
            project_id=locked_issue.project_id,
            workspace_id=locked_issue.workspace_id,
            actor=_audit_actor(user),
            verb="transition",
            field=TRANSITION_ACTIVITY_FIELD,
            old_value=str(old_state_id),
            new_value=str(to_state.id),
            comment=json.dumps(payload, sort_keys=True),
            epoch=timezone.now().timestamp(),
        )
        return locked_issue, old_state_id
