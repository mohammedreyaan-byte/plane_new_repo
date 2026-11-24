# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for PLN-007 type filters, grouping, ordering and projections."""

import pytest

from plane.db.models import Project
from plane.tests.workflow_helpers import client_for, make_issue, make_project, type_of

pytestmark = pytest.mark.contract


def issues_url(ws, project):
    return f"/api/workspaces/{ws.slug}/projects/{project.id}/issues/"


def flattened_rows(data):
    results = data["results"] if isinstance(data, dict) and "results" in data else data
    if isinstance(results, list):
        return results
    return [row for group in results.values() for row in (group.get("results", []) if isinstance(group, dict) else group)]


@pytest.fixture
def project(db, workspace, create_user):
    return make_project(workspace, create_user, identifier="TF", governed=True)


@pytest.fixture
def admin_client(project, create_user):
    return client_for(create_user)


@pytest.mark.django_db
def test_direct_type_id_filter_and_regression_state_group(workspace, project, admin_client):
    bug = make_issue(project, "bug", name="bug item")
    make_issue(project, "task", name="task item")
    bug_type = type_of(workspace, "bug")

    response = admin_client.get(f"{issues_url(workspace, project)}?type_id={bug_type.id}&per_page=50")
    assert response.status_code == 200, response.data
    assert {str(row["id"]) for row in flattened_rows(response.data)} == {str(bug.id)}

    # `type` must remain the state-group filter and must not be interpreted as a type UUID.
    legacy = admin_client.get(f"{issues_url(workspace, project)}?type=active&per_page=50")
    assert legacy.status_code == 200, legacy.data


@pytest.mark.django_db
def test_type_id_in_invalid_uuid_and_projection(workspace, project, admin_client):
    bug = make_issue(project, "bug", name="bug item")
    task = make_issue(project, "task", name="task item")
    bug_type = type_of(workspace, "bug")
    task_type = type_of(workspace, "task")

    response = admin_client.get(
        f"{issues_url(workspace, project)}?type_id__in={bug_type.id},{task_type.id}&per_page=50"
    )
    assert response.status_code == 200, response.data
    ids = {str(row["id"]) for row in flattened_rows(response.data)}
    assert ids == {str(bug.id), str(task.id)}

    bug_row = next(row for row in flattened_rows(response.data) if str(row["id"]) == str(bug.id))
    assert bug_row["type"]["key"] == "bug"
    assert str(bug_row["type"]["id"]) == str(bug_type.id)

    invalid = admin_client.get(f"{issues_url(workspace, project)}?type_id=not-a-uuid")
    assert invalid.status_code == 400
    assert "type_id" in str(invalid.data)


@pytest.mark.django_db
def test_group_by_type_id(workspace, project, admin_client):
    bug = make_issue(project, "bug", name="bug item")
    bug_type = type_of(workspace, "bug")
    response = admin_client.get(f"{issues_url(workspace, project)}?group_by=type_id&per_page=50")
    assert response.status_code == 200, response.data
    group = response.data["results"][str(bug_type.id)]
    assert group["total_results"] >= 1
    assert any(str(row["id"]) == str(bug.id) for row in group["results"])


@pytest.mark.django_db
def test_order_by_type_name(workspace, project, admin_client):
    make_issue(project, "task", name="task item")
    make_issue(project, "bug", name="bug item")
    response = admin_client.get(f"{issues_url(workspace, project)}?order_by=type__name&per_page=50")
    assert response.status_code == 200, response.data
    names = [row["type"]["name"] for row in flattened_rows(response.data) if row.get("type")]
    assert names == sorted(names, key=str.lower)


@pytest.mark.django_db
def test_types_disabled_project_ignores_filter_and_sets_header(workspace, project, admin_client):
    Project.objects.filter(pk=project.pk).update(is_issue_type_enabled=False)
    bug = make_issue(project, "bug", name="bug item")
    task = make_issue(project, "task", name="task item")
    bug_type = type_of(workspace, "bug")

    response = admin_client.get(f"{issues_url(workspace, project)}?type_id={bug_type.id}&per_page=50")
    assert response.status_code == 200, response.data
    assert response["X-Plane-Types-Disabled"] == "true"
    ids = {str(row["id"]) for row in flattened_rows(response.data)}
    assert ids == {str(bug.id), str(task.id)}
