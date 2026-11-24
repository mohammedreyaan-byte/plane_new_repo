# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Module imports
from plane.db.models import IssueType

# Jira-style default issue types. `icon` is the key the web app maps to an SVG.
DEFAULT_ISSUE_TYPES = [
    {
        "name": "Epic",
        "description": "A big chunk of work that can be broken down into stories and tasks.",
        "icon": "epic",
        "color": "#904EE2",
        "is_epic": True,
        "is_default": False,
        "level": 1,
    },
    {
        "name": "Story",
        "description": "A user-facing feature or requirement.",
        "icon": "story",
        "color": "#4BAE4F",
        "is_epic": False,
        "is_default": False,
        "level": 0,
    },
    {
        "name": "Task",
        "description": "A piece of work that needs to be done.",
        "icon": "task",
        "color": "#2684FF",
        "is_epic": False,
        "is_default": True,
        "level": 0,
    },
    {
        "name": "Bug",
        "description": "A problem that impairs or prevents functionality.",
        "icon": "bug",
        "color": "#E5493A",
        "is_epic": False,
        "is_default": False,
        "level": 0,
    },
    {
        "name": "Sub-task",
        "description": "A smaller piece of work that belongs to another issue.",
        "icon": "subtask",
        "color": "#4F9CF9",
        "is_epic": False,
        "is_default": False,
        "level": -1,
    },
]


def ensure_default_issue_types(workspace):
    """Create the default Jira-style issue types for a workspace if it has none.

    Safe to call repeatedly. Returns the workspace's active issue types.
    """
    if not IssueType.objects.filter(workspace=workspace).exists():
        IssueType.objects.bulk_create(
            [
                IssueType(
                    workspace=workspace,
                    name=item["name"],
                    description=item["description"],
                    logo_props={"in_use": "icon", "icon": {"name": item["icon"], "color": item["color"]}},
                    is_epic=item["is_epic"],
                    is_default=item["is_default"],
                    level=item["level"],
                )
                for item in DEFAULT_ISSUE_TYPES
            ]
        )
    return IssueType.objects.filter(workspace=workspace, is_active=True)


def get_default_issue_type(workspace):
    """Return the workspace's default issue type (Task), seeding types if needed."""
    types = ensure_default_issue_types(workspace)
    return types.filter(is_default=True).first() or types.first()
