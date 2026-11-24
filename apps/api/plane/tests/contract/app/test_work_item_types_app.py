# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for work item types (PLN-004)."""

import pytest

from plane.db.models import Issue, IssueType, Module, ProjectIssueType
from plane.tests.workflow_helpers import (
    DEVELOPER,
    MEMBER,
    VIEWER,
    client_for,
    make_issue,
    make_project,
    make_user,
    type_of,
)
from plane.utils.issue_types import ensure_project_issue_types, ensure_workspace_issue_types

pytestmark = pytest.mark.contract


def ws_types(ws):
    return f"/api/workspaces/{ws.slug}/work-item-types/"


def proj_types(ws, project):
    return f"/api/workspaces/{ws.slug}/projects/{project.id}/work-item-types/"


def issues(ws, project):
    return f"/api/workspaces/{ws.slug}/projects/{project.id}/issues/"


@pytest.fixture
def project(db, workspace, create_user):
    return make_project(workspace, create_user, governed=True)


@pytest.fixture
def admin_client(project, create_user):
    return client_for(create_user)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_workspace_and_project_get_the_four_default_types(workspace, create_user):
    types = IssueType.objects.filter(workspace=workspace)
    assert set(types.values_list("key", flat=True)) == {"bug", "task", "story", "epic"}
    assert types.get(key="epic").is_epic and not types.get(key="bug").is_epic

    project = make_project(workspace, create_user, identifier="NP", governed=False)
    rows = ProjectIssueType.objects.filter(project=project)
    assert rows.count() == 4 and all(r.is_enabled for r in rows)
    assert rows.get(is_default=True).issue_type.key == "task"


@pytest.mark.django_db
def test_seeding_is_idempotent(workspace, create_user):
    project = make_project(workspace, create_user, identifier="ID", governed=False)
    ensure_workspace_issue_types(workspace)
    ensure_project_issue_types(project)
    assert IssueType.objects.filter(workspace=workspace).count() == 4
    assert ProjectIssueType.objects.filter(project=project).count() == 4


@pytest.mark.django_db
def test_data_migration_seeds_existing_workspaces_and_projects_twice(workspace, create_user):
    import importlib

    from django.apps import apps

    project = make_project(workspace, create_user, identifier="MG", governed=False)
    ProjectIssueType.objects.all().delete()
    IssueType.objects.all().delete()

    seed = importlib.import_module("plane.db.migrations.0129_seed_default_issue_types").seed
    seed(apps, None)
    seed(apps, None)
    assert IssueType.objects.filter(workspace=workspace).count() == 4
    assert ProjectIssueType.objects.filter(project=project).count() == 4
    assert ProjectIssueType.objects.get(project=project, is_default=True).issue_type.key == "task"


@pytest.mark.django_db
def test_database_allows_only_one_default_type_per_project_and_workspace(workspace, create_user):
    from django.db import IntegrityError, transaction

    project = make_project(workspace, create_user, identifier="UQ", governed=False)
    bug = ProjectIssueType.objects.get(project=project, issue_type__key="bug")
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectIssueType.objects.filter(pk=bug.pk).update(is_default=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        IssueType.objects.filter(workspace=workspace, key="bug").update(is_default=True)


# ---------------------------------------------------------------------------
# Workspace level API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_workspace_types(workspace, admin_client):
    response = admin_client.get(ws_types(workspace))
    assert response.status_code == 200
    assert [t["key"] for t in response.data] == ["bug", "task", "story", "epic"]
    assert response.data[1]["is_default"] is True
    assert "projects_count" in response.data[0]


@pytest.mark.django_db
def test_admin_creates_updates_and_deletes_a_type(workspace, admin_client):
    created = admin_client.post(ws_types(workspace), {"name": "Spike", "logo_props": {"icon": "bolt"}}, format="json")
    assert created.status_code == 201, created.data
    assert created.data["key"] == "spike"
    type_id = created.data["id"]

    renamed = admin_client.patch(f"{ws_types(workspace)}{type_id}/", {"name": "Research spike"}, format="json")
    assert renamed.status_code == 200 and renamed.data["name"] == "Research spike"

    changed_key = admin_client.patch(f"{ws_types(workspace)}{type_id}/", {"key": "other"}, format="json")
    assert changed_key.status_code == 400
    assert changed_key.data["error"]["code"] == "key_immutable"

    assert admin_client.delete(f"{ws_types(workspace)}{type_id}/").status_code == 204


@pytest.mark.django_db
def test_duplicate_key_is_rejected(workspace, admin_client):
    response = admin_client.post(ws_types(workspace), {"name": "Bug again", "key": "bug"}, format="json")
    assert response.status_code == 400 and response.data["error"]["code"] == "key_taken"


@pytest.mark.django_db
def test_setting_a_new_default_clears_the_old_one(workspace, admin_client):
    bug = type_of(workspace, "bug")
    response = admin_client.patch(f"{ws_types(workspace)}{bug.id}/", {"is_default": True}, format="json")
    assert response.status_code == 200
    assert IssueType.objects.filter(workspace=workspace, is_default=True).count() == 1
    assert IssueType.objects.get(workspace=workspace, is_default=True).key == "bug"


@pytest.mark.django_db
def test_default_type_cannot_be_deleted(workspace, admin_client):
    task = type_of(workspace, "task")
    response = admin_client.delete(f"{ws_types(workspace)}{task.id}/")
    assert response.status_code == 409 and response.data["error"]["code"] == "default_type_protected"


@pytest.mark.django_db
def test_deleting_a_type_in_use_needs_force_and_moves_items_to_the_default(workspace, project, admin_client):
    story = type_of(workspace, "story")
    issue = make_issue(project, "story", "Backlog")
    blocked = admin_client.delete(f"{ws_types(workspace)}{story.id}/")
    assert blocked.status_code == 409
    assert blocked.data["error"]["code"] == "type_in_use" and blocked.data["error"]["count"] == 1

    forced = admin_client.delete(f"{ws_types(workspace)}{story.id}/?force=true")
    assert forced.status_code == 204
    issue.refresh_from_db()
    assert issue.type.key == "task"


@pytest.mark.django_db
@pytest.mark.parametrize("role", [MEMBER, DEVELOPER, VIEWER])
def test_only_admins_manage_types(role, workspace, project):
    client = client_for(make_user(workspace, project, role))
    assert client.get(ws_types(workspace)).status_code == 200
    assert client.post(ws_types(workspace), {"name": "Nope"}, format="json").status_code == 403
    assert client.delete(f"{ws_types(workspace)}{type_of(workspace, 'bug').id}/").status_code == 403


# ---------------------------------------------------------------------------
# Project level API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_project_lists_its_types(workspace, project, admin_client):
    response = admin_client.get(proj_types(workspace, project))
    assert response.status_code == 200
    assert [r["issue_type"]["key"] for r in response.data] == ["bug", "task", "story", "epic"]
    assert all(r["is_enabled"] for r in response.data)


@pytest.mark.django_db
def test_disabled_project_reports_types_as_disabled_and_refuses_changes(workspace, create_user):
    project = make_project(workspace, create_user, identifier="OFF", governed=False)
    client = client_for(create_user)
    listed = client.get(proj_types(workspace, project))
    assert listed.status_code == 200 and not any(r["is_enabled"] for r in listed.data)

    refused = client.post(
        proj_types(workspace, project), {"issue_type_id": str(type_of(workspace, "bug").id)}, format="json"
    )
    assert refused.status_code == 400 and refused.data["error"]["code"] == "types_disabled"


@pytest.mark.django_db
def test_enable_endpoint_turns_on_types_and_workflows(workspace, create_user):
    from plane.db.models import Project, Workflow

    project = make_project(workspace, create_user, identifier="EN", governed=False)
    response = client_for(create_user).post(proj_types(workspace, project) + "enable/")
    assert response.status_code == 200 and response.data["is_issue_type_enabled"] is True
    assert Project.objects.get(pk=project.pk).is_issue_type_enabled
    assert Workflow.objects.filter(project=project).count() == 4

    off = client_for(create_user).post(proj_types(workspace, project) + "disable/")
    assert off.status_code == 200 and not Project.objects.get(pk=project.pk).is_issue_type_enabled
    assert Workflow.objects.filter(project=project).count() == 4  # nothing is deleted


@pytest.mark.django_db
def test_project_default_switches_atomically_and_cannot_be_disabled(workspace, project, admin_client):
    rows = {r.issue_type.key: r for r in ProjectIssueType.objects.filter(project=project).select_related("issue_type")}
    switched = admin_client.patch(
        f"{proj_types(workspace, project)}{rows['bug'].id}/", {"is_default": True}, format="json"
    )
    assert switched.status_code == 200
    assert ProjectIssueType.objects.filter(project=project, is_default=True).count() == 1
    assert ProjectIssueType.objects.get(project=project, is_default=True).issue_type.key == "bug"

    refused = admin_client.delete(f"{proj_types(workspace, project)}{rows['bug'].id}/")
    assert refused.status_code == 409 and refused.data["error"]["code"] == "default_type_protected"

    disabled = admin_client.delete(f"{proj_types(workspace, project)}{rows['story'].id}/")
    assert disabled.status_code == 204
    assert not ProjectIssueType.objects.get(pk=rows["story"].pk).is_enabled


@pytest.mark.django_db
def test_reorder(workspace, project, admin_client):
    rows = list(ProjectIssueType.objects.filter(project=project).order_by("level"))
    ids = [str(r.id) for r in reversed(rows)]
    assert (
        admin_client.post(proj_types(workspace, project) + "reorder/", {"ids": ids}, format="json").status_code == 204
    )
    ordered = list(ProjectIssueType.objects.filter(project=project).order_by("level").values_list("id", flat=True))
    assert [str(i) for i in ordered] == ids


# ---------------------------------------------------------------------------
# Work item payloads
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_without_type_gets_the_project_default(workspace, project, admin_client):
    response = admin_client.post(issues(workspace, project), {"name": "plain"}, format="json")
    assert response.status_code == 201, response.data
    assert Issue.objects.get(project=project, name="plain").type.key == "task"


@pytest.mark.django_db
def test_create_with_type_id_and_update_type(workspace, project, admin_client):
    bug = type_of(workspace, "bug")
    created = admin_client.post(issues(workspace, project), {"name": "a bug", "type_id": str(bug.id)}, format="json")
    assert created.status_code == 201, created.data
    issue = Issue.objects.get(project=project, name="a bug")
    assert issue.type.key == "bug"

    task = type_of(workspace, "task")
    patched = admin_client.patch(f"{issues(workspace, project)}{issue.id}/", {"type_id": str(task.id)}, format="json")
    assert patched.status_code == 204, getattr(patched, "data", None)
    issue.refresh_from_db()
    assert issue.type.key == "task"


@pytest.mark.django_db
def test_type_must_be_enabled_in_the_project(workspace, project, admin_client):
    story_row = ProjectIssueType.objects.get(project=project, issue_type__key="story")
    story_row.is_enabled = False
    story_row.save()
    response = admin_client.post(
        issues(workspace, project), {"name": "x", "type_id": str(type_of(workspace, "story").id)}, format="json"
    )
    assert response.status_code == 400
    assert response.data["error"]["code"] == "type_not_enabled"


@pytest.mark.django_db
def test_disabled_project_behaves_like_before(workspace, create_user):
    project = make_project(workspace, create_user, identifier="OLD", governed=False)
    client = client_for(create_user)
    response = client.post(issues(workspace, project), {"name": "legacy item"}, format="json")
    assert response.status_code == 201, response.data
    assert Issue.objects.get(project=project, name="legacy item").type_id is None

    refused = client.post(
        issues(workspace, project), {"name": "typed", "type_id": str(type_of(workspace, "bug").id)}, format="json"
    )
    assert refused.status_code == 400 and refused.data["error"]["code"] == "types_disabled"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "parent_key,child_key,allowed",
    [
        ("epic", "story", True),
        ("epic", "task", True),
        ("epic", "bug", True),
        ("story", "task", True),
        ("story", "bug", True),
        ("task", "story", False),
        ("bug", "story", False),
        ("task", "epic", False),
        ("bug", "epic", False),
        ("story", "epic", False),
    ],
)
def test_parent_child_type_rules(parent_key, child_key, allowed, workspace, project, admin_client):
    parent = make_issue(project, parent_key, name="parent")
    response = admin_client.post(
        issues(workspace, project),
        {"name": "child", "type_id": str(type_of(workspace, child_key).id), "parent_id": str(parent.id)},
        format="json",
    )
    if allowed:
        assert response.status_code == 201, response.data
    else:
        assert response.status_code == 400
        assert response.data["error"]["code"] == "invalid_parent_type"


@pytest.mark.django_db
def test_list_and_detail_responses_carry_the_type_id(workspace, project, admin_client):
    bug = make_issue(project, "bug", "New")
    listed = admin_client.get(issues(workspace, project))
    assert listed.status_code == 200, listed.data
    rows = listed.data["results"] if isinstance(listed.data, dict) and "results" in listed.data else listed.data
    flat = rows if isinstance(rows, list) else [r for g in rows.values() for r in (g if isinstance(g, list) else [])]
    assert any(str(r.get("type_id")) == str(bug.type_id) for r in flat), listed.data

    detail = admin_client.get(f"{issues(workspace, project)}{bug.id}/")
    assert detail.status_code == 200
    assert str(detail.data["type_id"]) == str(bug.type_id)


@pytest.mark.django_db
def test_issues_can_be_filtered_by_type(workspace, project, admin_client):
    bug = make_issue(project, "bug", "New", name="a bug")
    make_issue(project, "task", "New", name="a task")
    bug_type = type_of(workspace, "bug")

    legacy = admin_client.get(f"{issues(workspace, project)}?issue_type={bug_type.id}&per_page=50")
    assert legacy.status_code == 200, legacy.data
    results = legacy.data["results"]
    flat = results if isinstance(results, list) else [r for g in results.values() for r in g]
    assert {str(r["id"]) for r in flat} == {str(bug.id)}

    rich = admin_client.get(f'{issues(workspace, project)}?filters={{"type_id__in":"{bug_type.id}"}}&per_page=50')
    assert rich.status_code == 200, rich.data


@pytest.mark.django_db
def test_epic_type_linked_from_a_module_cannot_be_deleted(workspace, project, admin_client):
    epic = make_issue(project, "epic", name="Guarded epic")
    Module.objects.create(name="Checkout", project=project, workspace=workspace, epic=epic)

    response = admin_client.delete(f"{ws_types(workspace)}{epic.type_id}/")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "epic_type_in_use"
    assert response.data["error"]["count"] == 1
    assert IssueType.objects.filter(pk=epic.type_id).exists()

    Module.objects.filter(epic=epic).update(epic=None)
    assert admin_client.delete(f"{ws_types(workspace)}{epic.type_id}/").status_code == 204
    assert not IssueType.objects.filter(pk=epic.type_id).exists()
