# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Rules applied when a work item is created or updated (types, hierarchy, workflow).

Both issue serializers (web ``IssueCreateSerializer`` and the v1 ``IssueSerializer``) call
these helpers, so the web app and the public API cannot disagree. Projects that have not
enabled work item types are not affected at all (``is_issue_type_enabled`` is False).
"""

from crum import get_current_user

from plane.db.models import Issue, Project, WorkflowState
from plane.utils.issue_types import get_default_issue_type, is_type_enabled_in_project
from plane.utils.workflow.transition import (
    WorkflowError,
    get_workflow_for_issue,
    project_is_governed,
    validate_transition,
)

# child type key -> parent type keys that are not allowed for it
FORBIDDEN_PARENTS = {
    "story": {"task", "bug"},
    "epic": {"task", "bug", "story", "epic"},
}


def _actor():
    user = get_current_user()
    return user if user is not None and not user.is_anonymous else None


def _types_enabled(project_id):
    return Project.objects.filter(pk=project_id, is_issue_type_enabled=True).exists()


def check_parent_type(parent, issue_type):
    """Epic > Story > Task/Bug. Raises 400 invalid_parent_type when the pairing is not allowed."""
    if parent is None or issue_type is None or parent.type_id is None:
        return
    parent_key = getattr(parent.type, "key", None)
    child_key = issue_type.key
    if child_key in FORBIDDEN_PARENTS and parent_key in FORBIDDEN_PARENTS[child_key]:
        raise WorkflowError(
            "invalid_parent_type",
            f"A {issue_type.name} cannot be a child of a {parent.type.name}. "
            "Epics sit at the top and contain stories, tasks and bugs; stories contain tasks and bugs.",
            parent_id=str(parent.id),
            parent_type=parent_key,
            child_type=child_key,
        )


def _initial_state(project_id, issue_type):
    """The first state of the workflow that governs a new item of this type, or None."""
    probe = Issue(project_id=project_id, type=issue_type)
    workflow = get_workflow_for_issue(probe)
    if workflow is None:
        return None
    row = WorkflowState.objects.filter(workflow=workflow, is_initial=True).select_related("state").first()
    return row.state if row else None


def apply_create_rules(project_id, validated_data, *, allow_triage=False):
    """Type default, hierarchy and initial state for a new work item. Mutates and returns the dict."""
    issue_type = validated_data.get("type")
    if not _types_enabled(project_id):
        if issue_type is not None:
            raise WorkflowError(
                "types_disabled", "Work item types are not enabled in this project.", project_id=str(project_id)
            )
        return validated_data

    if issue_type is None:
        issue_type = get_default_issue_type(project_id)
        validated_data["type"] = issue_type
    elif not is_type_enabled_in_project(project_id, issue_type.id):
        raise WorkflowError(
            "type_not_enabled", f"'{issue_type.name}' is not enabled in this project.", type_id=str(issue_type.id)
        )

    check_parent_type(validated_data.get("parent"), issue_type)

    if not allow_triage and issue_type is not None and project_is_governed(project_id):
        initial = _initial_state(project_id, issue_type)
        if initial is not None:
            # New items always start in the first state of their workflow.
            validated_data["state"] = initial
    return validated_data


def apply_update_rules(issue, validated_data, user=None):
    """Type, hierarchy and workflow rules for an update. Mutates and returns the dict."""
    user = user or _actor()
    types_on = _types_enabled(issue.project_id)

    if "type" in validated_data:
        new_type = validated_data["type"]
        new_type_id = new_type.id if new_type else None
        if new_type_id != issue.type_id:
            if not types_on:
                raise WorkflowError(
                    "types_disabled",
                    "Work item types are not enabled in this project.",
                    project_id=str(issue.project_id),
                )
            if new_type is not None and not is_type_enabled_in_project(issue.project_id, new_type.id):
                raise WorkflowError(
                    "type_not_enabled", f"'{new_type.name}' is not enabled in this project.", type_id=str(new_type.id)
                )
            check_parent_type(validated_data.get("parent", issue.parent), new_type)

            # Moving to a type with another workflow: reset the state when the current one is not in it.
            if new_type is not None and project_is_governed(issue.project_id):
                probe = Issue(project_id=issue.project_id, type=new_type)
                workflow = get_workflow_for_issue(probe)
                if workflow is not None:
                    in_workflow = set(
                        WorkflowState.objects.filter(workflow=workflow).values_list("state_id", flat=True)
                    )
                    current = validated_data.get("state") or issue.state
                    if current is None or current.id not in in_workflow:
                        initial = _initial_state(issue.project_id, new_type)
                        if initial is not None:
                            validated_data["state"] = initial
                            # System reset on a type change: not a user transition.
                            return validated_data
    elif "parent" in validated_data:
        check_parent_type(validated_data["parent"], issue.type)

    new_state = validated_data.get("state")
    if new_state is not None and new_state.id != issue.state_id and user is not None:
        validate_transition(issue, new_state, user)
    return validated_data
