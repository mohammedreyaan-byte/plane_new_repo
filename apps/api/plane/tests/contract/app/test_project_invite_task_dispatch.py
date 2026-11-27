# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.urls import reverse

from plane.db.models import Project, ProjectMember


@pytest.fixture
def project(db, workspace, create_user):
    created = Project.objects.create(
        name="Invite Project",
        identifier="INV",
        workspace=workspace,
        created_by=create_user,
    )
    ProjectMember.objects.create(project=created, member=create_user, workspace=workspace, role=20)
    return created


@pytest.mark.contract
@pytest.mark.django_db
def test_project_invitation_is_dispatched_as_a_task(session_client, create_user, project, mocker):
    delay = mocker.patch("plane.app.views.project.invite.project_invitation.delay")

    response = session_client.post(
        reverse(
            "project-member-invite",
            kwargs={"slug": project.workspace.slug, "project_id": project.pk},
        ),
        {"emails": [{"email": "invitee@example.invalid", "role": 5}]},
        format="json",
    )

    assert response.status_code == 200
    delay.assert_called_once()
    args = delay.call_args.args
    assert args[0] == "invitee@example.invalid"
    assert str(args[1]) == str(project.pk)
    assert args[4] == create_user.email
