# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared fixtures for PLN-015 project-isolation authorization tests."""

from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, User, Workspace, WorkspaceMember

ADMIN = 20
MEMBER = 15
GUEST = 5


def make_user(prefix):
    suffix = uuid4().hex[:10]
    user = User.objects.create(
        email=f"{prefix}-{suffix}@example.com",
        username=f"{prefix}_{suffix}",
        first_name=prefix.title(),
        last_name="User",
        is_active=True,
    )
    user.set_password("test-password")
    user.save()
    return user


def make_workspace(name, owner):
    return Workspace.objects.create(
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        owner=owner,
    )


def make_project(name, identifier, workspace, created_by):
    return Project.objects.create(
        name=name,
        identifier=identifier,
        workspace=workspace,
        created_by=created_by,
        guest_view_all_features=False,
    )


def add_workspace_member(workspace, user, role):
    return WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)


def add_project_member(project, user, role):
    return ProjectMember.objects.create(project=project, workspace=project.workspace, member=user, role=role)


def make_issue(name, project, author):
    """Create an issue with an explicit ``created_by`` (see existing tests)."""
    issue = Issue(name=name, project=project, workspace=project.workspace)
    issue.save(created_by_id=author.id)
    return issue


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def isolation_context(db):
    """Two projects in one workspace plus one project in another workspace."""
    suffix = uuid4().hex[:6].upper()

    owner = make_user("owner")
    member = make_user("member")
    guest = make_user("guest")
    outsider = make_user("outsider")
    service_user = make_user("service")

    workspace = make_workspace(f"Isolation {suffix}", owner)
    other_workspace = make_workspace(f"Other {suffix}", owner)

    project_a = make_project(f"Alpha {suffix}", f"PA{suffix[:4]}", workspace, owner)
    project_b = make_project(f"Beta {suffix}", f"PB{suffix[:4]}", workspace, owner)
    foreign_project = make_project(f"Foreign {suffix}", f"FX{suffix[:4]}", other_workspace, owner)

    for user in (owner, member, guest, outsider, service_user):
        add_workspace_member(workspace, user, ADMIN if user == owner else MEMBER)

    add_project_member(project_a, owner, ADMIN)
    add_project_member(project_a, member, MEMBER)
    add_project_member(project_a, guest, GUEST)
    add_project_member(project_b, owner, ADMIN)
    add_project_member(foreign_project, owner, ADMIN)

    # The service identity is a member everywhere so token scope, not
    # membership, is the only reason a restricted request can fail.
    add_project_member(project_a, service_user, MEMBER)
    add_project_member(project_b, service_user, MEMBER)
    add_project_member(foreign_project, service_user, MEMBER)

    issue_a = make_issue("Alpha issue", project_a, owner)
    issue_b = make_issue("Beta issue", project_b, owner)
    guest_issue = make_issue("Guest issue", project_a, guest)
    foreign_issue = make_issue("Foreign issue", foreign_project, owner)

    return {
        "workspace": workspace,
        "other_workspace": other_workspace,
        "project_a": project_a,
        "project_b": project_b,
        "foreign_project": foreign_project,
        "owner": owner,
        "member": member,
        "guest": guest,
        "outsider": outsider,
        "service_user": service_user,
        "issue_a": issue_a,
        "issue_b": issue_b,
        "guest_issue": guest_issue,
        "foreign_issue": foreign_issue,
        "owner_client": client_for(owner),
        "member_client": client_for(member),
        "guest_client": client_for(guest),
        "outsider_client": client_for(outsider),
    }
