# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Turn work item types and workflows on for one project (explicit rollout step).

    python manage.py enable_work_item_types --workspace <slug> --project <IDENTIFIER>
    python manage.py enable_work_item_types --workspace <slug> --project <IDENTIFIER> --reset

Creates the types, the four built-in workflows (Bug, Task, Story, Epic) and their states, then
sets ``is_issue_type_enabled``. Existing work items are not changed: run ``backfill_issue_types``
next. Safe to re-run. With ``--reset`` the built-in transition matrices are restored.
"""

import json

from django.core.management import BaseCommand, CommandError

from plane.db.models import Project
from plane.utils.workflow.service import seed_project_workflows


class Command(BaseCommand):
    help = "Enable work item types and the built-in workflows on a project."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace slug")
        parser.add_argument("--project", required=True, help="Project identifier")
        parser.add_argument("--reset", action="store_true", help="Restore the built-in transition matrices")

    def handle(self, *args, **options):
        project = Project.objects.filter(workspace__slug=options["workspace"], identifier=options["project"]).first()
        if project is None:
            raise CommandError("Project not found.")

        summary = seed_project_workflows(project, reset=options["reset"])
        if not project.is_issue_type_enabled:
            Project.objects.filter(pk=project.pk).update(is_issue_type_enabled=True)
        self.stdout.write(json.dumps({"project": project.identifier, "enabled": True, "workflows": summary}, indent=2))
