# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Create, repair, export and import the built-in workflows of a project."""

import logging

from django.db import transaction
from django.utils import timezone

from plane.db.models import Issue, ProjectIssueType, State, Workflow, WorkflowState, WorkflowTransition
from plane.utils.issue_types import ensure_project_issue_types
from plane.utils.workflow.seeds import STATE_COLORS, WORKFLOW_SEEDS

logger = logging.getLogger("plane.workflow")


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


class WorkflowResetConflict(Exception):
    """Raised when a reset would orphan work items in states it is about to remove."""

    def __init__(self, count, states):
        self.count = count
        self.states = list(states)
        super().__init__(f"{count} work item(s) are in states that would be removed.")


class WorkflowImportError(ValueError):
    """Strict validation error for workflow import payloads."""

    def __init__(self, code, message, **details):
        self.code = code
        self.details = details
        super().__init__(message)


IMPORT_TOP_LEVEL_FIELDS = {"name", "issue_type_key", "states", "transitions"}
IMPORT_STATE_FIELDS = {"name", "group", "sequence", "is_initial", "is_final"}
IMPORT_TRANSITION_FIELDS = {
    "from",
    "to",
    "allowed_roles",
    "requires_comment",
    "required_fields",
    "admin_override",
    "is_active",
}


def workflow_reset_diff(project, workflow):
    """Describe what a built-in reset would add, update and remove."""
    key = workflow.issue_type.key if workflow.issue_type else None
    seed = WORKFLOW_SEEDS.get(key)
    if seed is None:
        raise WorkflowResetConflict(0, [])
    expected_names = [name for name, *_ in seed["states"]]
    expected_set = set(expected_names)

    mapped = list(
        WorkflowState.objects.filter(workflow=workflow, deleted_at__isnull=True).select_related("state")
    )
    mapped_by_name = {row.state.name: row for row in mapped}
    removed_rows = [row for row in mapped if row.state.name not in expected_set]
    removed_state_ids = {row.state_id for row in removed_rows}

    states_by_name = {
        state.name: state for state in State.all_state_objects.filter(project=project, name__in=expected_names)
    }
    expected_edges = {}
    for from_name, to_name, roles in seed["transitions"]:
        if from_name in states_by_name and to_name in states_by_name:
            expected_edges[(states_by_name[from_name].id, states_by_name[to_name].id)] = list(roles)

    existing_rows = list(
        WorkflowTransition.objects.filter(workflow=workflow, deleted_at__isnull=True).select_related(
            "from_state", "to_state"
        )
    )
    existing_edges = {(row.from_state_id, row.to_state_id): row for row in existing_rows}
    added_edges = sorted(set(expected_edges) - set(existing_edges))
    removed_edges = sorted(set(existing_edges) - set(expected_edges))
    updated_edges = []
    for pair in sorted(set(expected_edges) & set(existing_edges)):
        row = existing_edges[pair]
        expected = expected_edges[pair]
        if list(row.allowed_roles or []) != expected or not row.is_active or row.admin_override is False:
            updated_edges.append(pair)

    affected = Issue.objects.filter(project=project, type_id=workflow.issue_type_id).filter(
        state_id__in=removed_state_ids
    ).count()

    return {
        "added": {
            "states": sorted(expected_set - set(mapped_by_name)),
            "transitions": len(added_edges),
        },
        "updated": {
            "states": sorted(
                name
                for name, row in mapped_by_name.items()
                if name in expected_set
                and (
                    row.is_initial
                    != next(item[3] for item in seed["states"] if item[0] == name)
                    or row.is_final != next(item[4] for item in seed["states"] if item[0] == name)
                )
            ),
            "transitions": len(updated_edges),
        },
        "removed": {
            "states": sorted(row.state.name for row in removed_rows),
            "transitions": len(removed_edges),
        },
        "affected_items": affected,
    }


def reset_workflow(project, workflow, *, force=False, user=None):
    """Reset a system workflow, optionally moving items out of removed states."""
    from plane.utils.workflow.transition import reset_issue_state

    key = workflow.issue_type.key if workflow.issue_type else None
    seed = WORKFLOW_SEEDS.get(key)
    if seed is None:
        raise WorkflowResetConflict(0, [])

    plan = workflow_reset_diff(project, workflow)
    if plan["affected_items"] and not force:
        raise WorkflowResetConflict(plan["affected_items"], plan["removed"]["states"])

    with transaction.atomic():
        stale_rows = WorkflowState.objects.filter(workflow=workflow, deleted_at__isnull=True).exclude(
            state__name__in=[name for name, *_ in seed["states"]]
        )
        if plan["affected_items"]:
            initial_name = next(name for name, _, _, is_initial, _ in seed["states"] if is_initial)
            initial_state = State.all_state_objects.filter(project=project, name=initial_name).first()
            if initial_state is None:
                initial_state = _ensure_state(project, initial_name, seed["states"][0][1])
            for issue in Issue.objects.filter(project=project, type_id=workflow.issue_type_id).filter(
                state_id__in=stale_rows.values_list("state_id", flat=True)
            ):
                reset_issue_state(issue.id, initial_state.id, user=user, reason="workflow_reset", source="api")
            plan["moved"] = plan["affected_items"]

        stale_rows.update(deleted_at=timezone.now(), updated_at=timezone.now())
        summary = seed_project_workflows(project, type_keys=[key], reset=True)
        plan["summary"] = summary[key]
    return plan


def export_workflow(workflow):
    """A stable, secret-free representation that import accepts verbatim."""
    states = [
        {
            "name": row.state.name,
            "group": row.state.group,
            "sequence": row.sequence,
            "is_initial": row.is_initial,
            "is_final": row.is_final,
        }
        for row in WorkflowState.objects.filter(workflow=workflow, deleted_at__isnull=True)
        .select_related("state")
        .order_by("sequence")
    ]
    transitions = [
        {
            "from": row.from_state.name,
            "to": row.to_state.name,
            "allowed_roles": list(row.allowed_roles or []),
            "requires_comment": row.requires_comment,
            "required_fields": list(row.required_fields or []),
            "admin_override": row.admin_override,
            "is_active": row.is_active,
        }
        for row in WorkflowTransition.objects.filter(workflow=workflow, deleted_at__isnull=True)
        .select_related("from_state", "to_state")
        .order_by("from_state__sequence", "to_state__sequence")
    ]
    return {
        "name": workflow.name,
        "issue_type_key": workflow.issue_type.key if workflow.issue_type else None,
        "states": states,
        "transitions": transitions,
    }


def _require_exact_keys(value, allowed, label):
    if not isinstance(value, dict):
        raise WorkflowImportError("invalid_payload", f"{label} must be an object.")
    unknown = set(value) - allowed
    if unknown:
        raise WorkflowImportError(
            "unknown_fields",
            f"Unknown {label} field(s): {', '.join(sorted(unknown))}.",
            fields=sorted(unknown),
        )


@transaction.atomic
def import_workflow(project, payload):
    """Create a workflow from an export payload; unknown fields are rejected."""
    _require_exact_keys(payload, IMPORT_TOP_LEVEL_FIELDS, "workflow")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise WorkflowImportError("invalid_name", "Enter a workflow name between 1 and 120 characters.")
    key = payload.get("issue_type_key")
    project_type = (
        ProjectIssueType.objects.filter(
            project=project,
            issue_type__key=key,
            is_enabled=True,
            deleted_at__isnull=True,
        )
        .select_related("issue_type")
        .first()
    )
    if project_type is None:
        raise WorkflowImportError("type_not_enabled", "The target work item type is not enabled in this project.")
    if Workflow.objects.filter(project=project, name=name.strip(), deleted_at__isnull=True).exists():
        raise WorkflowImportError("duplicate_name", "A workflow with this name already exists in the project.", status=409)

    states = payload.get("states")
    if not isinstance(states, list) or not states:
        raise WorkflowImportError("invalid_payload", "states must be a non-empty list.")
    seen_names = set()
    for row in states:
        _require_exact_keys(row, IMPORT_STATE_FIELDS, "state")
        state_name = row.get("name")
        if not isinstance(state_name, str) or not state_name.strip():
            raise WorkflowImportError("invalid_payload", "Every state needs a name.")
        if state_name in seen_names:
            raise WorkflowImportError("duplicate_state", f"State '{state_name}' appears more than once.")
        seen_names.add(state_name)
        if row.get("group") not in STATE_COLORS:
            raise WorkflowImportError("invalid_payload", f"Unknown state group: {row.get('group')}.")
    initial = [row for row in states if row.get("is_initial") is True]
    final = [row for row in states if row.get("is_final") is True]
    if len(initial) != 1:
        raise WorkflowImportError("missing_initial", "Exactly one state must be marked initial.")
    if not final:
        raise WorkflowImportError("missing_final", "At least one state must be marked final.")

    transitions = payload.get("transitions")
    if not isinstance(transitions, list):
        raise WorkflowImportError("invalid_payload", "transitions must be a list.")
    seen_edges = set()
    for row in transitions:
        _require_exact_keys(row, IMPORT_TRANSITION_FIELDS, "transition")
        from_name, to_name = row.get("from"), row.get("to")
        if from_name not in seen_names or to_name not in seen_names:
            raise WorkflowImportError("invalid_transition", "Transitions may only reference states in this payload.")
        if from_name == to_name:
            raise WorkflowImportError("self_transition", "A state cannot move to itself.")
        if (from_name, to_name) in seen_edges:
            raise WorkflowImportError("duplicate_transition", f"Transition {from_name} -> {to_name} is duplicated.")
        seen_edges.add((from_name, to_name))
        for list_field in ("allowed_roles", "required_fields"):
            if not isinstance(row.get(list_field, []), list):
                raise WorkflowImportError("invalid_payload", f"{list_field} must be a list.")

    workflow = Workflow.objects.create(
        project=project,
        issue_type=project_type.issue_type,
        name=name.strip(),
        description=f"Imported {project_type.issue_type.name} workflow.",
        is_default=False,
        is_active=True,
    )
    state_by_name = {}
    for row in states:
        existing = State.all_state_objects.filter(project=project, name=row["name"]).first()
        if existing is not None and existing.group != row["group"]:
            logger.warning(
                "workflow import kept existing state group state=%s wanted=%s kept=%s",
                row["name"],
                row["group"],
                existing.group,
            )
        state = _ensure_state(project, row["name"], row["group"])
        state_by_name[row["name"]] = state
        WorkflowState.objects.create(
            workflow=workflow,
            project=project,
            state=state,
            sequence=row.get("sequence", 65535),
            is_initial=row.get("is_initial", False),
            is_final=row.get("is_final", False),
        )
    for row in transitions:
        WorkflowTransition.objects.create(
            workflow=workflow,
            project=project,
            from_state=state_by_name[row["from"]],
            to_state=state_by_name[row["to"]],
            allowed_roles=list(row.get("allowed_roles") or []),
            requires_comment=bool(row.get("requires_comment", False)),
            required_fields=list(row.get("required_fields") or []),
            admin_override=bool(row.get("admin_override", True)),
            is_active=bool(row.get("is_active", True)),
        )
    return workflow
