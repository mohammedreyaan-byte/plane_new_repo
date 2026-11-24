# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.utils.permissions.capabilities import (
    SYSTEM_ROLE_CAPABILITIES,
    get_role_capabilities,
    get_user_project_role,
    get_user_workspace_role,
    has_capability,
)

pytestmark = pytest.mark.unit

ROLE_KEYS = {"admin", "member", "developer", "qa", "viewer", "guest"}


def test_six_system_roles_exist():
    assert set(SYSTEM_ROLE_CAPABILITIES) == ROLE_KEYS


def test_admin_and_member_matrix():
    admin = SYSTEM_ROLE_CAPABILITIES["admin"]
    member = SYSTEM_ROLE_CAPABILITIES["member"]
    assert "member.manage" in admin
    assert "member.manage" not in member
    for capability in ["type.manage", "workflow.manage", "integration.manage", "service_token.manage"]:
        assert capability in admin
        assert capability not in member
    # Legacy Member keeps everything else it could do before.
    assert "work_item.create" in member and "work_item.transition" in member


def test_developer_qa_viewer_guest_matrix():
    developer = set(SYSTEM_ROLE_CAPABILITIES["developer"])
    assert {"work_item.view", "work_item.create", "work_item.edit", "work_item.transition"} <= developer
    assert "project.manage" not in developer and "cycle.manage" not in developer

    assert set(SYSTEM_ROLE_CAPABILITIES["qa"]) == developer

    viewer = set(SYSTEM_ROLE_CAPABILITIES["viewer"])
    assert viewer == {"work_item.view", "comment.read", "report.view"}

    guest = set(SYSTEM_ROLE_CAPABILITIES["guest"])
    assert guest == {"work_item.view", "work_item.edit", "comment.create"}


@pytest.mark.parametrize(
    "legacy_id,key",
    [(20, "admin"), (15, "member"), (12, "developer"), (11, "qa"), (2, "viewer"), (5, "guest")],
)
def test_legacy_integer_resolves_to_same_capabilities(legacy_id, key):
    assert get_role_capabilities(legacy_id) == set(SYSTEM_ROLE_CAPABILITIES[key])


@pytest.mark.django_db
def test_project_role_overrides_workspace_role(create_user, workspace):
    from plane.db.models import Project, ProjectMember, User, WorkspaceMember

    developer = User.objects.create(email="developer@plane.so", username="developer", first_name="Dev", last_name="User")
    WorkspaceMember.objects.create(workspace=workspace, member=developer, role=15)
    project = Project.objects.create(name="Role Project", identifier="ROLE", workspace=workspace)
    ProjectMember.objects.create(workspace=workspace, project=project, member=developer, role=12)

    assert get_user_workspace_role(developer, workspace).key == "member"
    assert get_user_project_role(developer, workspace, project).key == "developer"
    assert has_capability(developer, workspace, "work_item.edit", project=project)
    assert not has_capability(developer, workspace, "member.manage", project=project)


@pytest.mark.django_db
def test_workspace_admin_overrides_project_role(create_user, workspace):
    from plane.db.models import Project, ProjectMember

    project = Project.objects.create(name="Admin Project", identifier="ADM", workspace=workspace)
    ProjectMember.objects.create(workspace=workspace, project=project, member=create_user, role=2)

    assert get_user_project_role(create_user, workspace, project).key == "admin"
    assert has_capability(create_user, workspace, "member.manage", project=project)
