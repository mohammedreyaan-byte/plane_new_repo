# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Create and repair the built-in workflows of a project."""

from django.db import transaction
from django.utils import timezone

from plane.db.models import State, Workflow, WorkflowState, WorkflowTransition
from plane.utils.issue_types import ensure_project_issue_types
from plane.utils.workflow.seeds import STATE_COLORS, WORKFLOW_SEEDS


def _ensure_state(project, name, group):
    state = State.all_state_objects.filter(project=project, name=name).first()
    if state is None:
        state = State.objects.create(project=project, name=name, group=group, color=STATE_COLORS[group])
    return state


@transaction.atomic
def seed_project_workflows(project, *, type_keys=None, reset=False):
    """Create (or, with ``reset``, restore) the built-in workflows of a project.

    Idempotent: workflows are matched by (project, issue type, name), states by
    (project, name) and transitions by (workflow, from, to). Existing states are reused as
    they are, so their group is never changed silently. Returns a summary dict.
    """
    types = ensure_project_issue_types(project)
    summary = {}

    for key, seed in WORKFLOW_SEEDS.items():
        if type_keys and key not in type_keys:
            continue

        issue_type = types[key].issue_type
        counts = {
            "workflow": "existing",
            "states_added": 0,
            "transitions_added": 0,
            "transitions_restored": 0,
            "transitions_removed": 0,
        }

        workflow = Workflow.objects.filter(project=project, issue_type=issue_type, name=seed["name"]).first()
        if workflow is None:
            workflow = Workflow.objects.create(
                project=project,
                issue_type=issue_type,
                name=seed["name"],
                is_default=True,
                is_active=True,
                description=f"Built-in {issue_type.name} workflow.",
            )
            counts["workflow"] = "created"

        states = {}
        for name, group, sequence, is_initial, is_final in seed["states"]:
            state = _ensure_state(project, name, group)
            states[name] = state
            row = WorkflowState.objects.filter(workflow=workflow, state=state).first()
            if row is None:
                WorkflowState.objects.create(
                    workflow=workflow,
                    project=project,
                    state=state,
                    sequence=sequence,
                    is_initial=is_initial,
                    is_final=is_final,
                )
                counts["states_added"] += 1
            elif reset:
                row.sequence, row.is_initial, row.is_final = sequence, is_initial, is_final
                row.save()

        wanted = set()
        for from_name, to_name, roles in seed["transitions"]:
            wanted.add((states[from_name].id, states[to_name].id))
            row = WorkflowTransition.objects.filter(
                workflow=workflow, from_state=states[from_name], to_state=states[to_name]
            ).first()
            if row is None:
                WorkflowTransition.objects.create(
                    workflow=workflow,
                    project=project,
                    from_state=states[from_name],
                    to_state=states[to_name],
                    allowed_roles=list(roles),
                )
                counts["transitions_added"] += 1
            elif reset and (row.allowed_roles != list(roles) or not row.is_active):
                row.allowed_roles, row.is_active, row.admin_override = list(roles), True, True
                row.requires_comment, row.required_fields = False, []
                row.save()
                counts["transitions_restored"] += 1

        if reset:
            for row in WorkflowTransition.objects.filter(workflow=workflow):
                if (row.from_state_id, row.to_state_id) not in wanted:
                    row.deleted_at = timezone.now()
                    row.save()
                    counts["transitions_removed"] += 1

        summary[key] = counts
    return summary
