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
from plane.bgtasks.webhook_task import model_activity
from plane.db.models import (
    Issue,
    IssueActivity,
    Project,
    ProjectIssueType,
    Workflow,
    WorkflowState,
    WorkflowTransition,
)
from plane.utils.host import base_host
from plane.utils.permissions.capabilities import get_user_project_role
from plane.utils.workflow.service import (
    WorkflowImportError,
    WorkflowResetConflict,
    export_workflow,
    import_workflow,
    reset_workflow,
    seed_project_workflows,
)
from plane.utils.workflow.transition import (
    REQUIRED_FIELD_CHECKS,
    WORKFLOW_AUDIT_FIELDS,
    has_transition_capability,
    serialize_allowed_transitions,
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
                "wip_limit": ws.wip_limit,
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


class WorkflowStateEndpoint(BaseAPIView):
    """Per-state WIP settings for workflow-aware boards (PLN-009)."""

    @allow_permission([ROLE.ADMIN], capability="workflow.manage")
    def patch(self, request, slug, project_id, workflow_id, pk):
        workflow_state = (
            WorkflowState.objects.filter(
                pk=pk,
                workflow_id=workflow_id,
                workflow__project_id=project_id,
                workflow__project__workspace__slug=slug,
            )
            .select_related("state")
            .first()
        )
        if workflow_state is None:
            return _err("not_found", "Workflow state not found.", status.HTTP_404_NOT_FOUND)
        if "wip_limit" not in request.data:
            return _err("invalid_payload", "wip_limit is required.")
        value = request.data["wip_limit"]
        if value in ("", None):
            value = None
        else:
            try:
                value = int(value)
            except (TypeError, ValueError):
                return _err("invalid_wip_limit", "wip_limit must be a non-negative integer or null.")
            if value < 0:
                return _err("invalid_wip_limit", "wip_limit must be a non-negative integer or null.")
        workflow_state.wip_limit = value
        workflow_state.save(update_fields=["wip_limit", "updated_at"])
        return Response(
            {
                "id": workflow_state.id,
                "state_id": workflow_state.state_id,
                "name": workflow_state.state.name if workflow_state.state else None,
                "wip_limit": workflow_state.wip_limit,
            },
            status=status.HTTP_200_OK,
        )


class ProjectWorkflowCloneEndpoint(BaseAPIView):
    """Clone a workflow into an enabled type without sharing editable rows."""

    @allow_permission([ROLE.ADMIN], capability="workflow.manage")
    def post(self, request, slug, project_id, workflow_id):
        source = (
            Workflow.objects.filter(pk=workflow_id, project_id=project_id, project__workspace__slug=slug)
            .select_related("project", "issue_type")
            .first()
        )
        if source is None:
            return _err("not_found", "Workflow not found.", status.HTTP_404_NOT_FOUND)

        name = request.data.get("name")
        issue_type_id = request.data.get("issue_type_id")
        replace = request.data.get("replace", False)
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            return _err("invalid_name", "Enter a workflow name between 1 and 120 characters.")
        if not issue_type_id:
            return _err("type_required", "issue_type_id is required.")
        if not isinstance(replace, bool):
            return _err("invalid_replace", "replace must be a boolean.")

        project_type = (
            ProjectIssueType.objects.filter(
                project_id=project_id,
                issue_type_id=issue_type_id,
                issue_type__workspace__slug=slug,
                issue_type__is_active=True,
                is_enabled=True,
                deleted_at__isnull=True,
            )
            .select_related("issue_type")
            .first()
        )
        if project_type is None:
            return _err("type_not_enabled", "The target work item type is not enabled in this project.")

        target_default = Workflow.objects.filter(
            project_id=project_id,
            issue_type_id=project_type.issue_type_id,
            is_default=True,
            is_active=True,
            deleted_at__isnull=True,
        ).first()
        if target_default and not replace:
            return _err(
                "default_exists",
                "This work item type already has a default workflow. Confirm replacement to archive it first.",
                status.HTTP_409_CONFLICT,
                workflow_id=str(target_default.id),
            )
        if Workflow.objects.filter(project_id=project_id, name=name.strip(), deleted_at__isnull=True).exists():
            return _err("duplicate_name", "A workflow with this name already exists in the project.", status.HTTP_409_CONFLICT)

        source_states = list(
            WorkflowState.objects.filter(workflow=source).select_related("state").order_by("sequence", "id")
        )
        source_transitions = list(WorkflowTransition.objects.filter(workflow=source).order_by("id"))
        if not source_states:
            return _err("empty_workflow", "An empty workflow cannot be cloned.")

        try:
            with transaction.atomic():
                if target_default:
                    # Keep the previous workflow and its mappings for history and
                    # activity references; the replacement is an archived copy.
                    target_default.is_default = False
                    target_default.is_active = False
                    target_default.deleted_at = timezone.now()
                    target_default.save(update_fields=["is_default", "is_active", "deleted_at", "updated_at"])

                clone = Workflow.objects.create(
                    project_id=project_id,
                    issue_type_id=project_type.issue_type_id,
                    name=name.strip(),
                    description=source.description,
                    is_default=True,
                    is_active=True,
                )
                state_ids = {}
                for state_row in source_states:
                    new_state = WorkflowState.objects.create(
                        project_id=project_id,
                        workflow=clone,
                        state_id=state_row.state_id,
                        sequence=state_row.sequence,
                        is_initial=state_row.is_initial,
                        is_final=state_row.is_final,
                    )
                    state_ids[state_row.state_id] = new_state.state_id

                for transition in source_transitions:
                    WorkflowTransition.objects.create(
                        project_id=project_id,
                        workflow=clone,
                        from_state_id=state_ids[transition.from_state_id],
                        to_state_id=state_ids[transition.to_state_id],
                        allowed_roles=list(transition.allowed_roles or []),
                        requires_comment=transition.requires_comment,
                        required_fields=list(transition.required_fields or []),
                        admin_override=transition.admin_override,
                        is_active=transition.is_active,
                    )
        except IntegrityError:
            return _err("clone_conflict", "The workflow changed while it was being cloned. Refresh and try again.", status.HTTP_409_CONFLICT)

        return Response(serialize_workflow(clone, detail=True), status=status.HTTP_201_CREATED)


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
        try:
            plan = reset_workflow(
                workflow.project,
                workflow,
                force=str(request.query_params.get("force", "")).lower() == "true",
                user=request.user,
            )
        except WorkflowResetConflict as error:
            return _err(
                "items_in_removed_states",
                f"{error.count} work item(s) are in states that this reset would remove. Pass force=true to move them.",
                status.HTTP_409_CONFLICT,
                count=error.count,
                states=error.states,
            )
        return Response(plan, status=status.HTTP_200_OK)


class WorkflowHealthEndpoint(BaseAPIView):
    """Report problems that would block or confuse state changes (PLN-005/006)."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        issues = []

        def add(code, *, workflow=None, type_id=None, detail=""):
            issues.append(
                {
                    "code": code,
                    "type_id": str(type_id) if type_id else None,
                    "workflow_id": str(workflow.id) if workflow else None,
                    "detail": detail,
                }
            )

        project = (
            Project.objects.filter(pk=project_id, workspace__slug=slug).only("is_issue_type_enabled").first()
        )
        if project is not None and project.is_issue_type_enabled:
            enabled_types = ProjectIssueType.objects.filter(
                project_id=project_id, is_enabled=True, deleted_at__isnull=True
            ).select_related("issue_type")
            for project_type in enabled_types:
                defaults = Workflow.objects.filter(
                    project_id=project_id,
                    issue_type_id=project_type.issue_type_id,
                    is_active=True,
                    is_default=True,
                    deleted_at__isnull=True,
                ).count()
                if defaults == 0:
                    add(
                        "missing_default_workflow",
                        type_id=project_type.issue_type_id,
                        detail=f"'{project_type.issue_type.name}' has no active default workflow.",
                    )
                elif defaults > 1:
                    add(
                        "duplicate_default",
                        type_id=project_type.issue_type_id,
                        detail=f"'{project_type.issue_type.name}' has more than one active default workflow.",
                    )

        workflows = Workflow.objects.filter(
            project_id=project_id, is_active=True, deleted_at__isnull=True
        ).select_related("issue_type")
        for workflow in workflows:
            type_id = workflow.issue_type_id
            ws = list(WorkflowState.objects.filter(workflow=workflow, deleted_at__isnull=True).select_related("state"))
            state_ids = {w.state_id for w in ws}
            initial = [w for w in ws if w.is_initial]
            if len(initial) != 1:
                add(
                    "missing_initial",
                    workflow=workflow,
                    type_id=type_id,
                    detail=f"Expected exactly one initial state, found {len(initial)}.",
                )
            if not any(w.is_final for w in ws):
                add(
                    "missing_final",
                    workflow=workflow,
                    type_id=type_id,
                    detail="The workflow has no final state.",
                )

            edges = list(
                WorkflowTransition.objects.filter(workflow=workflow, deleted_at__isnull=True, is_active=True)
            )
            for edge in edges:
                if edge.from_state_id not in state_ids or edge.to_state_id not in state_ids:
                    add(
                        "transition_outside_workflow",
                        workflow=workflow,
                        type_id=type_id,
                        detail=f"Transition {edge.id} references a state outside the workflow.",
                    )

            if len(initial) == 1:
                reachable, frontier = {initial[0].state_id}, [initial[0].state_id]
                while frontier:
                    current = frontier.pop()
                    for edge in edges:
                        if edge.from_state_id == current and edge.to_state_id not in reachable:
                            reachable.add(edge.to_state_id)
                            frontier.append(edge.to_state_id)
                unreachable = [w for w in ws if w.state_id not in reachable]
                if unreachable:
                    add(
                        "unreachable_states",
                        workflow=workflow,
                        type_id=type_id,
                        detail=f"{len(unreachable)} state(s) cannot be reached from the initial state.",
                    )

            if type_id:
                stray = Issue.objects.filter(project_id=project_id, type_id=type_id)
                stray = stray.exclude(state_id__in=state_ids).count()
                if stray:
                    add(
                        "items_in_unmapped_states",
                        workflow=workflow,
                        type_id=type_id,
                        detail=f"{stray} work item(s) are in a state outside this workflow.",
                    )
        return Response({"healthy": not issues, "issues": issues}, status=status.HTTP_200_OK)


class WorkflowExportEndpoint(BaseAPIView):
    """Export a workflow as a strict, secret-free JSON document."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, workflow_id):
        workflow = (
            Workflow.objects.filter(pk=workflow_id, project_id=project_id, project__workspace__slug=slug)
            .select_related("issue_type")
            .first()
        )
        if workflow is None:
            return _err("not_found", "Workflow not found.", status.HTTP_404_NOT_FOUND)
        return Response(export_workflow(workflow), status=status.HTTP_200_OK)


class WorkflowImportEndpoint(BaseAPIView):
    """Create a workflow from an export; unknown fields are rejected."""

    @allow_permission([ROLE.ADMIN], capability="workflow.manage")
    def post(self, request, slug, project_id):
        project = Project.objects.filter(pk=project_id, workspace__slug=slug).first()
        if project is None:
            return _err("not_found", "Project not found.", status.HTTP_404_NOT_FOUND)
        try:
            workflow = import_workflow(project, request.data)
        except WorkflowImportError as error:
            return _err(error.code, str(error), error.details.pop("status", status.HTTP_400_BAD_REQUEST), **error.details)
        return Response(serialize_workflow(workflow, detail=True), status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Work item level
# ---------------------------------------------------------------------------


def _allowed_transitions_response(issue, user, *, workflow=None, role_key=None):
    if not has_transition_capability(user, issue):
        # Viewers, guests and capability-less tokens get a generic denial.
        return _err(
            "transition_forbidden",
            "You cannot change the state of work items.",
            status.HTTP_403_FORBIDDEN,
        )
    return Response(serialize_allowed_transitions(issue, user, workflow=workflow, role_key=role_key), status=status.HTTP_200_OK)


class WorkflowAuditEndpoint(BaseAPIView):
    """Project-admin-only view of denied transitions and admin overrides."""

    @allow_permission([ROLE.ADMIN])
    def get(self, request, slug, project_id):
        role = get_user_project_role(request.user, slug, project_id)
        if not role or role.key != "admin":
            return _err(
                "transition_forbidden",
                "You cannot view the workflow audit log.",
                status.HTTP_403_FORBIDDEN,
            )

        queryset = (
            IssueActivity.objects.filter(
                project_id=project_id,
                workspace__slug=slug,
                field__in=WORKFLOW_AUDIT_FIELDS,
            )
            .select_related("actor", "issue")
            .order_by("-created_at")
        )

        field = request.query_params.get("field")
        if field:
            if field not in WORKFLOW_AUDIT_FIELDS:
                return _err("invalid_field", "Unsupported workflow audit field.")
            queryset = queryset.filter(field=field)
        issue_id = request.query_params.get("issue_id")
        if issue_id:
            queryset = queryset.filter(issue_id=issue_id)
        actor_id = request.query_params.get("actor_id")
        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)
        created_at__gt = request.query_params.get("created_at__gt")
        if created_at__gt:
            queryset = queryset.filter(created_at__gt=created_at__gt)

        rows = [
            {
                "id": str(row.id),
                "issue_id": str(row.issue_id) if row.issue_id else None,
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "field": row.field,
                "verb": row.verb,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "comment": row.comment,
                "created_at": row.created_at,
            }
            for row in queryset
        ]
        return Response(rows, status=status.HTTP_200_OK)


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
        return _allowed_transitions_response(issue, request.user)


class WorkflowAllowedTransitionsEndpoint(BaseAPIView):
    """Admin preview endpoint: allowed moves for a workflow/issue and an optional role."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, workflow_id):
        workflow = Workflow.objects.filter(
            pk=workflow_id,
            project_id=project_id,
            project__workspace__slug=slug,
            is_active=True,
            deleted_at__isnull=True,
        ).first()
        if workflow is None:
            return _err("not_found", "Workflow not found.", status.HTTP_404_NOT_FOUND)

        issue_id = request.query_params.get("issue_id")
        if not issue_id:
            return _err("issue_id_required", "issue_id is required.")
        issue = (
            Issue.objects.filter(pk=issue_id, project_id=project_id, workspace__slug=slug)
            .select_related("state", "type")
            .first()
        )
        if issue is None:
            return _err("not_found", "Work item not found.", status.HTTP_404_NOT_FOUND)

        role_key = request.query_params.get("role")
        if role_key:
            # Role preview is an admin tool; it can reveal denied rule details.
            role = get_user_project_role(request.user, issue.workspace_id, project_id)
            if not role or role.key != "admin":
                return _err(
                    "transition_forbidden",
                    "You cannot preview transitions as another role.",
                    status.HTTP_403_FORBIDDEN,
                )
        return _allowed_transitions_response(issue, request.user, workflow=workflow, role_key=role_key)


class IssueTransitionEndpoint(BaseAPIView):
    """Move a work item to another state. The only endpoint that takes a comment with the move."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        to_state_id = request.data.get("to_state_id")
        if not to_state_id:
            return _err("state_required", "to_state_id is required.")
        comment = (request.data.get("comment") or "").strip()
        force = str(request.query_params.get("force", "")).lower() == "true"

        exists = Issue.objects.filter(pk=issue_id, project_id=project_id, workspace__slug=slug).exists()
        if not exists:
            return _err("not_found", "Work item not found.", status.HTTP_404_NOT_FOUND)

        # Do not wrap the service in an outer atomic block: a denial audit must survive
        # the rejected transition. The service owns the state-write transaction and
        # persists the activity/comment before notifications are dispatched.
        issue, old_state_id = transition_issue(
            issue_id,
            to_state_id,
            request.user,
            comment=comment,
            source="web",
            expected_transition_id=request.data.get("transition_id"),
            force=force,
        )

        if str(old_state_id) != str(issue.state_id):
            origin = base_host(request=request, is_app=True)
            issue_id_str = str(issue.id)
            state_id_str = str(issue.state_id)
            previous_state_id_str = str(old_state_id)
            actor_id = str(request.user.id)

            def dispatch():
                issue_activity.delay(
                    type="issue.activity.updated",
                    requested_data=json.dumps({"state_id": state_id_str}),
                    actor_id=actor_id,
                    issue_id=issue_id_str,
                    project_id=str(project_id),
                    current_instance=json.dumps({"state_id": previous_state_id_str}),
                    epoch=int(timezone.now().timestamp()),
                    notification=True,
                    origin=origin,
                )
                model_activity.delay(
                    model_name="issue",
                    model_id=issue_id_str,
                    requested_data={"state_id": state_id_str},
                    current_instance=json.dumps({"state_id": previous_state_id_str}),
                    actor_id=request.user.id,
                    slug=slug,
                    origin=origin,
                )

            transaction.on_commit(dispatch)
        return Response(
            {"issue_id": issue.id, "state_id": issue.state_id, "previous_state_id": old_state_id},
            status=status.HTTP_200_OK,
        )
