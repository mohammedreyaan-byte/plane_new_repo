# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Default work item types (PLN-004).

Every workspace gets Bug, Task, Story and Epic. Every project gets all four enabled,
with Task as the default type. Both helpers are idempotent, so they are safe to call from
signals, management commands and data migrations.
"""

from django.db import transaction

DEFAULT_ISSUE_TYPES = [
    {
        "key": "bug",
        "name": "Bug",
        "level": 0,
        "is_epic": False,
        "icon": "bug",
        "color": "#EF4444",
        "description": "Something is broken or behaves incorrectly.",
    },
    {
        "key": "task",
        "name": "Task",
        "level": 1,
        "is_epic": False,
        "icon": "task",
        "color": "#3B82F6",
        "description": "A unit of work.",
        "is_default": True,
    },
    {
        "key": "story",
        "name": "Story",
        "level": 2,
        "is_epic": False,
        "icon": "story",
        "color": "#10B981",
        "description": "A user facing piece of functionality.",
    },
    {
        "key": "epic",
        "name": "Epic",
        "level": 3,
        "is_epic": True,
        "icon": "epic",
        "color": "#8B5CF6",
        "description": "A large body of work made of stories and tasks.",
    },
]

DEFAULT_TYPE_KEY = "task"


@transaction.atomic
def ensure_workspace_issue_types(workspace):
    """Create the four default types for a workspace. Returns {key: IssueType}."""
    from plane.db.models import IssueType

    types = {}
    for spec in DEFAULT_ISSUE_TYPES:
        issue_type = IssueType.objects.filter(workspace=workspace, key=spec["key"]).first()
        if issue_type is None:
            issue_type = IssueType.objects.create(
                workspace=workspace,
                key=spec["key"],
                name=spec["name"],
                description=spec["description"],
                logo_props={"icon": spec["icon"], "color": spec["color"]},
                is_epic=spec["is_epic"],
                is_default=spec.get("is_default", False),
                is_active=True,
                level=spec["level"],
            )
        types[spec["key"]] = issue_type
    return types


@transaction.atomic
def ensure_project_issue_types(project):
    """Enable all workspace types on a project. Returns {key: ProjectIssueType}."""
    from plane.db.models import ProjectIssueType

    types = ensure_workspace_issue_types(project.workspace)
    rows = {}
    for spec in DEFAULT_ISSUE_TYPES:
        issue_type = types[spec["key"]]
        row = ProjectIssueType.objects.filter(project=project, issue_type=issue_type).first()
        if row is None:
            row = ProjectIssueType.objects.create(
                project=project,
                issue_type=issue_type,
                level=spec["level"],
                is_default=spec["key"] == DEFAULT_TYPE_KEY,
                is_enabled=True,
            )
        rows[spec["key"]] = row
    return rows


def get_default_issue_type(project_id):
    """The enabled default type of a project, or None when types are not set up."""
    from plane.db.models import ProjectIssueType

    row = (
        ProjectIssueType.objects.filter(project_id=project_id, is_default=True, is_enabled=True)
        .select_related("issue_type")
        .first()
    )
    return row.issue_type if row else None


def is_type_enabled_in_project(project_id, issue_type_id):
    from plane.db.models import ProjectIssueType

    return ProjectIssueType.objects.filter(
        project_id=project_id, issue_type_id=issue_type_id, is_enabled=True, issue_type__is_active=True
    ).exists()
