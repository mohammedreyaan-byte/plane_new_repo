# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Idempotent seed of standard shared Views for PLN-007 (type filters/grouping/views).

Usage:
    python manage.py seed_standard_views --workspace <workspace-slug-or-id>

Creates (or updates, never duplicates) four public standard views per project in the
workspace that has an enabled Bug work item type:

    My open bugs        type Bug, state group unstarted+started
    Ready for testing   type Bug, state In Testing
    Reopened            type Bug, state Reopened
    Sprint scope        current cycle, all types

All views are public (shared) with stable names; re-running updates the filters in
place instead of creating duplicates. "My open bugs" is intentionally left without a
hard-coded assignee so each member's first open resolves "current user" dynamically.
"""

from django.core.management import BaseCommand, CommandError
from django.db import transaction

from plane.db.models import IssueType, IssueView, Project, Workspace


STANDARD_VIEWS = [
    {
        "name": "My open bugs",
        "description": "Open Bug work items across unstarted and started states.",
        "filters": {"type_id__in": [], "state__group": ["unstarted", "started"]},
        "display_properties": {
            "issue_type": True,
            "key": True,
            "name": True,
            "state": True,
            "assignee": True,
            "priority": True,
            "updated_on": True,
        },
    },
    {
        "name": "Ready for testing",
        "description": "Bug work items waiting in In Testing.",
        "filters": {"type_id__in": [], "state": []},
        "display_properties": {
            "issue_type": True,
            "key": True,
            "name": True,
            "state": True,
            "assignee": True,
            "updated_on": True,
        },
    },
    {
        "name": "Reopened",
        "description": "Bug work items that have been reopened.",
        "filters": {"type_id__in": [], "state": []},
        "display_properties": {
            "issue_type": True,
            "key": True,
            "name": True,
            "state": True,
            "assignee": True,
            "updated_on": True,
        },
    },
    {
        "name": "Sprint scope",
        "description": "Current cycle scope across all work item types.",
        "filters": {},
        "display_properties": {
            "issue_type": True,
            "key": True,
            "name": True,
            "state": True,
            "assignee": True,
            "priority": True,
            "due_date": True,
            "updated_on": True,
        },
    },
]


def _resolve_workspace(value):
    try:
        return Workspace.objects.get(pk=value)
    except (ValueError, Workspace.DoesNotExist):
        pass
    try:
        return Workspace.objects.get(slug=value)
    except Workspace.DoesNotExist:
        raise CommandError(f"Workspace {value!r} was not found.")


def _bug_type_for_project(project):
    return (
        IssueType.objects.filter(
            workspace=project.workspace,
            key="bug",
            is_active=True,
            deleted_at__isnull=True,
            project_issue_types__project=project,
            project_issue_types__is_enabled=True,
            project_issue_types__deleted_at__isnull=True,
        )
        .distinct()
        .first()
    )


def _state_for_project(project, name):
    from plane.db.models import State

    return State.objects.filter(
        project=project, name=name, deleted_at__isnull=True
    ).first()


def _upsert_view(project, user, view_def, verbosity):
    bug_type = _bug_type_for_project(project)
    filters = dict(view_def["filters"])
    if bug_type is not None:
        filters["type_id__in"] = [str(bug_type.id)]

    # Wire named states where the definition expects them.
    if view_def["name"] == "Ready for testing":
        state = _state_for_project(project, "In Testing")
        if state is not None:
            filters["state"] = [str(state.id)]
    elif view_def["name"] == "Reopened":
        state = _state_for_project(project, "Reopened")
        if state is not None:
            filters["state"] = [str(state.id)]

    defaults = {
        "description": view_def["description"],
        "filters": filters,
        "display_properties": view_def["display_properties"],
        "access": 1,  # Public / shared
        "owned_by": user,
    }

    view, created = IssueView.objects.update_or_create(
        workspace=project.workspace,
        project=project,
        name=view_def["name"],
        defaults=defaults,
    )
    if verbosity >= 2:
        action = "created" if created else "updated"
        self.stdout.write(f"  {action} view {view.name!r} for project {project.name!r}")


class Command(BaseCommand):
    help = "Seed idempotent standard shared Views for type-filtered work (PLN-007)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace slug or UUID")
        parser.add_argument(
            "--user",
            help="Owner user email (defaults to the workspace admin / first active member)",
        )

    def handle(self, *args, **options):
        workspace = _resolve_workspace(options["workspace"])
        verbosity = options.get("verbosity", 1)

        from django.contrib.auth import get_user_model

        User = get_user_model()

        user = None
        if options.get("user"):
            try:
                user = User.objects.get(email=options["user"])
            except User.DoesNotExist:
                raise CommandError(f"User {options['user']!r} was not found.")
        else:
            # Fall back to the workspace admin, then the first active member.
            from plane.db.models import WorkspaceMember

            admin = (
                WorkspaceMember.objects.filter(
                    workspace=workspace, role=20, is_active=True
                )
                .select_related("member")
                .first()
            )
            if admin:
                user = admin.member
            else:
                member = (
                    WorkspaceMember.objects.filter(workspace=workspace, is_active=True)
                    .select_related("member")
                    .first()
                )
                if member:
                    user = member.member
        if user is None:
            raise CommandError(f"No owning user could be resolved for workspace {workspace.slug!r}.")

        projects = (
            Project.objects.filter(workspace=workspace, deleted_at__isnull=True)
            .prefetch_related("project_issue_types__issue_type")
            .order_by("name")
        )
        if not projects.exists():
            raise CommandError(f"No active projects found in workspace {workspace.slug!r}.")

        seeded = 0
        with transaction.atomic():
            for project in projects:
                if verbosity >= 1:
                    self.stdout.write(f"Seeding views for project {project.name!r}...")
                for view_def in STANDARD_VIEWS:
                    _upsert_view(project, user, view_def, verbosity)
                    seeded += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: {seeded} standard view(s) across {projects.count()} project(s) "
                f"in workspace {workspace.slug!r}."
            )
        )
