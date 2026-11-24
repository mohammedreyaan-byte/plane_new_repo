# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for workflow-aware boards and WIP limits (PLN-009)."""

import pytest
from uuid import uuid4

from plane.db.models import Project, Workflow, WorkflowState
from plane.tests.workflow_helpers import (
    VIEWER,
    client_for,
    make_issue,
    make_project,
    make_user,
    state_of,
    type_of,
)

pytestmark = pytest.mark.contract


@pytest.fixture
def project(db, workspace, create_user):
    return make_project(workspace, create_user, identifier="WB", governed=True)


@pytest.fixture
def admin_client(project, create_user):
    return client_for(create_user)


def workflow_for(workspace, project, key="bug"):
    return Workflow.objects.get(project=project, issue_type=type_of(workspace, key), is_default=True)


def workflow_state(workflow, state_name):
    return WorkflowState.objects.get(workflow=workflow, state=state_of(workflow.project, state_name))


def issues_url(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/"


@pytest.mark.django_db
def test_board_metadata_is_additive_and_type_scoped(workspace, project, admin_client):
    make_issue(project, "bug", "New", name="one")
    bug_type = type_of(workspace, "bug")

    response = admin_client.get(
        f"{issues_url(workspace, project)}?layout=board&group_by=state_id&type_id={bug_type.id}&per_page=50"
    )
    assert response.status_code == 200, response.data
    metadata = response.data["extra_stats"]
    workflow = workflow_for(workspace, project)
    expected_states = list(
        WorkflowState.objects.filter(workflow=workflow)
        .select_related("state")
        .order_by("sequence")
        .values_list("state__name", flat=True)
    )
    assert metadata["health"] == "ok"
    assert metadata["type_id"] == str(bug_type.id)
    assert [column["name"] for column in metadata["columns"]] == expected_states
    assert metadata["columns"][0]["count"] == 1
    assert metadata["columns"][0]["wip_limit"] is None

    # A type without a workflow gets an explicit health state, not an empty 200 list.
    missing = admin_client.get(
        f"{issues_url(workspace, project)}?layout=board&group_by=state_id&type_id={uuid4()}&per_page=50"
    )
    assert missing.status_code == 200, missing.data
    assert missing.data["extra_stats"]["health"] == "no_workflow"
    assert missing.data["extra_stats"]["columns"] == []


@pytest.mark.django_db
def test_workflow_state_wip_limit_requires_admin(workspace, project, admin_client):
    workflow = workflow_for(workspace, project)
    ws = workflow_state(workflow, "New")
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/workflows/{workflow.id}/states/{ws.id}/"

    response = admin_client.patch(url, {"wip_limit": 3}, format="json")
    assert response.status_code == 200, response.data
    ws.refresh_from_db()
    assert ws.wip_limit == 3

    viewer = client_for(make_user(workspace, project, VIEWER))
    denied = viewer.patch(url, {"wip_limit": 5}, format="json")
    assert denied.status_code == 403


@pytest.mark.django_db
def test_hard_wip_limit_blocks_transition_but_warn_only_does_not(workspace, project, admin_client):
    workflow = workflow_for(workspace, project)
    ws = workflow_state(workflow, "In Progress")
    ws.wip_limit = 1
    ws.save(update_fields=["wip_limit"])
    first = make_issue(project, "bug", "New", name="first")
    second = make_issue(project, "bug", "New", name="second")
    target = str(state_of(project, "In Progress").id)

    # Warn-only default: both moves succeed.
    assert admin_client.patch(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{first.id}/",
        {"state_id": target},
        format="json",
    ).status_code == 204
    assert admin_client.patch(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{second.id}/",
        {"state_id": target},
        format="json",
    ).status_code == 204

    Project.objects.filter(pk=project.pk).update(board_wip_hard_limit=True)
    third = make_issue(project, "bug", "New", name="third")
    blocked = admin_client.patch(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{third.id}/",
        {"state_id": target},
        format="json",
    )
    assert blocked.status_code == 400
    assert blocked.data["error"]["code"] == "wip_limit_reached"


@pytest.mark.django_db
def test_board_reorder_writes_only_sort_order(workspace, project, admin_client):
    first = make_issue(project, "bug", "New", name="first")
    second = make_issue(project, "bug", "New", name="second")
    state_id = str(state_of(project, "New").id)
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/board/reorder/"

    response = admin_client.post(
        url,
        {
            "items": [
                {
                    "issue_id": str(second.id),
                    "state_id": state_id,
                    "before_id": str(first.id),
                    "after_id": None,
                }
            ]
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    second.refresh_from_db()
    first.refresh_from_db()
    assert second.sort_order > first.sort_order
    assert str(second.state_id) == state_id

    mismatch = admin_client.post(
        url,
        {
            "issue_id": str(second.id),
            "state_id": str(state_of(project, "In Progress").id),
        },
        format="json",
    )
    assert mismatch.status_code == 400
    assert mismatch.data["error"]["code"] == "state_mismatch"
