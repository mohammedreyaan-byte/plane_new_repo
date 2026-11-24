# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from itertools import groupby
from collections import defaultdict
from uuid import UUID

# Django imports
from django.db import models, transaction
from django.db.models import Q
from django.db.utils import IntegrityError

# Third party imports
from rest_framework.response import Response
from rest_framework import status

# Module imports
from .. import BaseViewSet, BaseAPIView
from plane.app.serializers import StateSerializer
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import (
    Issue,
    Project,
    ProjectIssueType,
    State,
    Workflow,
    WorkflowState,
    WorkflowTransition,
)
from plane.utils.cache import invalidate_cache


def workflow_usage(states, project_id):
    """Map state id to the active workflows that map it (for the States settings table)."""
    usage = {}
    state_ids = [state.get("id") if isinstance(state, dict) else state.id for state in states]
    rows = (
        WorkflowState.objects.filter(
            project_id=project_id,
            state_id__in=state_ids,
            deleted_at__isnull=True,
            workflow__deleted_at__isnull=True,
            workflow__is_active=True,
        )
        .select_related("workflow", "workflow__issue_type")
        .order_by("workflow__name")
    )
    for row in rows:
        usage.setdefault(str(row.state_id), []).append(
            {
                "id": str(row.workflow_id),
                "name": row.workflow.name,
                "type": row.workflow.issue_type.key if row.workflow.issue_type else "default",
            }
        )
    return usage


def _validation_code(errors, fields=("name", "color")):
    """Read an optional ``{"code", "message"}`` validation payload from DRF errors."""
    for field in fields:
        value = errors.get(field)
        if isinstance(value, dict):
            code, message = value.get("code"), value.get("message")
            if code:
                return code, message
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], dict):
            code, message = value[0].get("code"), value[0].get("message")
            if code:
                return code, message
    return None, None


class StateViewSet(BaseViewSet):
    serializer_class = StateSerializer
    model = State

    def get_queryset(self):
        return self.filter_queryset(
            super()
            .get_queryset()
            .filter(workspace__slug=self.kwargs.get("slug"))
            .filter(project_id=self.kwargs.get("project_id"))
            .filter(
                project__project_projectmember__member=self.request.user,
                project__project_projectmember__is_active=True,
                project__archived_at__isnull=True,
            )
            .filter(is_triage=False)
            .select_related("project")
            .select_related("workspace")
            .distinct()
        )

    def _error(self, code, message, http_status=status.HTTP_400_BAD_REQUEST, **details):
        return Response({"error": {"code": code, "message": message, "details": details}}, status=http_status)

    @invalidate_cache(path="workspaces/:slug/states/", url_params=True, user=False)
    @allow_permission([ROLE.ADMIN])
    def create(self, request, slug, project_id):
        data = request.data.copy()
        workflow_ids = data.pop("workflow_ids", []) or []
        if not isinstance(workflow_ids, list):
            return self._error("invalid_workflow_ids", "workflow_ids must be a list.")
        workflows = []
        if workflow_ids:
            workflows = list(
                Workflow.objects.filter(
                    pk__in=workflow_ids, project_id=project_id, is_active=True, deleted_at__isnull=True
                )
            )
            if len(workflows) != len(set(str(w) for w in workflow_ids)):
                return self._error("invalid_workflow_ids", "Every workflow must belong to this project.")
        try:
            serializer = StateSerializer(data=data, context={"project_id": project_id})
            if not serializer.is_valid():
                errors = serializer.errors
                error_code, message = _validation_code(errors)
                if error_code:
                    return self._error(error_code, message or error_code)
                return Response(errors, status=status.HTTP_400_BAD_REQUEST)
            state = serializer.save(project_id=project_id)
            if workflows:
                for workflow in workflows:
                    next_sequence = (
                        WorkflowState.objects.filter(workflow=workflow).aggregate(models.Max("sequence"))[
                            "sequence__max"
                        ]
                        or 0
                    ) + 1000
                    WorkflowState.objects.get_or_create(
                        workflow=workflow,
                        state=state,
                        project_id=project_id,
                        defaults={"sequence": next_sequence},
                    )
            payload = StateSerializer(state, context={"project_id": project_id}).data
            payload["used_by_workflows"] = workflow_usage([state], project_id).get(str(state.id), [])
            return Response(payload, status=status.HTTP_200_OK)
        except IntegrityError:
            return self._error("duplicate_state_name", "A state with this name already exists.")

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def partial_update(self, request, slug, project_id, pk):
        state = State.objects.filter(pk=pk, project_id=project_id, workspace__slug=slug).first()
        if state is None:
            return self._error("not_found", "State not found.", status.HTTP_404_NOT_FOUND)
        if "group" in request.data and request.data["group"] != state.group:
            usages = WorkflowState.objects.filter(state=state, deleted_at__isnull=True).select_related("workflow")
            if usages.exists():
                transitions = WorkflowTransition.objects.filter(
                    workflow__in=[u.workflow_id for u in usages],
                ).filter(Q(from_state=state) | Q(to_state=state))
                return self._error(
                    "group_change_affects_workflow",
                    "This state is used by workflows. Review the affected transitions before changing its group.",
                    status.HTTP_409_CONFLICT,
                    workflows=[str(u.workflow_id) for u in usages],
                    transitions=[str(t.id) for t in transitions],
                )
        try:
            serializer = StateSerializer(state, data=request.data, partial=True, context={"project_id": project_id})
            if not serializer.is_valid():
                errors = serializer.errors
                error_code, message = _validation_code(errors)
                if error_code:
                    return self._error(error_code, message or error_code)
                return Response(errors, status=status.HTTP_400_BAD_REQUEST)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        except IntegrityError:
            return self._error("duplicate_state_name", "A state with this name already exists.")

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def list(self, request, slug, project_id):
        state_queryset = self.get_queryset()
        type_id = request.query_params.get("type_id")
        workflow_state_rows = []
        workflow_type_filter_applied = False

        # Keep the legacy state list unchanged unless a type filter is explicitly
        # requested for a project that has work item types enabled.
        if type_id:
            try:
                type_id = UUID(type_id)
            except (ValueError, TypeError, AttributeError):
                return Response({"error": "Invalid type_id"}, status=status.HTTP_400_BAD_REQUEST)

            project = (
                Project.objects.filter(pk=project_id, workspace__slug=slug)
                .only("id", "is_issue_type_enabled")
                .first()
            )
            if project and project.is_issue_type_enabled:
                workflow_type_filter_applied = True
                project_type = ProjectIssueType.objects.filter(
                    project_id=project_id,
                    issue_type_id=type_id,
                    issue_type__workspace__slug=slug,
                    issue_type__is_active=True,
                    is_enabled=True,
                    deleted_at__isnull=True,
                ).first()
                if project_type is None:
                    return Response(
                        {"error": "Work item type is not enabled in this project."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                workflow = Workflow.objects.filter(
                    project_id=project_id,
                    issue_type_id=type_id,
                    is_active=True,
                    is_default=True,
                    deleted_at__isnull=True,
                ).first()
                if workflow is None:
                    state_queryset = state_queryset.none()
                    workflow_state_rows = []
                else:
                    workflow_state_rows = list(
                        WorkflowState.objects.filter(
                            workflow_id=workflow.id, deleted_at__isnull=True
                        ).order_by("sequence", "created_at")
                    )
                    mapped_state_ids = [row.state_id for row in workflow_state_rows]
                    state_queryset = state_queryset.filter(pk__in=mapped_state_ids)

        states = StateSerializer(state_queryset, many=True).data
        usage_by_state = workflow_usage(states, project_id)
        for state in states:
            usages = usage_by_state.get(str(state["id"]), [])
            state["used_by_workflows"] = usages
            # Additive compatibility field for the States settings table. Prefer the
            # Bug workflow when a shared state appears in several workflows so the
            # value is stable, then fall back to the first workflow by name.
            primary = next((usage for usage in usages if usage.get("type") == "bug"), None)
            state["workflow_id"] = (primary or usages[0])["id"] if usages else None

        # Workflow ordering and boundary metadata are additive to the legacy
        # state representation and are only returned for typed requests.
        if workflow_type_filter_applied:
            state_by_id = {str(state["id"]): state for state in states}
            workflow_states = []
            for row in workflow_state_rows:
                state = state_by_id.get(str(row.state_id))
                if state is not None:
                    state.update(
                        {
                            "workflow_id": str(workflow.id),
                            "is_initial": row.is_initial,
                            "is_final": row.is_final,
                        }
                    )
                    workflow_states.append(state)
            states = workflow_states

        grouped_states = defaultdict(list)
        for state in states:
            grouped_states[state["group"]].append(state)

        for group, group_states in grouped_states.items():
            count = len(group_states)

            for index, state in enumerate(group_states, start=1):
                state["order"] = index / count

        grouped = request.GET.get("grouped", False)

        if grouped == "true":
            state_dict = {}
            for key, value in groupby(
                sorted(states, key=lambda state: state["group"]),
                lambda state: state.get("group"),
            ):
                state_dict[str(key)] = list(value)
            return Response(state_dict, status=status.HTTP_200_OK)

        return Response(states, status=status.HTTP_200_OK)

    @invalidate_cache(path="workspaces/:slug/states/", url_params=True, user=False)
    @allow_permission([ROLE.ADMIN])
    def mark_as_default(self, request, slug, project_id, pk):
        state = State.objects.filter(workspace__slug=slug, project_id=project_id, pk=pk).first()
        if state is None:
            return self._error("not_found", "State not found.", status.HTTP_404_NOT_FOUND)

        # The default must match the initial state of each default workflow. Changing it
        # is allowed only after the caller has seen which workflows will be affected.
        default_workflows = Workflow.objects.filter(
            project_id=project_id,
            is_default=True,
            is_active=True,
            deleted_at__isnull=True,
        ).select_related("issue_type")
        affected = []
        for workflow in default_workflows:
            initial = (
                WorkflowState.objects.filter(workflow=workflow, is_initial=True, deleted_at__isnull=True)
                .select_related("state")
                .first()
            )
            if initial is None or initial.state_id != state.id:
                affected.append(
                    {
                        "workflow_id": str(workflow.id),
                        "workflow_name": workflow.name,
                        "issue_type": workflow.issue_type.key if workflow.issue_type else None,
                        "current_initial_state_id": str(initial.state_id) if initial else None,
                        "current_initial_state_name": initial.state.name if initial else None,
                    }
                )

        confirmation = request.data.get(
            "confirm_workflow_impact", request.query_params.get("confirm_workflow_impact", False)
        )
        confirmed = str(confirmation).lower() == "true"
        if affected and not confirmed:
            return self._error(
                "workflow_impact_confirmation_required",
                "Changing the default state changes the initial state of the listed workflows.",
                status.HTTP_409_CONFLICT,
                affected_workflows=affected,
            )

        with transaction.atomic():
            State.objects.filter(workspace__slug=slug, project_id=project_id, default=True).exclude(pk=pk).update(
                default=False
            )
            State.objects.filter(workspace__slug=slug, project_id=project_id, pk=pk).update(default=True)
            for workflow in default_workflows:
                if str(workflow.id) not in {row["workflow_id"] for row in affected}:
                    continue
                WorkflowState.objects.filter(workflow=workflow, is_initial=True, deleted_at__isnull=True).update(
                    is_initial=False
                )
                WorkflowState.objects.update_or_create(
                    workflow=workflow,
                    state=state,
                    defaults={"is_initial": True, "project_id": project_id},
                )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @invalidate_cache(path="workspaces/:slug/states/", url_params=True, user=False)
    @allow_permission([ROLE.ADMIN])
    def destroy(self, request, slug, project_id, pk):
        state = State.objects.get(is_triage=False, pk=pk, project_id=project_id, workspace__slug=slug)

        if state.default:
            return Response(
                {"error": "Default state cannot be deleted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        issue_count = Issue.objects.filter(state=pk).count()
        force = str(request.query_params.get("force", "false")).lower() == "true"
        comment = (request.data.get("comment") or request.query_params.get("comment") or "").strip()
        if issue_count:
            if not force:
                return self._error(
                    "state_in_use",
                    "Move or reassign the work items before deleting this state.",
                    status.HTTP_409_CONFLICT,
                    issue_count=issue_count,
                )
            if not comment:
                return self._error(
                    "comment_required",
                    "A comment is required when force deleting a state with work items.",
                )

        workflow_rows = list(WorkflowState.objects.filter(state=state, deleted_at__isnull=True))
        if workflow_rows:
            workflow_ids = [row.workflow_id for row in workflow_rows]
            last_group_states = WorkflowState.objects.filter(
                workflow_id__in=workflow_ids, state__group=state.group, deleted_at__isnull=True
            )
            remaining = {
                (row.workflow_id, str(row.state_id))
                for row in last_group_states
                if str(row.state_id) != str(state.id)
            }
            for workflow_id in workflow_ids:
                if not any(wid == workflow_id for wid, _ in remaining):
                    return self._error(
                        "state_in_use",
                        "This state is the last state in its group for a workflow and cannot be deleted.",
                        status.HTTP_409_CONFLICT,
                        workflow_id=str(workflow_id),
                    )

        if issue_count and force:
            # Use the central engine so forced reassignment cannot bypass role rules.
            from plane.utils.workflow.transition import transition_issue

            default_state = State.objects.filter(project_id=project_id, default=True, deleted_at__isnull=True).first()
            if default_state is None or default_state.id == state.id:
                return self._error("default_state_required", "A different default state is required.")
            for issue_id in Issue.objects.filter(state=pk).values_list("id", flat=True):
                transition_issue(issue_id, default_state.id, request.user, comment=comment, source="state_delete")

        state.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IntakeStateEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        state = State.triage_objects.filter(workspace__slug=slug, project_id=project_id).first()
        if not state:
            return Response(
                {"error": "Triage state not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(StateSerializer(state).data, status=status.HTTP_200_OK)
