# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Seed Bug / Task / Story / Epic for every existing workspace and project (PLN-004).

Idempotent. This does NOT turn work item types on for any project
(``Project.is_issue_type_enabled`` is left as it is) and it does not touch work items.
Backfilling ``issues.type_id`` is a separate, reportable step:

    python manage.py backfill_issue_types --project <identifier>
"""

from django.db import migrations

# Copied here on purpose: migrations must not depend on application code that can change.
DEFAULT_TYPES = [
    ("bug", "Bug", 0, False, False, "bug", "#EF4444", "Something is broken or behaves incorrectly."),
    ("task", "Task", 1, False, True, "task", "#3B82F6", "A unit of work."),
    ("story", "Story", 2, False, False, "story", "#10B981", "A user facing piece of functionality."),
    ("epic", "Epic", 3, True, False, "epic", "#8B5CF6", "A large body of work made of stories and tasks."),
]


def seed(apps, schema_editor):
    Workspace = apps.get_model("db", "Workspace")
    Project = apps.get_model("db", "Project")
    IssueType = apps.get_model("db", "IssueType")
    ProjectIssueType = apps.get_model("db", "ProjectIssueType")

    for workspace in Workspace.objects.all().iterator():
        types = {}
        for key, name, level, is_epic, is_default, icon, color, description in DEFAULT_TYPES:
            issue_type = IssueType.objects.filter(workspace=workspace, key=key, deleted_at__isnull=True).first()
            if issue_type is None:
                issue_type = IssueType.objects.create(
                    workspace=workspace, key=key, name=name, level=level, is_epic=is_epic,
                    is_default=is_default, is_active=True, description=description,
                    logo_props={"icon": icon, "color": color},
                )
            types[key] = issue_type

        for project in Project.objects.filter(workspace=workspace).iterator():
            for key, name, level, is_epic, is_default, icon, color, description in DEFAULT_TYPES:
                exists = ProjectIssueType.objects.filter(
                    project=project, issue_type=types[key], deleted_at__isnull=True
                ).exists()
                if not exists:
                    ProjectIssueType.objects.create(
                        project=project, workspace=workspace, issue_type=types[key],
                        level=level, is_default=key == "task", is_enabled=True,
                    )


class Migration(migrations.Migration):
    dependencies = [("db", "0128_work_item_type_keys_and_workflows")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
