# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from rest_framework.test import APIClient

from plane.db.models import Project, ProjectMember, Role, RoleAuditLog, User, WorkspaceMember, WorkspaceMemberInvite
from plane.utils.permissions.capabilities import KEY_TO_LEGACY_ID, SYSTEM_ROLE_CAPABILITIES

pytestmark = pytest.mark.contract


def _seed_roles():
    # The repo's pytest configuration disables data migrations; supply the
    # system role rows this API normally receives from migration 0125.
    for key in ("admin", "developer", "guest"):
        Role.objects.update_or_create(
            workspace=None,
            key=key,
            defaults={
                "name": key.title(),
                "legacy_id": KEY_TO_LEGACY_ID[key],
                "capabilities": list(SYSTEM_ROLE_CAPABILITIES[key]),
                "is_system": True,
                "is_active": True,
            },
        )


@pytest.mark.django_db
def test_bulk_invite_reports_each_address_and_deduplicates(workspace, create_user, mocker):
    _seed_roles()
    from plane.app.views.workspace.invite import track_event, workspace_invitation

    mocker.patch.object(workspace_invitation, "delay")
    mocker.patch.object(track_event, "delay")
    existing = User.objects.create(
        username="already-member", email="already@example.com", first_name="Existing", last_name="Member"
    )
    WorkspaceMember.objects.create(workspace=workspace, member=existing, role=15)
    client = APIClient()
    client.force_authenticate(user=create_user)

    response = client.post(
        f"/api/workspaces/{workspace.slug}/invitations/bulk/",
        {
            "emails": [
                {"email": "new@example.com", "role_key": "developer"},
                {"email": "bad-address", "role_key": "developer"},
                {"email": "already@example.com", "role_key": "developer"},
                {"email": "new@example.com", "role_key": "developer"},
                {"email": "unknown@example.com", "role_key": "not-a-role"},
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert [row["status"] for row in response.data["results"]] == [
        "invited",
        "invalid",
        "already_member",
        "already_member",
        "invalid",
    ], response.data
    assert all("member_id" in row for row in response.data["results"])
    assert response.data["results"][0]["member_id"] is not None
    assert response.data["results"][1]["member_id"] is None
    assert response.data["results"][2]["member_id"] == str(WorkspaceMember.objects.get(member=existing).id)
    assert response.data["invited"] == 1
    assert response.data["failed"] == 4
    invitation = WorkspaceMemberInvite.objects.get(workspace=workspace, email="new@example.com")
    assert response.data["results"][0]["member_id"] == str(invitation.id)
    assert invitation.role_ref.key == "developer"
    assert WorkspaceMemberInvite.objects.filter(workspace=workspace, email="unknown@example.com").count() == 0


@pytest.mark.django_db
def test_bulk_invite_requires_workspace_admin(workspace, create_user):
    _seed_roles()
    from plane.db.models import User, WorkspaceMember

    member = User.objects.create(
        username="regular-member", email="member@example.com", first_name="Regular", last_name="Member"
    )
    WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
    client = APIClient()
    client.force_authenticate(user=member)

    response = client.post(
        f"/api/workspaces/{workspace.slug}/invitations/bulk/",
        {"emails": [{"email": "new@example.com", "role_key": "guest"}]},
        format="json",
    )

    assert response.status_code == 403
    assert not WorkspaceMemberInvite.objects.filter(workspace=workspace, email="new@example.com").exists()


@pytest.mark.django_db
def test_single_invite_rejects_unknown_and_conflicting_roles(workspace, create_user, mocker):
    _seed_roles()
    from plane.app.views.workspace.invite import track_event, workspace_invitation

    mocker.patch.object(workspace_invitation, "delay")
    mocker.patch.object(track_event, "delay")
    client = APIClient()
    client.force_authenticate(user=create_user)

    unknown = client.post(
        f"/api/workspaces/{workspace.slug}/invitations/",
        {"emails": [{"email": "unknown@example.com", "role_key": "not-a-role"}]},
        format="json",
    )
    assert unknown.status_code == 400
    assert "role_key" in unknown.data

    conflict = client.post(
        f"/api/workspaces/{workspace.slug}/invitations/",
        {"emails": [{"email": "conflict@example.com", "role_key": "developer", "role": 5}]},
        format="json",
    )
    assert conflict.status_code == 400
    assert conflict.data["code"] == "role_key_conflict"
    assert not WorkspaceMemberInvite.objects.filter(
        workspace=workspace, email__in=["unknown@example.com", "conflict@example.com"]
    ).exists()


@pytest.mark.django_db
def test_resend_rotates_token_and_sends_pending_invitation(workspace, create_user, mocker):
    _seed_roles()
    from plane.app.views.workspace.invite import workspace_invitation

    send = mocker.patch.object(workspace_invitation, "delay")
    invitation = WorkspaceMemberInvite.objects.create(
        email="pending@example.com",
        workspace=workspace,
        token="old-token",
        role=5,
        created_by=create_user,
    )
    client = APIClient()
    client.force_authenticate(user=create_user)

    response = client.post(f"/api/workspaces/{workspace.slug}/invitations/{invitation.id}/resend/", {}, format="json")

    assert response.status_code == 200, response.data
    invitation.refresh_from_db()
    assert invitation.token != "old-token"
    send.assert_called_once()


@pytest.mark.django_db
def test_workspace_member_removal_writes_role_audit_log(workspace, create_user):
    _seed_roles()
    target = User.objects.create(
        email="admin-target@example.com", username="admin-target", first_name="Admin", last_name="Target"
    )
    membership = WorkspaceMember.objects.create(workspace=workspace, member=target, role=20)
    client = APIClient()
    client.force_authenticate(user=create_user)

    response = client.delete(f"/api/workspaces/{workspace.slug}/members/{membership.id}/")

    assert response.status_code == 204, response.data
    log = RoleAuditLog.objects.get(scope=RoleAuditLog.SCOPE_WORKSPACE, target_id=target.id)
    assert log.old_role == "admin"
    assert log.new_role == ""


@pytest.mark.django_db
def test_project_bulk_add_rejects_role_above_workspace_role(workspace, create_user):
    _seed_roles()
    project = Project.objects.create(
        name="Bulk role project", identifier="BR", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    guest = User.objects.create(
        email="project-guest@example.com", username="project-guest", first_name="Project", last_name="Guest"
    )
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
    client = APIClient()
    client.force_authenticate(user=create_user)

    response = client.post(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/members/",
        {"members": [{"member_id": str(guest.id), "role_key": "admin"}]},
        format="json",
    )

    assert response.status_code == 400
    assert "higher than the workspace role" in response.data["error"]
