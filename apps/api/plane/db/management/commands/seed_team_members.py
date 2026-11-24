# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Seed workspace and project members from a CSV file.

CSV columns: email, first_name, last_name, workspace_role, project_role

Example:
    python manage.py seed_team_members --workspace greenmen-consulting \
        --project SDLC --file team.csv

Roles accept a role key (admin, member, developer, qa, viewer, guest) or the
legacy integer. Re-running the command is safe: memberships are updated, not
duplicated.
"""

import csv

from django.core.management.base import BaseCommand, CommandError

from plane.db.models import Project, ProjectMember, User, Workspace, WorkspaceMember
from plane.utils.permissions.capabilities import LEGACY_ID_TO_KEY, resolve_role


class Command(BaseCommand):
    help = "Create or update workspace and project members from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace slug")
        parser.add_argument("--file", required=True, help="Path to the CSV file")
        parser.add_argument("--project", default="SDLC", help="Project identifier (default: SDLC)")

    def _resolve_role(self, workspace, value, default_key):
        value = (value or "").strip().lower() or default_key
        key = LEGACY_ID_TO_KEY.get(int(value)) if value.isdigit() else value
        role = resolve_role(workspace, key)
        if role is None:
            raise CommandError(f"Unknown role: {value}")
        return role

    def handle(self, *args, **options):
        workspace = Workspace.objects.filter(slug=options["workspace"]).first()
        if workspace is None:
            raise CommandError(f"Workspace not found: {options['workspace']}")

        project = Project.objects.filter(workspace=workspace, identifier=options["project"]).first()
        if project is None:
            raise CommandError(f"Project not found: {options['project']}")

        created_users = 0
        workspace_memberships = 0
        project_memberships = 0

        with open(options["file"], newline="", encoding="utf-8-sig") as csv_file:
            for row in csv.DictReader(csv_file):
                email = (row.get("email") or "").strip().lower()
                if not email:
                    continue

                user, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "first_name": (row.get("first_name") or "").strip(),
                        "last_name": (row.get("last_name") or "").strip(),
                    },
                )
                if created:
                    user.set_unusable_password()
                    user.save()
                    created_users += 1

                workspace_role = self._resolve_role(workspace, row.get("workspace_role"), "member")
                WorkspaceMember.objects.update_or_create(
                    workspace=workspace,
                    member=user,
                    defaults={
                        "role": workspace_role.legacy_id,
                        "role_ref": workspace_role,
                        "is_active": True,
                    },
                )
                workspace_memberships += 1

                project_role = self._resolve_role(workspace, row.get("project_role"), "member")
                ProjectMember.objects.update_or_create(
                    workspace=workspace,
                    project=project,
                    member=user,
                    defaults={
                        "role": project_role.legacy_id,
                        "role_ref": project_role,
                        "is_active": True,
                    },
                )
                project_memberships += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Users created: {created_users}; workspace memberships: {workspace_memberships}; "
                f"project memberships: {project_memberships}"
            )
        )
