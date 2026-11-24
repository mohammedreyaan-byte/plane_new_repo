# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for the Developer / QA / Viewer roles (PLN-014).

The new roles reuse spare legacy integers (Developer 12, QA 11, Viewer 2). The old
integer checks did not know about them, so before the compatibility layer a
Developer could be added to a project but could not create or edit work items, could
not be assigned to one, and a Viewer was rejected even on read endpoints.

These tests pin the intended behaviour through the real HTTP endpoints:

* Developer and QA behave like Member for work items, and can be assigned.
* Developer and QA are kept out of cycle and module management (``cycle.manage`` /
  ``module.manage`` are Admin and Member capabilities only).
* Viewer can read but never write. Guest behaviour is unchanged.
"""

from uuid import uuid4

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, IssueAssignee, Project, ProjectMember, State, User, WorkspaceMember

ADMIN, MEMBER, DEVELOPER, QA, GUEST, VIEWER = 20, 15, 12, 11, 5, 2

ISSUES_URL = "/api/workspaces/{slug}/projects/{project_id}/issues/"
CYCLES_URL = "/api/workspaces/{slug}/projects/{project_id}/cycles/"
MODULES_URL = "/api/workspaces/{slug}/projects/{project_id}/modules/"

pytestmark = pytest.mark.contract


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Role Project", identifier="RP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=ADMIN)
    State.objects.create(name="Todo", project=project, workspace=workspace, group="unstarted", default=True)
    return project


def _user_with_role(workspace, project, role):
    suffix = uuid4().hex[:8]
    user = User.objects.create(
        email=f"role{role}-{suffix}@plane.so", username=f"role{role}_{suffix}", first_name="R", last_name=str(role)
    )
    user.set_password("test-password")
    user.save()
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def make_client(workspace, project):
    def _make(role):
        return _client(_user_with_role(workspace, project, role))

    return _make


def _issues(workspace, project):
    return ISSUES_URL.format(slug=workspace.slug, project_id=project.id)


@pytest.mark.django_db
@pytest.mark.parametrize("role", [MEMBER, DEVELOPER, QA])
def test_contributor_roles_can_create_work_items(role, workspace, project, make_client):
    response = make_client(role).post(_issues(workspace, project), {"name": f"created by {role}"}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    assert Issue.objects.filter(project=project, name=f"created by {role}").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", [VIEWER, GUEST])
def test_read_only_roles_cannot_create_work_items(role, workspace, project, make_client):
    response = make_client(role).post(_issues(workspace, project), {"name": "nope"}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert not Issue.objects.filter(project=project, name="nope").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", [MEMBER, DEVELOPER, QA, VIEWER])
def test_roles_can_read_work_items(role, workspace, project, make_client):
    response = make_client(role).get(_issues(workspace, project))
    assert response.status_code == status.HTTP_200_OK, response.data


@pytest.mark.django_db
@pytest.mark.parametrize("role", [DEVELOPER, QA])
def test_developer_and_qa_can_be_assigned_to_work_items(role, workspace, project, make_client, create_user):
    assignee = _user_with_role(workspace, project, role)
    response = _client(create_user).post(
        _issues(workspace, project), {"name": "assign me", "assignee_ids": [str(assignee.id)]}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    issue = Issue.objects.get(project=project, name="assign me")
    assert IssueAssignee.objects.filter(issue=issue, assignee=assignee).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", [VIEWER, GUEST])
def test_viewer_and_guest_cannot_be_assigned(role, workspace, project, create_user):
    assignee = _user_with_role(workspace, project, role)
    response = _client(create_user).post(
        _issues(workspace, project), {"name": "no assign", "assignee_ids": [str(assignee.id)]}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    issue = Issue.objects.get(project=project, name="no assign")
    assert not IssueAssignee.objects.filter(issue=issue, assignee=assignee).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", [DEVELOPER, QA])
def test_developer_and_qa_cannot_manage_cycles_or_modules(role, workspace, project, make_client):
    client = make_client(role)
    cycle = client.post(
        CYCLES_URL.format(slug=workspace.slug, project_id=project.id),
        {"name": "Sprint 1", "start_date": "2026-12-01", "end_date": "2026-12-14"},
        format="json",
    )
    module = client.post(MODULES_URL.format(slug=workspace.slug, project_id=project.id), {"name": "M1"}, format="json")
    assert cycle.status_code == status.HTTP_403_FORBIDDEN
    assert module.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_member_can_still_manage_cycles_and_modules(workspace, project, make_client):
    client = make_client(MEMBER)
    cycle = client.post(
        CYCLES_URL.format(slug=workspace.slug, project_id=project.id),
        {"name": "Sprint 1", "start_date": "2026-12-01", "end_date": "2026-12-14"},
        format="json",
    )
    module = client.post(MODULES_URL.format(slug=workspace.slug, project_id=project.id), {"name": "M1"}, format="json")
    assert cycle.status_code == status.HTTP_201_CREATED, cycle.data
    assert module.status_code == status.HTTP_201_CREATED, module.data


@pytest.mark.django_db
@pytest.mark.parametrize("role", [DEVELOPER, QA, VIEWER])
def test_developer_qa_viewer_can_list_cycles(role, workspace, project, make_client):
    response = make_client(role).get(CYCLES_URL.format(slug=workspace.slug, project_id=project.id))
    assert response.status_code == status.HTTP_200_OK, response.data
