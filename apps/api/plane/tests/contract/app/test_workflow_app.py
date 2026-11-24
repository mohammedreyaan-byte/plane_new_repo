# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for workflows and role based transitions (PLN-005/006/013)."""

import pytest

from plane.db.models import Issue, IssueComment, Workflow, WorkflowTransition
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

pytestmark = pytest.mark.contract


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
