# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for the work item template API and template application."""

from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from plane.db.models import Project, ProjectMember, State, User, WorkspaceMember, WorkItemTemplate

pytestmark = pytest.mark.contract

ADMIN, MEMBER = 20, 15


@pytest.fixture
def template_context(db, workspace, create_user):
    project = Project.objects.create(
        name="Template Review", identifier="TPL", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(workspace=workspace, project=project, member=create_user, role=ADMIN)
    State.objects.create(
        name="Todo", project=project, workspace=workspace, group="unstarted", color="#000000", default=True
    )
    suffix = uuid4().hex[:8]
    member = User.objects.create(email=f"member-{suffix}@plane.so", username=f"member_{suffix}")
    WorkspaceMember.objects.create(workspace=workspace, member=member, role=MEMBER)
    ProjectMember.objects.create(workspace=workspace, project=project, member=member, role=MEMBER)
    admin_client = APIClient()
    admin_client.force_authenticate(user=create_user)
    member_client = APIClient()
    member_client.force_authenticate(user=member)
    return {
        "workspace": workspace,
        "project": project,
        "admin": create_user,
        "member": member,
        "admin_client": admin_client,
        "member_client": member_client,
    }


def _url(name, **kwargs):
    return reverse(name, kwargs=kwargs)


def test_workspace_template_options_expose_priorities_and_members(template_context):
    workspace = template_context["workspace"]
    admin_client = template_context["admin_client"]
    member = template_context["member"]

    response = admin_client.get(_url("workspace-work-item-template-options", slug=workspace.slug))

    assert response.status_code == 200, response.data
    assert "high" in {item["value"] for item in response.data["priorities"]}
    assert str(member.id) in {item["id"] for item in response.data["members"]}
    assert response.data["states"] == []
    assert response.data["modules"] == []


def test_workspace_and_project_template_crud_and_validation(template_context):
    workspace = template_context["workspace"]
    project = template_context["project"]
    admin_client = template_context["admin_client"]
    member_client = template_context["member_client"]
    payload = {
        "name": "Bug report",
        "description": "Pre-filled bug report",
        "template_data": {
            "title_template": "Bug: ",
            "description_template": "Steps to reproduce",
            "priority": "high",
        },
        "is_public": True,
    }

    workspace_url = _url("workspace-work-item-templates", slug=workspace.slug)
    created = admin_client.post(workspace_url, payload, format="json")
    assert created.status_code == 201, created.data
    assert created.data["scope"] == "workspace"
    assert created.data["project_id"] is None
    assert WorkItemTemplate.objects.filter(workspace=workspace, project__isnull=True).count() == 1

    project_url = _url("project-work-item-templates", slug=workspace.slug, project_id=project.id)
    project_created = admin_client.post(project_url, {**payload, "name": "Feature request"}, format="json")
    assert project_created.status_code == 201, project_created.data
    assert project_created.data["scope"] == "project"
    assert project_created.data["project_id"] == str(project.id)

    assert [item["name"] for item in member_client.get(workspace_url).data] == ["Bug report"]
    assert [item["name"] for item in member_client.get(project_url).data] == ["Feature request"]
    assert member_client.post(project_url, payload, format="json").status_code == 201

    invalid = admin_client.post(
        project_url,
        {**payload, "template_data": {"unknown_field": "value"}},
        format="json",
    )
    assert invalid.status_code == 400

    detail_url = _url(
        "project-work-item-template-detail",
        slug=workspace.slug,
        project_id=project.id,
        pk=project_created.data["id"],
    )
    patched = admin_client.patch(detail_url, {"description": "Updated"}, format="json")
    assert patched.status_code == 200
    assert patched.data["description"] == "Updated"
    assert admin_client.delete(detail_url).status_code == 204
    assert not WorkItemTemplate.objects.filter(pk=project_created.data["id"]).exists()


def test_private_template_is_hidden_from_other_members(template_context):
    workspace = template_context["workspace"]
    admin_client = template_context["admin_client"]
    member_client = template_context["member_client"]
    url = _url("workspace-work-item-templates", slug=workspace.slug)

    created = admin_client.post(
        url,
        {"name": "Private", "template_data": {"priority": "high"}, "is_public": False},
        format="json",
    )
    assert created.status_code == 201
    assert member_client.get(url).data == []
    assert [item["name"] for item in admin_client.get(url).data] == ["Private"]

    detail_url = _url("workspace-work-item-template-detail", slug=workspace.slug, pk=created.data["id"])
    for method in (member_client.patch, member_client.delete):
        response = method(detail_url, {"name": "Changed"}, format="json")
        assert response.status_code == 404


def test_private_project_template_cannot_be_changed_by_other_members(template_context):
    workspace = template_context["workspace"]
    project = template_context["project"]
    admin_client = template_context["admin_client"]
    member_client = template_context["member_client"]
    url = _url("project-work-item-templates", slug=workspace.slug, project_id=project.id)

    created = admin_client.post(
        url,
        {"name": "Private project template", "template_data": {"priority": "high"}, "is_public": False},
        format="json",
    )
    assert created.status_code == 201

    detail_url = _url(
        "project-work-item-template-detail",
        slug=workspace.slug,
        project_id=project.id,
        pk=created.data["id"],
    )
    assert member_client.get(detail_url).status_code == 404
    assert member_client.patch(detail_url, {"name": "Changed"}, format="json").status_code == 404
    assert member_client.delete(detail_url).status_code == 404


def test_template_id_merges_defaults_and_explicit_fields_win(template_context):
    workspace = template_context["workspace"]
    project = template_context["project"]
    client = template_context["admin_client"]
    template_url = _url("project-work-item-templates", slug=workspace.slug, project_id=project.id)
    issue_url = _url("project-issue", slug=workspace.slug, project_id=project.id)

    template = client.post(
        template_url,
        {
            "name": "Bug report",
            "template_data": {
                "title_template": "Template title",
                "description_template": "Template description",
                "priority": "high",
            },
        },
        format="json",
    )
    assert template.status_code == 201, template.data

    merged = client.post(issue_url, {"template_id": template.data["id"]}, format="json")
    assert merged.status_code == 201, merged.data
    assert merged.data["name"] == "Template title"
    assert merged.data["priority"] == "high"

    overridden = client.post(
        issue_url,
        {"template_id": template.data["id"], "name": "Explicit title", "priority": "low"},
        format="json",
    )
    assert overridden.status_code == 201, overridden.data
    assert overridden.data["name"] == "Explicit title"
    assert overridden.data["priority"] == "low"

    missing = client.post(issue_url, {"template_id": uuid4()}, format="json")
    assert missing.status_code == 400
