# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Deterministic seed for the isolated PLN-026 k6 load project.

Usage::

    python manage.py seed_load --workspace load --project Load --reset
    python manage.py seed_load --workspace load --project Load --dry-run

The command creates 5,000 work items, 20 states, 500 label links, 200 cycles,
200 modules and six users. It never creates a service token or prints a
credential; tokens must be provisioned separately and supplied to k6 through
``LOAD_SERVICE_TOKEN`` (``LOAD_SERVICE_TOKEN`` is accepted as an alias).
"""

import os
import re
from datetime import timedelta

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from plane.db.models import (
    Cycle,
    Issue,
    IssueLabel,
    IssueSequence,
    IssueType,
    Label,
    Module,
    Project,
    State,
    Workflow,
    Workspace,
)
from plane.db.management.commands.seed_e2e import (
    PASSWORD_ENV,
    STATE_SPECS,
    TYPE_KEYS,
    USER_SPECS,
    Command as E2eSeedCommand,
)
from plane.utils.workflow.transition import reset_issue_state

EXPECTED_COUNTS = {
    "users": len(USER_SPECS),
    "work_item_types": len(TYPE_KEYS),
    "workflows": len(TYPE_KEYS),
    "states": 20,
    "labels": 10,
    "cycles": 200,
    "modules": 200,
    "work_items": 5000,
    "label_links": 500,
    "service_tokens": 0,
}
EXTRA_STATES = tuple(f"Load state {index:02d}" for index in range(8, 21))
LOAD_SOURCE = "seed_load"
SAFETY_OPT_IN_ENV = "LOAD_ALLOW_LOCAL_STAGING"
TARGET_ENV_NAME = "PLANE_LOAD_ENV"
TARGET_ENV_VARS = (TARGET_ENV_NAME, "PLANE_E2E_ENV", "PLANE_ENV", "DEPLOY_ENV", "APP_ENV", "ENVIRONMENT")
PRODUCTION_VALUES = {"prod", "production", "live"}
SAFE_TARGET_VALUES = {"dev", "development", "local", "local-compose", "staging", "test"}


def is_production_target():
    """True when any load environment marker points at production."""
    return any(os.environ.get(name, "").strip().lower() in PRODUCTION_VALUES for name in TARGET_ENV_VARS)


def has_explicit_safe_environment():
    """True when an operator explicitly declared a local/staging load target."""
    opt_in = os.environ.get(SAFETY_OPT_IN_ENV, "").strip().lower()
    if opt_in in {"1", "true", "yes", "on"}:
        return True
    return any(os.environ.get(name, "").strip().lower() in SAFE_TARGET_VALUES for name in TARGET_ENV_VARS)


def production_settings_module():
    """True when Django itself is configured for production.

    This check is deliberately unconditional: no flag or environment variable
    may bypass it.
    """
    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or getattr(settings, "SETTINGS_MODULE", "")).lower()
    normalized = re.sub(r"[^a-z0-9]+", ".", settings_module).strip(".")
    parts = set(filter(None, normalized.split(".")))
    return bool(parts & PRODUCTION_VALUES) or "production" in normalized


def has_safe_environment_opt_in():
    """True when the operator explicitly declared a local/staging target."""
    opt_in = os.environ.get(SAFETY_OPT_IN_ENV, "").strip().lower()
    if opt_in in {"1", "true", "yes", "on"}:
        return True
    return os.environ.get(TARGET_ENV_NAME, "").strip().lower() in SAFE_TARGET_VALUES


class Command(BaseCommand):
    help = "Seed deterministic k6 load data in an isolated local/staging workspace (never production)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", default="load", help="Workspace slug for the load data.")
        parser.add_argument("--project", default="Load", help="Project name to create in that workspace.")
        parser.add_argument("--identifier", default="LOAD", help="Project identifier used by load scripts.")
        parser.add_argument("--reset", action="store_true", help="Replace previously seeded project data first.")
        parser.add_argument("--dry-run", action="store_true", help="Report planned counts without writing anything.")
        parser.add_argument(
            "--allow-local-staging",
            action="store_true",
            help="Explicit opt-in for a dedicated local/staging target (never production).",
        )

    def handle(self, *args, **options):
        workspace_slug = str(options["workspace"]).strip()
        project_name = str(options["project"]).strip()
        identifier = str(options["identifier"]).strip().upper()
        if not workspace_slug or not project_name or not identifier:
            raise CommandError("--workspace, --project and --identifier must be non-empty.")

        if production_settings_module():
            raise CommandError(
                "Refusing to seed load data: DJANGO_SETTINGS_MODULE looks like production. "
                "This guard cannot be bypassed by any flag or environment variable."
            )
        if is_production_target():
            raise CommandError(
                "Refusing to seed a production target. Production environment markers "
                "cannot be overridden by local/staging opt-in flags."
            )
        if not (options["allow_local_staging"] or has_safe_environment_opt_in()):
            raise CommandError(
                "Refusing to seed without an explicit local/staging opt-in. Pass "
                "--allow-local-staging, set LOAD_ALLOW_LOCAL_STAGING=1, or set "
                "PLANE_LOAD_ENV=local|staging on a dedicated deployment."
            )

        if options["dry_run"]:
            self._report(EXPECTED_COUNTS, dry_run=True)
            return

        password = os.environ.get(PASSWORD_ENV)
        if password:
            self.stdout.write(f"Password source: {PASSWORD_ENV} (value is never printed or stored in plaintext).")
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"{PASSWORD_ENV} is not set: load users have unusable passwords; "
                    "the load suite authenticates with LOAD_SERVICE_TOKEN."
                )
            )

        with transaction.atomic():
            counts = self._seed(workspace_slug, project_name, identifier, bool(options["reset"]), password)
        self._report(counts, dry_run=False)

    def _report(self, counts, *, dry_run):
        title = "Planned load seed counts (dry run)" if dry_run else "Load seed counts"
        self.stdout.write(title)
        for key, value in counts.items():
            self.stdout.write(f"  {key:<18} {value}")
        if dry_run:
            self.stdout.write("Dry run complete; no database rows were written.")

    def _seed(self, workspace_slug, project_name, identifier, reset, password):
        e2e_seed = E2eSeedCommand()
        users = e2e_seed._seed_users(workspace_slug, password)
        admin = users["admin"]

        workspace = Workspace.objects.filter(slug=workspace_slug).first()
        if workspace is None:
            workspace = Workspace.objects.create(
                name=f"Load {workspace_slug}",
                slug=workspace_slug,
                owner=admin,
                created_by_id=admin.id,
            )
        elif workspace.owner_id != admin.id:
            Workspace.objects.filter(pk=workspace.pk).update(owner=admin)
            workspace.refresh_from_db(fields=["owner_id"])

        project = Project.objects.filter(workspace=workspace, name=project_name).first()
        if project is None:
            project = Project.objects.create(
                workspace=workspace,
                name=project_name,
                identifier=identifier,
                created_by_id=admin.id,
                cycle_view=True,
                module_view=True,
                issue_views_view=True,
                reports_enabled=True,
                is_issue_type_enabled=True,
            )
        else:
            Project.objects.filter(pk=project.pk).update(
                identifier=identifier,
                cycle_view=True,
                module_view=True,
                issue_views_view=True,
                reports_enabled=True,
                is_issue_type_enabled=True,
                created_by_id=admin.id,
            )
            project.refresh_from_db()

        if reset:
            e2e_seed._reset_project(project, workspace)

        types = e2e_seed._seed_types(workspace, project, admin)
        states = self._seed_states(project, admin)
        e2e_seed._seed_workflows(project, types, states, admin)
        e2e_seed._seed_members(workspace, project, users)
        labels = e2e_seed._seed_labels(project, admin)
        self._seed_cycles(project, admin)
        self._seed_modules(project, admin)
        issues = self._seed_work_items(project, types, states, admin, identifier)
        self._seed_label_links(project, issues, labels, admin)

        return {
            "users": len(users),
            "work_item_types": IssueType.objects.filter(workspace=workspace, key__in=TYPE_KEYS).count(),
            "workflows": Workflow.objects.filter(project=project, issue_type__key__in=TYPE_KEYS).count(),
            "states": State.all_state_objects.filter(project=project).count(),
            "labels": Label.objects.filter(project=project).count(),
            "cycles": Cycle.objects.filter(project=project).count(),
            "modules": Module.objects.filter(project=project).count(),
            "work_items": Issue.all_objects.filter(project=project).count(),
            "label_links": IssueLabel.objects.filter(project=project).count(),
            "service_tokens": self._service_token_count(workspace),
        }

    @staticmethod
    def _service_token_count(workspace):
        from plane.db.models import APIToken

        return APIToken.objects.filter(workspace=workspace, is_service=True).count()

    def _seed_states(self, project, admin):
        names = [spec[0] for spec in STATE_SPECS] + list(EXTRA_STATES)
        known_groups = {spec[0]: spec[1] for spec in STATE_SPECS}
        states = {}
        for index, name in enumerate(names, start=1):
            group = known_groups.get(name, "started" if index < len(names) else "completed")
            state = State.all_state_objects.filter(project=project, name=name).first()
            if state is None:
                state = State.all_state_objects.create(
                    project=project,
                    name=name,
                    group=group,
                    sequence=index * 10000,
                    color="#60646C",
                    default=name == "New",
                    created_by_id=admin.id,
                )
            else:
                State.all_state_objects.filter(pk=state.pk).update(
                    group=group,
                    sequence=index * 10000,
                    color="#60646C",
                    default=name == "New",
                    deleted_at=None,
                    created_by_id=admin.id,
                )
                state.refresh_from_db()
            states[name] = state
        State.all_state_objects.filter(project=project).exclude(name__in=names).delete()
        return states

    def _seed_cycles(self, project, admin):
        now = timezone.now()
        for index in range(1, EXPECTED_COUNTS["cycles"] + 1):
            name = f"Load cycle {index:03d}"
            cycle, created = Cycle.objects.update_or_create(
                project=project,
                name=name,
                defaults={
                    "workspace": project.workspace,
                    "owned_by": admin,
                    "start_date": now + timedelta(days=30 * (index - 1)),
                    "end_date": now + timedelta(days=30 * (index - 1) + 14),
                    "deleted_at": None,
                    "created_by_id": admin.id,
                },
            )
            if not created:
                cycle.save(created_by_id=admin.id)
        return list(Cycle.objects.filter(project=project).order_by("name"))

    def _seed_modules(self, project, admin):
        for index in range(1, EXPECTED_COUNTS["modules"] + 1):
            module, created = Module.objects.update_or_create(
                project=project,
                name=f"Load module {index:03d}",
                defaults={
                    "workspace": project.workspace,
                    "status": "planned",
                    "lead": admin,
                    "deleted_at": None,
                    "created_by_id": admin.id,
                },
            )
            if not created:
                module.save(created_by_id=admin.id)
        return list(Module.objects.filter(project=project).order_by("name"))

    def _seed_work_items(self, project, types, states, admin, identifier):
        expected = EXPECTED_COUNTS["work_items"]
        external_ids = {
            f"load:{project.workspace.slug}:{identifier}:item-{index:05d}" for index in range(1, expected + 1)
        }
        existing = {
            row["external_id"]: row
            for row in Issue.all_objects.filter(
                project=project,
                external_source=LOAD_SOURCE,
                external_id__in=external_ids,
            ).only("id", "external_id")
        }
        state_names = [spec[0] for spec in STATE_SPECS]
        priorities = ("urgent", "high", "medium", "low", "none")

        new_items = []
        changed_items = []
        changed_state_ids = {}
        for index in range(1, expected + 1):
            external_id = f"load:{project.workspace.slug}:{identifier}:item-{index:05d}"
            state_name = state_names[(index - 1) % len(state_names)]
            type_key = TYPE_KEYS[(index - 1) % len(TYPE_KEYS)]
            name = f"LOAD-{index:05d} {type_key} {state_name}"
            issue = existing.get(external_id)
            if issue is None:
                issue = Issue(
                    project=project,
                    workspace=project.workspace,
                    name=name,
                    state=states[state_name],
                    type=types[type_key],
                    priority=priorities[(index - 1) % len(priorities)],
                    sequence_id=index,
                    sort_order=index * 10000,
                    description_html=f"<p>Load test work item {index:05d}.</p>",
                    description_stripped=f"Load test work item {index:05d}.",
                    external_source=LOAD_SOURCE,
                    external_id=external_id,
                    created_by_id=admin.id,
                )
                new_items.append((index, issue))
            else:
                issue.name = name
                issue.type = types[type_key]
                issue.priority = priorities[(index - 1) % len(priorities)]
                issue.description_html = f"<p>Load test work item {index:05d}.</p>"
                issue.description_stripped = f"Load test work item {index:05d}."
                issue.deleted_at = None
                changed_items.append((index, issue))
                changed_state_ids[index] = states[state_name].id

        if new_items:
            Issue.all_objects.bulk_create([issue for _, issue in new_items], batch_size=500)
        for index, issue in changed_items:
            issue.sequence_id = index
            issue.sort_order = index * 10000
            issue.save(created_by_id=admin.id)
            # Re-runs use the central state writer so the state change is locked,
            # audited and visible to the workflow contract.
            reset_issue_state(issue.id, changed_state_ids[index], user=admin, reason="seed_load", source="seed")

        IssueSequence.objects.filter(project=project).delete()
        IssueSequence.objects.bulk_create(
            [
                IssueSequence(
                    project=project,
                    workspace=project.workspace,
                    issue=issue,
                    sequence=index,
                    created_by_id=admin.id,
                )
                for index, issue in new_items + changed_items
            ],
            batch_size=500,
        )

        return list(Issue.all_objects.filter(project=project, external_source=LOAD_SOURCE).order_by("sequence_id"))

    def _seed_label_links(self, project, issues, labels, admin):
        for index, issue in enumerate(issues[: EXPECTED_COUNTS["label_links"]], start=1):
            IssueLabel.objects.get_or_create(
                issue=issue,
                label=labels[(index - 1) % len(labels)],
                defaults={
                    "project": project,
                    "workspace": project.workspace,
                    "created_by_id": admin.id,
                },
            )
