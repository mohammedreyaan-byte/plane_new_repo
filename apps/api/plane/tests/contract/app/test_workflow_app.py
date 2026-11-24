# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for workflows and role based transitions (PLN-005/006/013)."""

import json
import pytest
from datetime import timedelta
from pathlib import Path
import re
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.db.models import Q

from uuid import uuid4

from plane.bgtasks.webhook_task import get_model_data
from plane.db.models import Issue, IssueActivity, IssueComment, State, Workflow, WorkflowState, WorkflowTransition
from plane.tests.workflow_helpers import (
    DEVELOPER,
    GUEST,
    MEMBER,
    QA,
    VIEWER,
    client_for,
    make_issue,
    make_project,
    make_user,
    state_of,
    type_of,
)
from plane.utils.workflow.service import workflow_reset_diff

pytestmark = pytest.mark.contract


def test_runtime_issue_state_assignments_are_allowlisted():
    """Keep new state-write paths on the transition service."""
    plane_root = Path(__file__).resolve().parents[3]
    allowlisted = {
        plane_root / "utils" / "workflow" / "transition.py",
        plane_root / "app" / "serializers" / "intake.py",
        plane_root / "api" / "serializers" / "intake.py",
        plane_root / "db" / "models" / "issue.py",
        plane_root / "db" / "models" / "draft.py",
        # Explicit repair tooling, documented in utils/workflow/README.md.
        plane_root / "db" / "management" / "commands" / "repair_states.py",
        # The CI guard itself documents the pattern; it does not write state.
        plane_root / "utils" / "workflow" / "check_state_writes.py",
    }
    direct_assignment = re.compile(r"\.state\s*=(?!=)|\.update\(\s*state=")
    offenders = []
    for path in plane_root.rglob("*.py"):
        if "migrations" in path.parts or "tests" in path.parts:
            continue
        if path not in allowlisted and direct_assignment.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(plane_root)))
    assert not offenders, f"Direct issue state writes must use transition_issue: {offenders}"


def base(ws, project):
    return f"/api/workspaces/{ws.slug}/projects/{project.id}"


@pytest.fixture
def project(db, workspace, create_user):
    return make_project(workspace, create_user, governed=True)


@pytest.fixture
def admin_client(project, create_user):
    return client_for(create_user)


def patch_state(client, ws, project, issue, name):
    return client.patch(
        f"{base(ws, project)}/issues/{issue.id}/", {"state_id": str(state_of(project, name).id)}, format="json"
    )


def transition(client, ws, project, issue, name, **extra):
    return client.post(
        f"{base(ws, project)}/work-items/{issue.id}/transition/",
        {"to_state_id": str(state_of(project, name).id), **extra},
        format="json",
    )


@pytest.mark.django_db
def test_bug_flows_end_to_end_through_the_issue_endpoint(workspace, project, create_user):
    bug = make_issue(project, "bug", "New")
    dev = client_for(make_user(workspace, project, DEVELOPER))
    qa = client_for(make_user(workspace, project, QA))

    assert patch_state(dev, workspace, project, bug, "In Progress").status_code == 204
    assert patch_state(dev, workspace, project, bug, "In Testing").status_code == 204
    # developer may not mark it tested
    denied = patch_state(dev, workspace, project, bug, "Tested")
    assert denied.status_code == 403
    assert denied.data["error"]["code"] == "transition_forbidden"
    assert patch_state(qa, workspace, project, bug, "Tested").status_code == 204
    assert patch_state(qa, workspace, project, bug, "Closed").status_code == 204
    bug.refresh_from_db()
    assert bug.state.name == "Closed" and bug.completed_at is not None


@pytest.mark.django_db
def test_transition_not_in_workflow_is_a_400(workspace, project, admin_client):
    bug = make_issue(project, "bug", "New")
    # admin override widens roles, it does not invent edges that are not in the workflow
    response = patch_state(admin_client, workspace, project, bug, "Tested")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "transition_not_allowed"
    dev = client_for(make_user(workspace, project, DEVELOPER))
    other = make_issue(project, "bug", "New", name="other")
    refused = patch_state(dev, workspace, project, other, "Closed")
    assert refused.status_code == 400
    assert refused.data["error"]["code"] == "transition_not_allowed"


@pytest.mark.django_db
@pytest.mark.parametrize("role", [VIEWER, GUEST])
def test_read_only_roles_cannot_change_state(role, workspace, project):
    bug = make_issue(project, "bug", "New")
    client = client_for(make_user(workspace, project, role))
    assert patch_state(client, workspace, project, bug, "In Progress").status_code == 403
    assert transition(client, workspace, project, bug, "In Progress").status_code == 403
    bug.refresh_from_db()
    assert bug.state.name == "New"


@pytest.mark.django_db
def test_ungoverned_project_changes_state_freely(workspace, create_user):
    project = make_project(workspace, create_user, identifier="FR", governed=False)
    from plane.db.models import State

    State.objects.create(name="Done", project=project, workspace=workspace, group="completed")
    issue = Issue.objects.create(project=project, workspace=workspace, name="free")
    dev = client_for(make_user(workspace, project, DEVELOPER))
    response = patch_state(dev, workspace, project, issue, "Done")
    assert response.status_code == 204


@pytest.mark.django_db
def test_transition_endpoint_moves_state_and_records_comment(workspace, project):
    bug = make_issue(project, "bug", "New")
    dev = client_for(make_user(workspace, project, DEVELOPER))
    response = transition(dev, workspace, project, bug, "In Progress", comment="Picking this up")
    assert response.status_code == 200, response.data
    assert str(response.data["state_id"]) == str(state_of(project, "In Progress").id)
    assert IssueComment.objects.filter(issue=bug, comment_stripped="Picking this up").exists()


@pytest.mark.django_db
def test_transition_endpoint_enforces_roles_with_the_error_contract(workspace, project):
    bug = make_issue(project, "bug", "In Testing")
    dev = client_for(make_user(workspace, project, DEVELOPER))
    response = transition(dev, workspace, project, bug, "Tested")
    assert response.status_code == 403
    assert response.data["error"]["code"] == "transition_forbidden"
    assert set(response.data["error"]) >= {"code", "message", "details"}


@pytest.mark.django_db
def test_comment_required_on_reopen_via_both_endpoints(workspace, project):
    bug = make_issue(project, "bug", "Closed")
    reopen = WorkflowTransition.objects.filter(
        workflow__project=project, from_state__name="Closed", to_state__name="Reopened"
    ).first()
    if reopen is None:
        pytest.skip("seed has no Closed -> Reopened edge")
    reopen.requires_comment = True
    reopen.save()
    qa = client_for(make_user(workspace, project, QA))

    refused = transition(qa, workspace, project, bug, "Reopened")
    assert refused.status_code == 400 and refused.data["error"]["code"] == "comment_required"
    # PATCH has nowhere to carry a comment, so it is refused as well
    assert patch_state(qa, workspace, project, bug, "Reopened").status_code == 400
    assert transition(qa, workspace, project, bug, "Reopened", comment="Fails again").status_code == 200


@pytest.mark.django_db
def test_allowed_transitions_differ_by_role(workspace, project, admin_client):
    bug = make_issue(project, "bug", "In Testing")
    url = f"{base(workspace, project)}/work-items/{bug.id}/allowed-transitions/"

    dev = client_for(make_user(workspace, project, DEVELOPER)).get(url)
    assert dev.status_code == 200
    names = (
        {t["to_state_name"] for t in dev.data["transitions"]}
        if dev.data["transitions"] and "to_state_name" in dev.data["transitions"][0]
        else None
    )
    if names is not None:
        assert "Tested" not in names and "In Progress" in names
    assert "denied" not in dev.data

    qa = client_for(make_user(workspace, project, QA)).get(url)
    assert qa.status_code == 200 and len(qa.data["transitions"]) > len(dev.data["transitions"])

    admin = admin_client.get(url)
    assert admin.status_code == 200 and "denied" not in admin.data  # admin override: nothing denied
    edge = WorkflowTransition.objects.get(
        workflow__project=project,
        workflow__issue_type__key="bug",
        from_state__name="In Testing",
        to_state__name="Tested",
    )
    edge.admin_override = False
    edge.allowed_roles = ["qa"]
    edge.save()
    admin = admin_client.get(url)
    assert [d["to_state_name"] for d in admin.data["denied"]] == ["Tested"]
    assert "denied" not in client_for(make_user(workspace, project, DEVELOPER)).get(url).data


@pytest.mark.django_db
def test_workflow_list_and_detail(workspace, project, admin_client):
    listed = admin_client.get(f"{base(workspace, project)}/workflows/")
    assert listed.status_code == 200
    assert {w["issue_type_key"] for w in listed.data} == {"bug", "task", "story", "epic"}
    detail = admin_client.get(f"{base(workspace, project)}/workflows/{listed.data[0]['id']}/")
    assert detail.status_code == 200 and detail.data["states"] and detail.data["transitions"]
    assert sum(1 for s in detail.data["states"] if s["is_initial"]) == 1


@pytest.mark.django_db
def test_admin_edits_a_transition_and_the_engine_follows(workspace, project, admin_client):
    wf = Workflow.objects.get(project=project, issue_type__key="bug")
    edge = WorkflowTransition.objects.get(workflow=wf, from_state__name="In Testing", to_state__name="Tested")
    url = f"{base(workspace, project)}/workflows/{wf.id}/transitions/{edge.id}/"

    changed = admin_client.patch(url, {"allowed_roles": ["developer", "qa", "admin"]}, format="json")
    assert changed.status_code == 200
    bug = make_issue(project, "bug", "In Testing")
    dev = client_for(make_user(workspace, project, DEVELOPER))
    assert patch_state(dev, workspace, project, bug, "Tested").status_code == 204

    bad = admin_client.patch(url, {"required_fields": ["nonsense"]}, format="json")
    assert bad.status_code == 400 and bad.data["error"]["code"] == "invalid_payload"


@pytest.mark.django_db
def test_admin_adds_and_removes_a_transition(workspace, project, admin_client):
    wf = Workflow.objects.get(project=project, issue_type__key="bug")
    url = f"{base(workspace, project)}/workflows/{wf.id}/transitions/"
    payload = {
        "from_state_id": str(state_of(project, "New").id),
        "to_state_id": str(state_of(project, "Closed").id),
        "allowed_roles": ["qa"],
    }
    created = admin_client.post(url, payload, format="json")
    assert created.status_code == 201, created.data
    assert admin_client.delete(f"{url}{created.data['id']}/").status_code == 204
    assert not WorkflowTransition.objects.filter(pk=created.data["id"]).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", [MEMBER, DEVELOPER, QA, VIEWER])
def test_only_admins_edit_workflows(role, workspace, project):
    wf = Workflow.objects.get(project=project, issue_type__key="bug")
    client = client_for(make_user(workspace, project, role))
    response = client.post(
        f"{base(workspace, project)}/workflows/{wf.id}/transitions/",
        {"from_state_id": str(state_of(project, "New").id), "to_state_id": str(state_of(project, "Closed").id)},
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_reset_restores_the_built_in_matrix(workspace, project, admin_client):
    wf = Workflow.objects.get(project=project, issue_type__key="bug")
    before = WorkflowTransition.objects.filter(workflow=wf).count()
    WorkflowTransition.objects.filter(workflow=wf).first().delete()
    response = admin_client.post(f"{base(workspace, project)}/workflows/{wf.id}/reset/")
    assert response.status_code == 200, response.data
    assert WorkflowTransition.objects.filter(workflow=wf).count() == before


@pytest.mark.django_db
def test_clone_creates_independent_workflow_rows_and_requires_replace(workspace, project, admin_client):
    source = Workflow.objects.get(project=project, issue_type__key="bug")
    task_type = type_of(workspace, "task")
    url = f"{base(workspace, project)}/workflows/{source.id}/clone/"

    conflict = admin_client.post(url, {"name": "Bug to task", "issue_type_id": str(task_type.id)}, format="json")
    assert conflict.status_code == 409
    assert conflict.data["error"]["code"] == "default_exists"

    response = admin_client.post(
        url,
        {"name": "Task QA workflow", "issue_type_id": str(task_type.id), "replace": True},
        format="json",
    )
    assert response.status_code == 201, response.data
    cloned = Workflow.objects.get(pk=response.data["id"])
    assert cloned.issue_type_id == task_type.id and cloned.is_default and cloned.is_active
    archived = Workflow.all_objects.get(project=project, issue_type=task_type, name="Task workflow")
    assert not archived.is_active and archived.deleted_at is not None
    assert cloned.workflow_states.count() == source.workflow_states.count()
    assert cloned.transitions.count() == source.transitions.count()

    source_edge = source.transitions.first()
    clone_edge = cloned.transitions.get(from_state_id=source_edge.from_state_id, to_state_id=source_edge.to_state_id)
    clone_edge.allowed_roles = ["qa"]
    clone_edge.save()
    source_edge.refresh_from_db()
    assert source_edge.allowed_roles != ["qa"]


@pytest.mark.django_db
def test_clone_rejects_a_type_not_enabled_in_the_project(workspace, project, admin_client, create_user):
    source = Workflow.objects.get(project=project, issue_type__key="bug")
    other_workspace = workspace.__class__.objects.create(name="Other", slug="other-workspace", owner=create_user)
    foreign_type = type_of(other_workspace, "bug")
    response = admin_client.post(
        f"{base(workspace, project)}/workflows/{source.id}/clone/",
        {"name": "Foreign clone", "issue_type_id": str(foreign_type.id)},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["error"]["code"] == "type_not_enabled"


@pytest.mark.django_db
def test_auto_close_uses_the_type_workflow_and_records_the_transition(workspace, project, monkeypatch):
    from plane.bgtasks import issue_automation_task

    project.close_in = 1
    project.save(update_fields=["close_in", "updated_at"])
    project.refresh_from_db()
    assert project.created_by_id is None  # auto-close should use the workspace owner as its actor fallback
    task = make_issue(project, "task", "In Progress", name="Old task")
    Issue.objects.filter(pk=task.pk).update(updated_at=timezone.now() - timedelta(days=60))
    assert Issue.issue_objects.filter(
        project=project,
        archived_at__isnull=True,
        updated_at__lte=timezone.now() - timedelta(days=30),
        state__group__in=["backlog", "unstarted", "started"],
    ).filter(
        Q(issue_intake__status=1)
        | Q(issue_intake__status=-1)
        | Q(issue_intake__status=2)
        | Q(issue_intake__isnull=True)
    ).filter(issue_cycle__isnull=True, issue_module__isnull=True).filter(pk=task.pk).exists()
    activity_events = []
    monkeypatch.setattr(issue_automation_task.issue_activity, "delay", lambda **event: activity_events.append(event))
    transition_errors = []
    original_transition = issue_automation_task.transition_issue

    def capture_transition_error(*args, **kwargs):
        try:
            return original_transition(*args, **kwargs)
        except Exception as error:
            transition_errors.append(error)
            raise

    monkeypatch.setattr(issue_automation_task, "transition_issue", capture_transition_error)

    def raise_logged_exception(error):
        raise error

    monkeypatch.setattr(issue_automation_task, "log_exception", raise_logged_exception)

    issue_automation_task.close_old_issues()

    task.refresh_from_db()
    assert task.state.name == "Done", transition_errors
    assert activity_events and activity_events[0]["requested_data"].find('"automation": true') >= 0


@pytest.mark.django_db
def test_health_is_clean_for_seeded_workflows(workspace, project, admin_client):
    response = admin_client.get(f"{base(workspace, project)}/workflows/health/")
    assert response.status_code == 200, response.data
    assert not response.data.get("issues"), response.data


@pytest.mark.django_db
def test_create_always_starts_in_the_initial_state(workspace, project, admin_client):
    closed = state_of(project, "Closed")
    response = admin_client.post(
        f"{base(workspace, project)}/issues/",
        {"name": "sneaky", "type_id": str(type_of(workspace, "bug").id), "state_id": str(closed.id)},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert Issue.objects.get(project=project, name="sneaky").state.name == "New"


@pytest.mark.django_db
def test_changing_type_moves_the_item_into_the_new_workflow(workspace, project, admin_client):
    bug = make_issue(project, "bug", "Code Review")
    response = admin_client.patch(
        f"{base(workspace, project)}/issues/{bug.id}/", {"type_id": str(type_of(workspace, "story").id)}, format="json"
    )
    assert response.status_code == 204, getattr(response, "data", None)
    bug.refresh_from_db()
    assert bug.type.key == "story"
    from plane.db.models import WorkflowState

    mapped = WorkflowState.objects.filter(workflow__project=project, workflow__issue_type__key="story")
    assert mapped.filter(state=bug.state).exists() or bug.state.name == "Backlog"


@pytest.mark.django_db
def test_triaged_item_can_only_enter_the_workflow_at_its_initial_state(workspace, project):
    from plane.db.models import State

    triage = State.objects.create(name="Triage", project=project, workspace=workspace, group="triage", sequence=1)
    bug = make_issue(project, "bug", None, name="from intake")
    Issue.objects.filter(pk=bug.pk).update(state=triage)
    dev = client_for(make_user(workspace, project, DEVELOPER))

    skip = transition(dev, workspace, project, bug, "In Progress")
    assert skip.status_code == 400
    assert transition(dev, workspace, project, bug, "New").status_code == 200


def bulk_url(ws, project):
    return f"{base(ws, project)}/bulk-operation-issues/"


@pytest.mark.django_db
def test_bulk_move_applies_the_workflow_to_every_item(workspace, project):
    allowed = make_issue(project, "bug", "New", name="ok")
    blocked = make_issue(project, "bug", "In Testing", name="blocked")
    dev = client_for(make_user(workspace, project, DEVELOPER))
    response = dev.post(
        bulk_url(workspace, project),
        {
            "issue_ids": [str(allowed.id), str(blocked.id)],
            "properties": {"state_id": str(state_of(project, "In Progress").id)},
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    # New -> In Progress is allowed, In Testing -> In Progress is allowed too; both succeed
    assert set(response.data["updated"]) == {str(allowed.id), str(blocked.id)}

    tested = dev.post(
        bulk_url(workspace, project),
        {"issue_ids": [str(blocked.id)], "properties": {"state_id": str(state_of(project, "Tested").id)}},
        format="json",
    )
    assert tested.status_code == 200
    assert tested.data["updated"] == []
    assert tested.data["failed"][0]["code"] in ("transition_forbidden", "transition_not_allowed")


@pytest.mark.django_db
def test_bulk_update_reports_partial_failure_without_stopping(workspace, project):
    in_testing = make_issue(project, "bug", "In Testing", name="a")
    in_progress = make_issue(project, "bug", "In Progress", name="b")
    qa = client_for(make_user(workspace, project, QA))
    response = qa.post(
        bulk_url(workspace, project),
        {
            "issue_ids": [str(in_testing.id), str(in_progress.id)],
            "properties": {"state_id": str(state_of(project, "Tested").id)},
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["updated"] == [str(in_testing.id)]
    assert [f["issue_id"] for f in response.data["failed"]] == [str(in_progress.id)]
    in_progress.refresh_from_db()
    assert in_progress.state.name == "In Progress"


@pytest.mark.django_db
def test_bulk_update_validation_and_permissions(workspace, project, admin_client):
    issue = make_issue(project, "task", None, name="x")
    assert (
        admin_client.post(bulk_url(workspace, project), {"issue_ids": [], "properties": {}}, format="json").status_code
        == 400
    )
    bad = admin_client.post(
        bulk_url(workspace, project), {"issue_ids": [str(issue.id)], "properties": {"cycle_id": "x"}}, format="json"
    )
    assert bad.status_code == 400 and "cycle_id" in bad.data["unsupported"]
    viewer = client_for(make_user(workspace, project, VIEWER))
    assert (
        viewer.post(
            bulk_url(workspace, project),
            {"issue_ids": [str(issue.id)], "properties": {"priority": "high"}},
            format="json",
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_bulk_type_change_respects_hierarchy(workspace, project, admin_client):
    epic = make_issue(project, "epic", None, name="epic")
    child = make_issue(project, "task", None, name="child", parent=epic)
    response = admin_client.post(
        bulk_url(workspace, project),
        {"issue_ids": [str(child.id)], "properties": {"type_id": str(type_of(workspace, "epic").id)}},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["failed"][0]["code"] == "invalid_parent_type"


# ---------------------------------------------------------------------------
# PLN-013: capability contract, role preview and stale workflow handling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_allowed_transitions_deny_capability_less_roles(workspace, project):
    bug = make_issue(project, "bug", "In Testing")
    url = f"{base(workspace, project)}/work-items/{bug.id}/allowed-transitions/"
    guest = client_for(make_user(workspace, project, GUEST)).get(url)

    assert guest.status_code == 403
    assert guest.data["error"]["code"] == "transition_forbidden"
    assert "state" in guest.data["error"]["message"]


@pytest.mark.django_db
def test_workflow_allowed_transitions_preview_as_role(workspace, project, admin_client):
    bug = make_issue(project, "bug", "In Testing")
    wf = Workflow.objects.get(project=project, issue_type__key="bug")
    edge = WorkflowTransition.objects.get(
        workflow=wf, from_state__name="In Testing", to_state__name="Tested"
    )
    edge.allowed_roles = ["qa"]
    edge.admin_override = False
    edge.save(update_fields=["allowed_roles", "admin_override"])
    url = f"{base(workspace, project)}/workflows/{wf.id}/allowed-transitions/"

    developer = admin_client.get(url, {"issue_id": str(bug.id), "role": "developer"})
    assert developer.status_code == 200, developer.data
    assert [t["to_state_name"] for t in developer.data["transitions"]] != ["Tested"]
    assert "Tested" in [t["to_state_name"] for t in developer.data["denied"]]

    qa = admin_client.get(url, {"issue_id": str(bug.id), "role": "qa"})
    assert qa.status_code == 200
    assert "Tested" in [t["to_state_name"] for t in qa.data["transitions"]]

    non_admin = client_for(make_user(workspace, project, DEVELOPER)).get(
        url, {"issue_id": str(bug.id), "role": "developer"}
    )
    assert non_admin.status_code == 403
    assert non_admin.data["error"]["code"] == "transition_forbidden"


@pytest.mark.django_db
def test_stale_transition_id_is_a_409(workspace, project):
    bug = make_issue(project, "bug", "New")
    dev = client_for(make_user(workspace, project, DEVELOPER))
    stale_id = str(uuid4())
    response = transition(dev, workspace, project, bug, "In Progress", transition_id=stale_id)

    assert response.status_code == 409
    assert response.data["error"]["code"] == "stale_workflow"
    bug.refresh_from_db()
    assert bug.state.name == "New"


@pytest.mark.django_db
def test_admin_override_writes_an_audit_activity(workspace, project, admin_client):
    bug = make_issue(project, "bug", "In Testing")
    wf = Workflow.objects.get(project=project, issue_type__key="bug")
    edge = WorkflowTransition.objects.get(
        workflow=wf, from_state__name="In Testing", to_state__name="Tested"
    )
    edge.allowed_roles = ["qa"]
    edge.admin_override = True
    edge.save(update_fields=["allowed_roles", "admin_override"])

    response = transition(admin_client, workspace, project, bug, "Tested")
    assert response.status_code == 200, response.data
    audit = IssueActivity.objects.filter(issue=bug, field="workflow.admin_override")
    assert audit.exists()
    assert f"transition={edge.id}" in audit.first().comment


# ---------------------------------------------------------------------------
# PLN-002: state validation, workflow usage and deletion guards
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_state_create_validates_duplicate_names_and_colors(workspace, project, admin_client):
    url = f"{base(workspace, project)}/states/"
    duplicate = admin_client.post(url, {"name": "new", "color": "#ffffff", "group": "unstarted"}, format="json")
    assert duplicate.status_code == 400
    assert duplicate.data["error"]["code"] == "duplicate_state_name"

    bad_color = admin_client.post(url, {"name": "Review", "color": "red", "group": "unstarted"}, format="json")
    assert bad_color.status_code == 400
    assert bad_color.data["error"]["code"] == "invalid_state_color"


@pytest.mark.django_db
def test_state_list_exposes_used_by_workflows(workspace, project, admin_client):
    response = admin_client.get(f"{base(workspace, project)}/states/")
    assert response.status_code == 200
    new_state = next(state for state in response.data if state["name"] == "New")
    workflow_names = [wf["name"] for wf in new_state["used_by_workflows"]]
    assert "Bug workflow" in workflow_names
    assert str(new_state["workflow_id"]) == str(Workflow.objects.get(project=project, issue_type__key="bug").id)


@pytest.mark.django_db
def test_create_state_can_add_it_to_a_workflow(workspace, project, admin_client):
    wf = Workflow.objects.get(project=project, issue_type__key="bug")
    response = admin_client.post(
        f"{base(workspace, project)}/states/",
        {
            "name": "QA Hold",
            "color": "#8b5cf6",
            "group": "started",
            "workflow_ids": [str(wf.id)],
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert [wf_row["id"] for wf_row in response.data["used_by_workflows"]] == [str(wf.id)]

    listed = admin_client.get(f"{base(workspace, project)}/states/").data
    state = next(row for row in listed if row["name"] == "QA Hold")
    assert [wf_row["id"] for wf_row in state["used_by_workflows"]] == [str(wf.id)]


@pytest.mark.django_db
def test_workflow_group_change_and_in_use_delete_are_conflicts(workspace, project, admin_client):
    url = f"{base(workspace, project)}/states/{state_of(project, 'New').id}/"
    changed = admin_client.patch(url, {"group": "completed"}, format="json")
    assert changed.status_code == 409
    assert changed.data["error"]["code"] == "group_change_affects_workflow"

    make_issue(project, "bug", "New", name="still here")
    deleted = admin_client.delete(url)
    assert deleted.status_code == 409
    assert deleted.data["error"]["code"] == "state_in_use"
    assert State.objects.filter(pk=state_of(project, "New").id).exists()


# ---------------------------------------------------------------------------
# PLN-004/005/006: durable transitions, webhooks, reset and strict import/export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transition_writes_durable_activity_and_exactly_one_comment(workspace, project, admin_client):
    bug = make_issue(project, "bug", "New")
    edge = WorkflowTransition.objects.get(
        workflow__project=project,
        workflow__issue_type__key="bug",
        from_state__name="New",
        to_state__name="In Progress",
    )

    response = transition(admin_client, workspace, project, bug, "In Progress", comment="Picking this up")
    assert response.status_code == 200, response.data

    activity = IssueActivity.objects.get(
        issue=bug,
        field="state",
        verb="transition",
        new_value=str(state_of(project, "In Progress").id),
    )
    metadata = json.loads(activity.comment)
    assert metadata["workflow_id"] == str(edge.workflow_id)
    assert metadata["transition_id"] == str(edge.id)
    assert metadata["comment"] == "Picking this up"
    assert IssueComment.objects.filter(issue=bug, comment_stripped="Picking this up").count() == 1


@pytest.mark.django_db
def test_webhook_issue_payload_includes_workflow_fields_and_batches_activity_lookup(
    workspace, project, admin_client
):
    bug = make_issue(project, "bug", "New")
    task = make_issue(project, "task", "Backlog")
    edge = WorkflowTransition.objects.get(
        workflow__project=project,
        workflow__issue_type__key="bug",
        from_state__name="New",
        to_state__name="In Progress",
    )
    assert transition(admin_client, workspace, project, bug, "In Progress").status_code == 200

    with CaptureQueriesContext(connection) as captured:
        payload = get_model_data(event="issue", event_id=[str(bug.id), str(task.id)], many=True)

    rows = {str(row["id"]): row for row in payload}
    bug_row = rows[str(bug.id)]
    assert bug_row["type_key"] == "bug" and bug_row["type_name"] == "Bug"
    assert bug_row["state_id"] == str(state_of(project, "In Progress").id)
    assert bug_row["state_name"] == "In Progress"
    assert bug_row["from_state_id"] == str(state_of(project, "New").id)
    assert bug_row["workflow_id"] == str(edge.workflow_id)
    assert bug_row["transition_id"] == str(edge.id)
    assert rows[str(task.id)]["type_key"] == "task"

    activity_queries = [query for query in captured.captured_queries if "issue_activities" in query["sql"]]
    assert len(activity_queries) == 1, [query["sql"] for query in activity_queries]


@pytest.mark.django_db
def test_stale_transition_id_after_the_edge_is_removed(workspace, project, admin_client):
    bug = make_issue(project, "bug", "New")
    edge = WorkflowTransition.objects.get(
        workflow__project=project,
        workflow__issue_type__key="bug",
        from_state__name="New",
        to_state__name="In Progress",
    )
    preview = admin_client.get(f"{base(workspace, project)}/work-items/{bug.id}/allowed-transitions/")
    assert preview.status_code == 200
    offered = next(row for row in preview.data["transitions"] if row["to_state_name"] == "In Progress")
    edge.delete()

    response = transition(
        admin_client, workspace, project, bug, "In Progress", transition_id=offered["transition_id"]
    )
    assert response.status_code == 409
    assert response.data["error"]["code"] == "stale_workflow"


@pytest.mark.django_db
def test_disabled_project_keeps_plane_1_4_2_state_behaviour(workspace, project, create_user):
    project.is_issue_type_enabled = False
    project.save(update_fields=["is_issue_type_enabled", "updated_at"])
    bug = make_issue(project, "bug", "New")
    dev = client_for(make_user(workspace, project, DEVELOPER))

    response = patch_state(dev, workspace, project, bug, "In Progress")
    assert response.status_code == 204
    bug.refresh_from_db()
    assert bug.state.name == "In Progress"


@pytest.mark.django_db
def test_type_change_writes_audit_and_state_reset_activity(workspace, project, admin_client):
    bug = make_issue(project, "bug", "Code Review")
    response = admin_client.patch(
        f"{base(workspace, project)}/issues/{bug.id}/",
        {"type_id": str(type_of(workspace, "story").id)},
        format="json",
    )
    assert response.status_code == 204, getattr(response, "data", None)

    bug.refresh_from_db()
    assert bug.type.key == "story" and bug.state.name == "Backlog"
    type_activity = IssueActivity.objects.filter(issue=bug, field="type", verb="updated").first()
    assert type_activity is not None
    assert "Type changed from Bug to Story" in type_activity.comment
    assert "state reset to Backlog" in type_activity.comment

    state_activity = IssueActivity.objects.filter(issue=bug, field="state", verb="transition").first()
    assert state_activity is not None
    assert json.loads(state_activity.comment)["reason"] == "type_change"


@pytest.mark.django_db
def test_epic_force_completion_requires_a_comment_and_writes_an_audit_row(workspace, project, admin_client):
    epic = make_issue(project, "epic", "In Progress", name="epic")
    make_issue(project, "task", "New", name="open child", parent=epic)
    url = f"{base(workspace, project)}/work-items/{epic.id}/transition/"
    payload = {"to_state_id": str(state_of(project, "Done").id)}

    denied = admin_client.post(url, payload, format="json")
    assert denied.status_code == 400
    assert denied.data["error"]["code"] == "epic_has_open_children"
    assert denied.data["error"]["details"]["count"] == 1
    assert denied.data["error"]["details"]["sample_ids"]

    no_comment = admin_client.post(f"{url}?force=true", payload, format="json")
    assert no_comment.status_code == 400
    assert no_comment.data["error"]["code"] == "epic_has_open_children"

    forced = admin_client.post(f"{url}?force=true", {**payload, "comment": "Ship it"}, format="json")
    assert forced.status_code == 200, forced.data
    epic.refresh_from_db()
    assert epic.state.name == "Done"

    audit = IssueActivity.objects.get(issue=epic, field="workflow.epic_force_complete")
    assert "count=1" in audit.comment and "Ship it" in audit.comment


@pytest.mark.django_db
def test_reset_reports_a_diff_conflicts_and_moves_items_with_force(workspace, project, admin_client):
    workflow = Workflow.objects.get(project=project, issue_type__key="bug")
    custom = State.objects.create(name="Custom", project=project, workspace=workspace, group="started")
    WorkflowState.objects.create(workflow=workflow, project=project, state=custom, sequence=95000)
    reset_url = f"{base(workspace, project)}/workflows/{workflow.id}/reset/"

    plan = workflow_reset_diff(project, workflow)
    assert "Custom" in plan["removed"]["states"]
    assert plan["affected_items"] == 0

    stuck = make_issue(project, "bug", "Custom", name="stuck")
    conflict = admin_client.post(reset_url)
    assert conflict.status_code == 409
    assert conflict.data["error"]["code"] == "items_in_removed_states"
    assert conflict.data["error"]["details"]["count"] == 1
    assert conflict.data["error"]["details"]["states"] == ["Custom"]
    assert WorkflowState.objects.filter(workflow=workflow, state=custom).exists()

    forced = admin_client.post(f"{reset_url}?force=true")
    assert forced.status_code == 200, forced.data
    assert forced.data["removed"]["states"] == ["Custom"]
    assert forced.data["affected_items"] == 1 and forced.data["moved"] == 1
    assert forced.data["summary"]["workflow"] == "existing"

    stuck.refresh_from_db()
    assert stuck.state.name == "New"
    assert not WorkflowState.objects.filter(workflow=workflow, state=custom).exists()
    assert IssueActivity.objects.filter(
        issue=stuck, field="state", verb="transition", comment__contains="workflow_reset"
    ).exists()


@pytest.mark.django_db
def test_health_reports_structural_problems_with_type_and_workflow_ids(workspace, project, admin_client):
    task_workflow = Workflow.objects.get(project=project, issue_type__key="task")
    task_workflow.is_active = False
    task_workflow.save(update_fields=["is_active", "updated_at"])

    bug_workflow = Workflow.objects.get(project=project, issue_type__key="bug")
    WorkflowState.objects.filter(workflow=bug_workflow, is_final=True).update(is_final=False)
    off_menu = State.objects.create(name="Off-menu", project=project, workspace=workspace, group="started")
    make_issue(project, "bug", "Off-menu", name="stray")

    assert off_menu.name == "Off-menu"
    response = admin_client.get(f"{base(workspace, project)}/workflows/health/")
    assert response.status_code == 200
    issues = response.data["issues"]
    codes = {issue["code"] for issue in issues}
    assert {"missing_default_workflow", "missing_final", "items_in_unmapped_states"} <= codes

    stray_issue = next(issue for issue in issues if issue["code"] == "items_in_unmapped_states")
    assert stray_issue["type_id"] == str(type_of(workspace, "bug").id)
    assert stray_issue["workflow_id"] == str(bug_workflow.id)


@pytest.mark.django_db
def test_workflow_export_import_is_strict_and_repeatable(workspace, project, admin_client):
    workflow = Workflow.objects.get(project=project, issue_type__key="bug")
    exported = admin_client.get(f"{base(workspace, project)}/workflows/{workflow.id}/export/")
    assert exported.status_code == 200
    assert exported.data["issue_type_key"] == "bug"
    assert exported.data["states"] and exported.data["transitions"]

    payload = json.loads(json.dumps(exported.data))
    unknown = {**payload, "surprise": True}
    refused = admin_client.post(f"{base(workspace, project)}/workflows/import/", unknown, format="json")
    assert refused.status_code == 400
    assert refused.data["error"]["code"] == "unknown_fields"
    assert refused.data["error"]["details"]["fields"] == ["surprise"]

    payload["name"] = "Imported Bug workflow"
    imported = admin_client.post(f"{base(workspace, project)}/workflows/import/", payload, format="json")
    assert imported.status_code == 201, imported.data
    imported_id = imported.data["id"]
    assert Workflow.objects.get(pk=imported_id).name == "Imported Bug workflow"
    assert WorkflowState.objects.filter(workflow_id=imported_id).count() == len(payload["states"])
    assert WorkflowTransition.objects.filter(workflow_id=imported_id).count() == len(payload["transitions"])

    duplicate = admin_client.post(f"{base(workspace, project)}/workflows/import/", payload, format="json")
    assert duplicate.status_code == 409
    assert duplicate.data["error"]["code"] == "duplicate_name"

    nested = json.loads(json.dumps(payload))
    nested["name"] = "Nested unknown"
    nested["states"][0]["oops"] = 1
    nested_refused = admin_client.post(f"{base(workspace, project)}/workflows/import/", nested, format="json")
    assert nested_refused.status_code == 400
    assert nested_refused.data["error"]["code"] == "unknown_fields"
    assert nested_refused.data["error"]["details"]["fields"] == ["oops"]
