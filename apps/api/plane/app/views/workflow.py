# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workflow engine endpoints (PLN-005 / PLN-006 / PLN-013).

Reading workflows is open to project members. Changing them needs the ``workflow.manage``
capability (project or workspace admin). Moving a work item always goes through
``plane.utils.workflow.transition``.
"""

# Python imports
import json

# Django imports
from django.db import IntegrityError, transaction
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .base import BaseAPIView
from plane.app.permissions import ROLE, allow_permission
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import (
    Issue,
    IssueComment,
    Workflow,
    WorkflowState,
    WorkflowTransition,
)
from plane.utils.host import base_host
from plane.utils.workflow.service import seed_project_workflows
from plane.utils.workflow.transition import (
    REQUIRED_FIELD_CHECKS,
    get_allowed_transitions,
    transition_issue,
)


def _err(code, message, http_status=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": {"code": code, "message": message, "details": extra}}, status=http_status)


def serialize_transition(t):
    return {
        "id": t.id,
        "from_state_id": t.from_state_id,
        "to_state_id": t.to_state_id,
        "allowed_roles": list(t.allowed_roles or []),
        "requires_comment": t.requires_comment,
        "required_fields": list(t.required_fields or []),
        "admin_override": t.admin_override,
        "is_active": t.is_active,
    }


def serialize_workflow(workflow, detail=False):
    data = {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "issue_type": workflow.issue_type_id,
        "issue_type_key": workflow.issue_type.key if workflow.issue_type else None,
        "is_default": workflow.is_default,
        "is_active": workflow.is_active,
    }
    if detail:
        states = WorkflowState.objects.filter(workflow=workflow).select_related("state").order_by("sequence")
        data["states"] = [
            {
                "id": ws.id,
                "state_id": ws.state_id,
                "name": ws.state.name,
                "group": ws.state.group,
                "sequence": ws.sequence,
                "is_initial": ws.is_initial,
                "is_final": ws.is_final,
            }
            for ws in states
        ]
        data["transitions"] = [serialize_transition(t) for t in WorkflowTransition.objects.filter(workflow=workflow)]
    return data


class ProjectWorkflowEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        workflows = Workflow.objects.filter(project_id=project_id, project__workspace__slug=slug).select_related(
            "issue_type"
        )
        return Response([serialize_workflow(w) for w in workflows], status=status.HTTP_200_OK)


class ProjectWorkflowDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, workflow_id):
        workflow = (
            Workflow.objects.filter(pk=workflow_id, project_id=project_id, project__workspace__slug=slug)
            .select_related("issue_type")
            .first()
        )
        if workflow is None:
            return _err("not_found", "Workflow not found.", status.HTTP_404_NOT_FOUND)
        return Response(serialize_workflow(workflow, detail=True), status=status.HTTP_200_OK)


def _validate_transition_payload(data, workflow):
    roles = data.get("allowed_roles")
    if roles is not None and (not isinstance(roles, list) or not all(isinstance(r, str) for r in roles)):
        return "allowed_roles must be a list of role keys."
    fields = data.get("required_fields")
    if fields is not None:
        if not isinstance(fields, list):
            return "required_fields must be a list."
        unknown = [f for f in fields if f not in REQUIRED_FIELD_CHECKS]
        if unknown:
            return (
                f"Unknown required fields: {', '.join(unknown)}. Allowed: {', '.join(sorted(REQUIRED_FIELD_CHECKS))}."
            )
    return None


class WorkflowTransitionEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], capability="workflow.manage")
    def post(self, request, slug, project_id, workflow_id):
        workflow = Workflow.objects.filter(pk=workflow_id, project_id=project_id, project__workspace__slug=slug).first()
        if workflow is None:
            return _err("not_found", "Workflow not found.", status.HTTP_404_NOT_FOUND)

        from_id, to_id = request.data.get("from_state_id"), request.data.get("to_state_id")
        if not from_id or not to_id:
            return _err("state_required", "from_state_id and to_state_id are required.")
        if str(from_id) == str(to_id):
            return _err("self_transition", "A state cannot move to itself.")
        mapped = set(str(s) for s in WorkflowState.objects.filter(workflow=workflow).values_list("state_id", flat=True))
        if str(from_id) not in mapped or str(to_id) not in mapped:
            return _err("state_not_in_workflow", "Both states must be part of this workflow.")
        message = _validate_transition_payload(request.data, workflow)
        if message:
            return _err("invalid_payload", message)
        if WorkflowTransition.objects.filter(workflow=workflow, from_state_id=from_id, to_state_id=to_id).exists():
            return _err("duplicate_transition", "This transition already exists.", status.HTTP_409_CONFLICT)

        try:
            transition = WorkflowTransition.objects.create(
                workflow=workflow,
                project_id=project_id,
                from_state_id=from_id,
                to_state_id=to_id,
                allowed_roles=request.data.get("allowed_roles", []),
                requires_comment=bool(request.data.get("requires_comment", False)),
                required_fields=request.data.get("required_fields", []),
                admin_override=bool(request.data.get("admin_override", True)),
            )
        except IntegrityError:
            return _err("invalid_payload", "The transition could not be created.")
        return Response(serialize_transition(transition), status=status.HTTP_201_CREATED)


class WorkflowTransitionDetailEndpoint(BaseAPIView):
    def _get(self, slug, project_id, workflow_id, pk):
        return WorkflowTransition.objects.filter(
            pk=pk, workflow_id=workflow_id, project_id=project_id, project__workspace__slug=slug
        ).first()

    @allow_permission([ROLE.ADMIN], capability="workflow.manage")
    def patch(self, request, slug, project_id, workflow_id, pk):
        transition = self._get(slug, project_id, workflow_id, pk)
        if transition is None:
            return _err("not_found", "Transition not found.", status.HTTP_404_NOT_FOUND)
        message = _validate_transition_payload(request.data, transition.workflow)
        if message:
            return _err("invalid_payload", message)
        for field in ("allowed_roles", "requires_comment", "required_fields", "admin_override", "is_active"):
            if field in request.data:
                setattr(transition, field, request.data[field])
        transition.save()
        return Response(serialize_transition(transition), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], capability="workflow.manage")
    def delete(self, request, slug, project_id, workflow_id, pk):
        transition = self._get(slug, project_id, workflow_id, pk)
        if transition is None:
            return _err("not_found", "Transition not found.", status.HTTP_404_NOT_FOUND)
        transition.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkflowResetEndpoint(BaseAPIView):
    """Restore the built-in matrix for a system workflow (bug, task, story, epic)."""

    @allow_permission([ROLE.ADMIN], capability="workflow.manage")
    def post(self, request, slug, project_id, workflow_id):
        workflow = (
            Workflow.objects.filter(pk=workflow_id, project_id=project_id, project__workspace__slug=slug)
            .select_related("issue_type", "project")
            .first()
        )
        if workflow is None:
            return _err("not_found", "Workflow not found.", status.HTTP_404_NOT_FOUND)
        if workflow.issue_type is None or workflow.issue_type.key not in ("bug", "task", "story", "epic"):
            return _err("not_resettable", "Only the built-in workflows can be reset.")
        summary = seed_project_workflows(workflow.project, type_keys=[workflow.issue_type.key], reset=True)
        return Response(summary[workflow.issue_type.key], status=status.HTTP_200_OK)


class WorkflowHealthEndpoint(BaseAPIView):
    """Report problems that would block or confuse state changes."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        issues = []
        workflows = Workflow.objects.filter(project_id=project_id, is_active=True).select_related("issue_type")
        for workflow in workflows:
            ws = list(WorkflowState.objects.filter(workflow=workflow))
            state_ids = {w.state_id for w in ws}
            initial = [w for w in ws if w.is_initial]
            if len(initial) != 1:
                issues.append(
                    {
                        "code": "initial_state",
                        "workflow_id": str(workflow.id),
                        "detail": f"Expected exactly one initial state, found {len(initial)}.",
                    }
                )
            if not any(w.is_final for w in ws):
                issues.append(
                    {
                        "code": "missing_final",
                        "workflow_id": str(workflow.id),
                        "detail": "The workflow has no final state.",
                    }
                )

            edges = list(WorkflowTransition.objects.filter(workflow=workflow, is_active=True))
            for e in edges:
                if e.from_state_id not in state_ids or e.to_state_id not in state_ids:
                    issues.append(
                        {
                            "code": "transition_outside_workflow",
                            "workflow_id": str(workflow.id),
                            "detail": f"Transition {e.id} references a state outside the workflow.",
                        }
                    )

            if len(initial) == 1:
                reachable, frontier = {initial[0].state_id}, [initial[0].state_id]
                while frontier:
                    current = frontier.pop()
                    for e in edges:
                        if e.from_state_id == current and e.to_state_id not in reachable:
                            reachable.add(e.to_state_id)
                            frontier.append(e.to_state_id)
                for w in ws:
                    if w.state_id not in reachable:
                        issues.append(
                            {
                                "code": "unreachable_state",
                                "workflow_id": str(workflow.id),
                                "detail": f"State {w.state_id} cannot be reached from the initial state.",
                            }
                        )

            if workflow.issue_type_id:
                stray = (
                    Issue.objects.filter(project_id=project_id, type_id=workflow.issue_type_id)
                    .exclude(state_id__in=state_ids)
                    .count()
                )
                if stray:
                    issues.append(
                        {
                            "code": "items_in_unmapped_states",
                            "workflow_id": str(workflow.id),
                            "detail": f"{stray} work items are in a state outside this workflow.",
                        }
                    )
        return Response({"healthy": not issues, "issues": issues}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Work item level
# ---------------------------------------------------------------------------


class IssueAllowedTransitionsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        issue = (
            Issue.objects.filter(pk=issue_id, project_id=project_id, workspace__slug=slug)
            .select_related("state", "type")
            .first()
        )
        if issue is None:
            return _err("not_found", "Work item not found.", status.HTTP_404_NOT_FOUND)

        result = get_allowed_transitions(issue, request.user)
        workflow = result["workflow"]

        def shape(entries):
            return [{**e, "transition_id": str(e["transition_id"])} for e in entries]

        payload = {
            "issue_id": issue.id,
            "current_state_id": issue.state_id,
            "current_state_name": issue.state.name if issue.state else None,
            "workflow_id": workflow.id if workflow else None,
            "transitions": result["allowed"],
        }
        if result["denied"]:
            payload["denied"] = result["denied"]
        return Response(payload, status=status.HTTP_200_OK)


class IssueTransitionEndpoint(BaseAPIView):
    """Move a work item to another state. The only endpoint that takes a comment with the move."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        to_state_id = request.data.get("to_state_id")
        if not to_state_id:
            return _err("state_required", "to_state_id is required.")
        comment = (request.data.get("comment") or "").strip()

        exists = Issue.objects.filter(pk=issue_id, project_id=project_id, workspace__slug=slug).exists()
        if not exists:
            return _err("not_found", "Work item not found.", status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            issue, old_state_id = transition_issue(issue_id, to_state_id, request.user, comment=comment, source="web")
            if comment and str(old_state_id) != str(issue.state_id):
                IssueComment.objects.create(
                    issue=issue,
                    project_id=project_id,
                    workspace_id=issue.workspace_id,
                    actor=request.user,
                    comment_html=f"<p>{comment}</p>",
                    comment_stripped=comment,
                )

        if str(old_state_id) != str(issue.state_id):
            issue_activity.delay(
                type="issue.activity.updated",
                requested_data=json.dumps({"state_id": str(issue.state_id)}),
                actor_id=str(request.user.id),
                issue_id=str(issue.id),
                project_id=str(project_id),
                current_instance=json.dumps({"state_id": str(old_state_id)}),
                epoch=int(timezone.now().timestamp()),
                notification=True,
                origin=base_host(request=request, is_app=True),
            )
        return Response(
            {"issue_id": issue.id, "state_id": issue.state_id, "previous_state_id": old_state_id},
            status=status.HTTP_200_OK,
        )
