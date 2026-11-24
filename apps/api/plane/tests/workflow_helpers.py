# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared builders for the work item type and workflow tests."""

from uuid import uuid4

from rest_framework.test import APIClient

from plane.db.models import (
    Issue,
    IssueType,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.utils.workflow.service import seed_project_workflows

ADMIN, MEMBER, DEVELOPER, QA, GUEST, VIEWER = 20, 15, 12, 11, 5, 2
ROLE_KEYS = {ADMIN: "admin", MEMBER: "member", DEVELOPER: "developer", QA: "qa", GUEST: "guest", VIEWER: "viewer"}


def make_user(workspace, project, role):
    suffix = uuid4().hex[:8]
    user = User.objects.create(
        email=f"r{role}-{suffix}@plane.so", username=f"r{role}_{suffix}", first_name="R", last_name=str(role)
    )
    user.set_password("test-password")
    user.save()
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_project(workspace, owner, identifier="WF", governed=True):
    """A project with its owner as admin; optionally with types + workflows switched on."""
    project = Project.objects.create(
        name=f"Project {identifier}", identifier=identifier, workspace=workspace, created_by=owner
    )
    ProjectMember.objects.create(project=project, member=owner, workspace=workspace, role=ADMIN)
    State.objects.create(name="Todo", project=project, workspace=workspace, group="unstarted", default=True)
    if governed:
        seed_project_workflows(project)
        Project.objects.filter(pk=project.pk).update(is_issue_type_enabled=True)
        project.refresh_from_db()
    return project


def type_of(workspace, key):
    return IssueType.objects.get(workspace=workspace, key=key)


def state_of(project, name):
    return State.objects.get(project=project, name=name)


def make_issue(project, issue_type_key, state_name=None, name="Item", parent=None):
    """Create a work item straight in the DB (no engine), in the named state."""
    issue_type = type_of(project.workspace, issue_type_key)
    state = state_of(project, state_name) if state_name else None
    issue = Issue(project=project, workspace=project.workspace, name=name, type=issue_type, parent=parent)
    if state:
        issue.state = state
    issue.save()
    return issue
