# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for linking a module to an epic (PLN-012)."""

import pytest

from plane.db.models import Module, ModuleIssue
from plane.tests.workflow_helpers import DEVELOPER, client_for, make_issue, make_project, make_user

pytestmark = pytest.mark.contract


def base(ws, project):
    return f"/api/workspaces/{ws.slug}/projects/{project.id}"


@pytest.fixture
def project(db, workspace, create_user):
    return make_project(workspace, create_user, governed=True)


@pytest.fixture
def admin_client(project, create_user):
    return client_for(create_user)


@pytest.mark.django_db
def test_module_can_be_created_and_relinked_with_an_epic(workspace, project, admin_client):
    epic = make_issue(project, "epic", None, name="Payments")
    created = admin_client.post(
        f"{base(workspace, project)}/modules/", {"name": "Checkout", "epic_id": str(epic.id)}, format="json"
    )
    assert created.status_code == 201, created.data
    assert str(created.data["epic_id"]) == str(epic.id)

    detail = admin_client.get(f"{base(workspace, project)}/modules/{created.data['id']}/")
    assert detail.status_code == 200 and str(detail.data["epic_id"]) == str(epic.id)

    unlinked = admin_client.patch(
        f"{base(workspace, project)}/modules/{created.data['id']}/", {"epic_id": None}, format="json"
    )
    assert unlinked.status_code == 200 and unlinked.data["epic_id"] is None


@pytest.mark.django_db
def test_only_epics_in_the_same_project_can_be_linked(workspace, project, create_user, admin_client):
    task = make_issue(project, "task", None, name="a task")
    refused = admin_client.post(
        f"{base(workspace, project)}/modules/", {"name": "Bad", "epic_id": str(task.id)}, format="json"
    )
    assert refused.status_code == 400 and "epic_id" in refused.data

    other = make_project(workspace, create_user, identifier="OT", governed=True)
    foreign_epic = make_issue(other, "epic", None, name="elsewhere")
    refused = admin_client.post(
        f"{base(workspace, project)}/modules/", {"name": "Bad2", "epic_id": str(foreign_epic.id)}, format="json"
    )
    assert refused.status_code == 400 and "epic_id" in refused.data


@pytest.mark.django_db
def test_epic_lists_its_modules_with_progress(workspace, project, admin_client):
    epic = make_issue(project, "epic", None, name="Payments")
    module = Module.objects.create(name="Checkout", project=project, workspace=workspace, epic=epic)
    done = make_issue(project, "task", "Done" if False else None, name="done")
    open_item = make_issue(project, "task", None, name="open")
    from plane.db.models import State

    completed = State.objects.create(name="Shipped", project=project, workspace=workspace, group="completed")
    type(done).objects.filter(pk=done.pk).update(state=completed)
    for issue in (done, open_item):
        ModuleIssue.objects.create(module=module, issue=issue, project=project, workspace=workspace)

    response = admin_client.get(f"{base(workspace, project)}/work-items/{epic.id}/epic-modules/")
    assert response.status_code == 200, response.data
    assert [m["name"] for m in response.data["modules"]] == ["Checkout"]
    assert response.data["total_issues"] == 2 and response.data["completed_issues"] == 1
    assert response.data["progress"] == 50

    not_epic = admin_client.get(f"{base(workspace, project)}/work-items/{done.id}/epic-modules/")
    assert not_epic.status_code == 400


@pytest.mark.django_db
def test_developer_cannot_link_but_can_read(workspace, project):
    epic = make_issue(project, "epic", None, name="E")
    dev = client_for(make_user(workspace, project, DEVELOPER))
    assert (
        dev.post(
            f"{base(workspace, project)}/modules/", {"name": "M", "epic_id": str(epic.id)}, format="json"
        ).status_code
        == 403
    )
    assert dev.get(f"{base(workspace, project)}/work-items/{epic.id}/epic-modules/").status_code == 200
