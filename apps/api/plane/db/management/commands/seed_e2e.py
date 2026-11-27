# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Deterministic, re-runnable seed for the PLN-026 end-to-end environment.

Usage::

    python manage.py seed_e2e --workspace e2e --project E2E --reset
    python manage.py seed_e2e --workspace e2e --project E2E --dry-run

Safety: the command refuses a production Django settings module and any
production environment marker; neither can be bypassed by a local/staging
opt-in. ``E2E_ALLOW_LOCAL_STAGING`` or ``PLANE_E2E_ENV=local|staging`` only
declares a safe target on an already non-production deployment. It never
creates service tokens or prints credentials. Provider mock integrations are
created only from operator-supplied environment configuration. The shared UI
password, when used, is read only from ``E2E_TEST_PASSWORD`` at runtime;
without it users get unusable passwords.
"""

import os
from datetime import timedelta

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from plane.db.models import (
    APIToken,
    Cycle,
    CycleIssue,
    Description,
    ExternalAccountIntegration,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueSequence,
    IssueType,
    IssueView,
    Label,
    Module,
    ModuleIssue,
    Project,
    ProjectIssueType,
    ProjectMember,
    SlackChannelSubscription,
    State,
    User,
    Webhook,
    Workflow,
    WorkflowState,
    WorkflowTransition,
    Workspace,
    WorkspaceMember,
)
from plane.db.models.issue import IssueAttachment
from plane.db.models.webhook import ProjectWebhook
from plane.utils.issue_types import ensure_project_issue_types
from plane.utils.workflow.transition import reset_issue_state

PASSWORD_ENV = "E2E_TEST_PASSWORD"
WEBHOOK_SECRET_ENV = "E2E_WEBHOOK_SECRET"
GITHUB_WEBHOOK_SECRET_ENV = "E2E_GITHUB_WEBHOOK_SECRET"
GITHUB_MOCK_URL_ENV = "E2E_GITHUB_MOCK_URL"
SLACK_MOCK_URL_ENV = "E2E_SLACK_MOCK_URL"
EVENT_SINK_URL_ENV = "E2E_EVENT_SINK_URL"
SAFETY_OPT_IN_ENV = "E2E_ALLOW_LOCAL_STAGING"
TARGET_ENV_NAME = "PLANE_E2E_ENV"
TARGET_ENV_VARS = (TARGET_ENV_NAME, "PLANE_ENV", "DEPLOY_ENV", "APP_ENV", "ENVIRONMENT")
PRODUCTION_VALUES = {"prod", "production", "live"}
SAFE_TARGET_VALUES = {"dev", "development", "local", "local-compose", "staging", "test"}

USER_SPECS = (
    ("admin", 20),
    ("member", 15),
    ("developer", 12),
    ("qa", 11),
    ("viewer", 2),
    ("guest", 5),
)
TYPE_KEYS = ("bug", "task", "story", "epic")
STATE_SPECS = (
    ("Backlog", "backlog", 10000, "#60646C", False),
    ("New", "unstarted", 15000, "#60646C", True),
    ("In Progress", "started", 25000, "#F59E0B", False),
    ("Code Review", "started", 35000, "#F59E0B", False),
    ("In Testing", "started", 45000, "#F59E0B", False),
    ("Tested", "started", 55000, "#16A34A", False),
    ("Closed", "completed", 65000, "#16A34A", False),
)
QA_ROLES = ("qa", "admin")
ANY_ROLE = ()
# Every workflow maps a subset of the seven shared states, so each type has its
# own board columns while the project state list stays deterministic.
WORKFLOW_SPECS = {
    "bug": {
        "states": ("New", "In Progress", "Code Review", "In Testing", "Tested", "Closed"),
        "transitions": (
            ("New", "In Progress", ANY_ROLE),
            ("In Progress", "Code Review", ANY_ROLE),
            ("Code Review", "In Testing", ANY_ROLE),
            ("In Testing", "Tested", QA_ROLES),
            ("Tested", "Closed", QA_ROLES),
        ),
    },
    "task": {
        "states": ("New", "In Progress", "Closed"),
        "transitions": (
            ("New", "In Progress", ANY_ROLE),
            ("In Progress", "Closed", ANY_ROLE),
        ),
    },
    "story": {
        "states": ("New", "In Progress", "Code Review", "Closed"),
        "transitions": (
            ("New", "In Progress", ANY_ROLE),
            ("In Progress", "Code Review", ANY_ROLE),
            ("Code Review", "Closed", QA_ROLES),
        ),
    },
    "epic": {
        "states": ("New", "In Progress", "Closed"),
        "transitions": (
            ("New", "In Progress", ANY_ROLE),
            ("In Progress", "Closed", QA_ROLES),
        ),
    },
}
VIEW_SPECS = (
    ("E2E all work items", {}, {"group_by": None}),
    ("E2E bugs", {"type": ["bug"]}, {"group_by": "state"}),
    ("E2E ready for testing", {"state": ["In Testing"]}, {"group_by": None}),
    ("E2E active cycle", {"cycle": ["active"]}, {"group_by": None}),
    ("E2E grouped by type", {}, {"group_by": "type"}),
)
WEBHOOK_PORT = 8787
SLACK_EVENT_KEYS = (
    "work_item.created",
    "work_item.state_changed",
    "work_item.assigned",
    "work_item.commented",
    "work_item.deleted",
)
WEBHOOK_COUNT = 20
EXPECTED_COUNTS = {
    "users": len(USER_SPECS),
    "work_item_types": len(TYPE_KEYS),
    "workflows": len(WORKFLOW_SPECS),
    "states": len(STATE_SPECS),
    "labels": 10,
    "cycles": 3,
    "modules": 3,
    "views": len(VIEW_SPECS),
    "work_items": 500,
    "comments": 200,
    "attachments": 50,
    "webhooks": WEBHOOK_COUNT,
    "service_tokens": 0,
}


def is_production_settings():
    """True when the Django settings module itself is a production module."""
    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or getattr(settings, "SETTINGS_MODULE", "")).lower()
    return any(f".{value}" in settings_module or settings_module.endswith(value) for value in PRODUCTION_VALUES)


def is_production_target():
    """True when the current settings/env combination looks like production."""
    if is_production_settings():
        return True
    return any(os.environ.get(name, "").strip().lower() in PRODUCTION_VALUES for name in TARGET_ENV_VARS)


def has_explicit_safe_environment():
    """True when an operator explicitly declared a local/staging target."""
    opt_in = os.environ.get(SAFETY_OPT_IN_ENV, "").strip().lower()
    if opt_in in {"1", "true", "yes", "on"}:
        return True
    return os.environ.get(TARGET_ENV_NAME, "").strip().lower() in SAFE_TARGET_VALUES


class Command(BaseCommand):
    help = "Seed deterministic E2E data in a local/staging workspace (never production)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace slug for the E2E data.")
        parser.add_argument("--project", required=True, help="Project name to create in that workspace.")
        parser.add_argument("--reset", action="store_true", help="Replace previously seeded project data first.")
        parser.add_argument("--dry-run", action="store_true", help="Report planned counts without writing anything.")

    def handle(self, *args, **options):
        workspace_slug = str(options["workspace"]).strip()
        project_name = str(options["project"]).strip()
        if not workspace_slug or not project_name:
            raise CommandError("--workspace and --project must be non-empty.")

        self._guard_environment()

        if options["dry_run"]:
            self._report(EXPECTED_COUNTS, dry_run=True)
            return

        password = os.environ.get(PASSWORD_ENV)
        if password:
            self.stdout.write(f"Password source: {PASSWORD_ENV} (value is never printed or stored in plaintext).")
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"{PASSWORD_ENV} is not set: E2E users have unusable passwords; UI login scenarios require it."
                )
            )

        webhook_secret = os.environ.get(WEBHOOK_SECRET_ENV)
        if webhook_secret:
            self.stdout.write(f"Webhook secret source: {WEBHOOK_SECRET_ENV} (value is never printed).")
        if os.environ.get(GITHUB_WEBHOOK_SECRET_ENV):
            self.stdout.write(f"GitHub webhook secret source: {GITHUB_WEBHOOK_SECRET_ENV} (value is never printed).")
        for name in (GITHUB_MOCK_URL_ENV, SLACK_MOCK_URL_ENV, EVENT_SINK_URL_ENV):
            if os.environ.get(name):
                self.stdout.write(f"Mock integration endpoint source: {name}.")

        with transaction.atomic():
            counts = self._seed(workspace_slug, project_name, bool(options["reset"]), password, webhook_secret)
        self._report(counts, dry_run=False)

    def _guard_environment(self):
        if is_production_settings():
            raise CommandError(
                "Refusing to seed a production target: the active Django settings module is production. "
                "Run this command only on local or staging deployments."
            )
        if is_production_target():
            raise CommandError(
                "Refusing to seed a production target. Production environment markers "
                "cannot be overridden by local/staging opt-in flags."
            )

    def _report(self, counts, *, dry_run):
        title = "Planned E2E seed counts (dry run)" if dry_run else "E2E seed counts"
        self.stdout.write(title)
        for key, value in counts.items():
            self.stdout.write(f"  {key:<18} {value}")
        if dry_run:
            self.stdout.write("Dry run complete; no database rows or files were written.")

    @staticmethod
    def _email(workspace_slug, role):
        return f"e2e-{role}@{workspace_slug}.example.invalid"

    @staticmethod
    def _webhook_url(index):
        return f"http://127.0.0.1:{WEBHOOK_PORT}/receiver/e2e/{index:02d}"

    def _seed(self, workspace_slug, project_name, reset, password, webhook_secret=None):
        users = self._seed_users(workspace_slug, password)
        admin = users["admin"]
        workspace = Workspace.objects.filter(slug=workspace_slug).first()
        if workspace is None:
            workspace = Workspace.objects.create(
                name=f"E2E {workspace_slug}",
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
                identifier="E2E",
                created_by_id=admin.id,
                cycle_view=True,
                module_view=True,
                issue_views_view=True,
                reports_enabled=True,
                is_issue_type_enabled=True,
            )
        else:
            Project.objects.filter(pk=project.pk).update(
                is_issue_type_enabled=True,
                cycle_view=True,
                module_view=True,
                issue_views_view=True,
                reports_enabled=True,
                identifier="E2E",
                created_by_id=admin.id,
            )
            project.refresh_from_db()

        if reset:
            self._reset_project(project, workspace)

        types = self._seed_types(workspace, project, admin)
        states = self._seed_states(project, admin)
        self._seed_workflows(project, types, states, admin)
        self._seed_members(workspace, project, users)
        labels = self._seed_labels(project, admin)
        cycles = self._seed_cycles(project, admin)
        modules = self._seed_modules(project, admin)
        self._seed_views(project, admin, states, types)
        items = self._seed_work_items(project, types, states, users, labels, admin)
        self._seed_comments(project, items, users, admin)
        self._seed_attachments(project, items, admin)
        self._seed_cycle_and_module_links(project, items, cycles, modules, admin)
        webhooks = self._seed_webhooks(workspace, project, admin, webhook_secret)
        integrations = self._seed_mock_integrations(workspace, admin)

        user_emails = [self._email(workspace_slug, role) for role, _ in USER_SPECS]
        return {
            "users": User.objects.filter(email__in=user_emails).count(),
            "work_item_types": IssueType.objects.filter(workspace=workspace, key__in=TYPE_KEYS).count(),
            "workflows": Workflow.objects.filter(project=project, issue_type__key__in=TYPE_KEYS).count(),
            "states": State.all_state_objects.filter(project=project).count(),
            "labels": Label.objects.filter(project=project).count(),
            "cycles": Cycle.objects.filter(project=project).count(),
            "modules": Module.objects.filter(project=project).count(),
            "views": IssueView.objects.filter(project=project).count(),
            "work_items": Issue.all_objects.filter(project=project).count(),
            "comments": IssueComment.objects.filter(project=project).count(),
            "attachments": IssueAttachment.objects.filter(project=project).count(),
            "webhooks": webhooks,
            "mock_integrations": integrations,
            "service_tokens": APIToken.objects.filter(workspace=workspace, is_service=True).count(),
        }

    def _seed_users(self, workspace_slug, password):
        users = {}
        for role, _ in USER_SPECS:
            email = self._email(workspace_slug, role)
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User(email=email, username=f"e2e_{workspace_slug}_{role}", first_name="E2E", last_name=role)
            user.is_active = True
            if password:
                user.set_password(password)
            else:
                user.set_unusable_password()
            user.save()
            users[role] = user
        return users

    def _seed_members(self, workspace, project, users):
        for role, role_value in USER_SPECS:
            user = users[role]
            WorkspaceMember.objects.update_or_create(
                workspace=workspace,
                member=user,
                defaults={"role": role_value},
            )
            ProjectMember.objects.update_or_create(
                project=project,
                member=user,
                defaults={"workspace": workspace, "role": role_value},
            )

    def _seed_types(self, workspace, project, admin):
        # The workspace/project signals create the four default types. Remove
        # stray workspace types so the seeded workspace always has exactly four.
        IssueType.objects.filter(workspace=workspace).exclude(key__in=TYPE_KEYS).delete(soft=False)
        ensure_project_issue_types(project)
        types = {}
        for key in TYPE_KEYS:
            issue_type = IssueType.objects.get(workspace=workspace, key=key)
            IssueType.objects.filter(pk=issue_type.pk).update(
                is_active=True, name=key.capitalize(), created_by_id=admin.id
            )
            types[key] = IssueType.objects.get(pk=issue_type.pk)
        ProjectIssueType.objects.filter(project=project, issue_type__key__in=TYPE_KEYS).update(
            is_enabled=True, is_default=False
        )
        ProjectIssueType.objects.filter(project=project, issue_type__key="task").update(is_default=True)
        return types

    def _seed_states(self, project, admin):
        states = {}
        for name, group, sequence, color, is_default in STATE_SPECS:
            state = State.all_state_objects.filter(project=project, name=name).first()
            if state is None:
                state = State.all_state_objects.create(
                    project=project,
                    name=name,
                    group=group,
                    sequence=sequence,
                    color=color,
                    default=is_default,
                    created_by_id=admin.id,
                )
            else:
                State.all_state_objects.filter(pk=state.pk).update(
                    group=group,
                    sequence=sequence,
                    color=color,
                    default=is_default,
                    deleted_at=None,
                    created_by_id=admin.id,
                )
                state.refresh_from_db()
            states[name] = state
        State.all_state_objects.filter(project=project).exclude(name__in=states).delete()
        return states

    def _seed_workflows(self, project, types, states, admin):
        for key, spec in WORKFLOW_SPECS.items():
            name = f"E2E {key.capitalize()} workflow"
            workflow = Workflow.objects.filter(project=project, issue_type=types[key], name=name).first()
            if workflow is None:
                workflow = Workflow.objects.create(
                    project=project,
                    issue_type=types[key],
                    name=name,
                    is_default=True,
                    is_active=True,
                    description=f"Deterministic E2E workflow for {key}.",
                    created_by_id=admin.id,
                )
            else:
                Workflow.objects.filter(pk=workflow.pk).update(is_default=True, is_active=True, created_by_id=admin.id)
            Workflow.objects.filter(project=project, issue_type=types[key]).exclude(pk=workflow.pk).delete(soft=False)

            expected_state_ids = []
            for sequence, state_name in enumerate(spec["states"], start=1):
                state = states[state_name]
                expected_state_ids.append(state.id)
                row = WorkflowState.objects.filter(workflow=workflow, state=state).first()
                if row is None:
                    WorkflowState.objects.create(
                        workflow=workflow,
                        project=project,
                        state=state,
                        sequence=sequence * 10000,
                        is_initial=state_name == spec["states"][0],
                        is_final=state_name == "Closed",
                        created_by_id=admin.id,
                    )
                else:
                    WorkflowState.objects.filter(pk=row.pk).update(
                        sequence=sequence * 10000,
                        is_initial=state_name == spec["states"][0],
                        is_final=state_name == "Closed",
                        deleted_at=None,
                    )
            WorkflowState.objects.filter(workflow=workflow).exclude(state_id__in=expected_state_ids).delete(soft=False)

            expected_edges = []
            for from_name, to_name, roles in spec["transitions"]:
                edge = (states[from_name].id, states[to_name].id)
                expected_edges.append(edge)
                row, _ = WorkflowTransition.objects.update_or_create(
                    workflow=workflow,
                    from_state=states[from_name],
                    to_state=states[to_name],
                    defaults={
                        "project": project,
                        "allowed_roles": list(roles),
                        "is_active": True,
                        "admin_override": True,
                        "requires_comment": False,
                        "required_fields": [],
                        "deleted_at": None,
                    },
                )
                row.save(created_by_id=admin.id, disable_auto_set_user=True)
            for row in WorkflowTransition.objects.filter(workflow=workflow):
                if (row.from_state_id, row.to_state_id) not in expected_edges:
                    row.delete(soft=False)

    def _seed_labels(self, project, admin):
        labels = []
        for index in range(1, EXPECTED_COUNTS["labels"] + 1):
            name = f"E2E label {index:02d}"
            label, _ = Label.objects.update_or_create(
                project=project,
                name=name,
                defaults={
                    "workspace": project.workspace,
                    "color": "#3B82F6",
                    "deleted_at": None,
                    "created_by_id": admin.id,
                },
            )
            labels.append(label)
        Label.objects.filter(project=project).exclude(pk__in=[label.pk for label in labels]).delete(soft=False)
        return labels

    def _seed_cycles(self, project, admin):
        now = timezone.now()
        cycles = []
        for index in range(1, EXPECTED_COUNTS["cycles"] + 1):
            name = f"E2E cycle {index:02d}" + (" (active)" if index == 1 else "")
            start = now - timedelta(days=7) if index == 1 else now + timedelta(days=30 * (index - 1))
            end = now + timedelta(days=7) if index == 1 else now + timedelta(days=30 * (index - 1) + 14)
            cycle, _ = Cycle.objects.update_or_create(
                project=project,
                name=name,
                defaults={
                    "workspace": project.workspace,
                    "owned_by": admin,
                    "start_date": start,
                    "end_date": end,
                    "deleted_at": None,
                    "created_by_id": admin.id,
                },
            )
            cycles.append(cycle)
        Cycle.objects.filter(project=project).exclude(pk__in=[cycle.pk for cycle in cycles]).delete(soft=False)
        return cycles

    def _seed_modules(self, project, admin):
        modules = []
        for index, status in enumerate(("planned", "in-progress", "backlog"), start=1):
            module, _ = Module.objects.update_or_create(
                project=project,
                name=f"E2E module {index:02d}",
                defaults={
                    "workspace": project.workspace,
                    "status": status,
                    "lead": admin,
                    "deleted_at": None,
                    "created_by_id": admin.id,
                },
            )
            modules.append(module)
        Module.objects.filter(project=project).exclude(pk__in=[module.pk for module in modules]).delete(soft=False)
        return modules

    def _seed_views(self, project, admin, states, types):
        filters_by_name = {
            "E2E bugs": {"type": [types["bug"].key]},
            "E2E ready for testing": {"state": [str(states["In Testing"].id)]},
            "E2E active cycle": {"cycle": ["active"]},
        }
        views = []
        for name, default_filters, display_filters in VIEW_SPECS:
            filters = dict(default_filters)
            filters.update(filters_by_name.get(name, {}))
            view, _ = IssueView.objects.update_or_create(
                project=project,
                name=name,
                defaults={
                    "workspace": project.workspace,
                    "owned_by": admin,
                    "access": 1,
                    "filters": filters,
                    "display_filters": {**IssueView._meta.get_field("display_filters").default(), **display_filters},
                    "deleted_at": None,
                    "created_by_id": admin.id,
                },
            )
            views.append(view)
        IssueView.objects.filter(project=project).exclude(pk__in=[view.pk for view in views]).delete(soft=False)

    def _seed_work_items(self, project, types, states, users, labels, admin):
        state_names = ("New", "In Progress", "Code Review", "In Testing", "Tested", "Closed")
        priorities = ("urgent", "high", "medium", "low", "none")
        role_keys = [role for role, _ in USER_SPECS]
        items = []
        for index in range(1, EXPECTED_COUNTS["work_items"] + 1):
            type_key = TYPE_KEYS[(index - 1) % len(TYPE_KEYS)]
            state_name = state_names[(index - 1) % len(state_names)]
            external_id = f"e2e:{project.workspace.slug}:{project.identifier}:item-{index:04d}"
            name = f"E2E-{index} {type_key.capitalize()} {state_name}"
            issue = Issue.all_objects.filter(
                project=project, external_source="seed_e2e", external_id=external_id
            ).first()
            if issue is None:
                issue = Issue(
                    project=project,
                    workspace=project.workspace,
                    name=name,
                    state=states[state_name],
                    type=types[type_key],
                    priority=priorities[(index - 1) % len(priorities)],
                    description_html=f"<p>Seeded E2E work item {index:04d}.</p>",
                    external_source="seed_e2e",
                    external_id=external_id,
                )
            else:
                issue.name = name
                issue.type = types[type_key]
                issue.priority = priorities[(index - 1) % len(priorities)]
                issue.deleted_at = None
            issue.save(created_by_id=admin.id)
            # Re-runs move existing rows through the central state writer so the
            # state change is locked, audited and visible to the workflow contract.
            reset_issue_state(issue.id, states[state_name].id, user=admin, reason="seed_e2e", source="seed")

            assignee = users[role_keys[index % len(role_keys)]]
            IssueAssignee.objects.get_or_create(issue=issue, assignee=assignee, defaults={"project": project})
            IssueLabel.objects.get_or_create(
                issue=issue,
                label=labels[(index - 1) % len(labels)],
                defaults={"project": project, "workspace": project.workspace},
            )
            items.append(issue)
        return items

    def _seed_comments(self, project, items, users, admin):
        role_keys = [role for role, _ in USER_SPECS]
        for index in range(1, EXPECTED_COUNTS["comments"] + 1):
            issue = items[(index - 1) % len(items)]
            external_id = f"e2e:{project.workspace.slug}:comment-{index:04d}"
            comment = IssueComment.objects.filter(
                project=project, external_source="seed_e2e", external_id=external_id
            ).first()
            if comment is None:
                comment = IssueComment(
                    project=project,
                    issue=issue,
                    actor=users[role_keys[index % len(role_keys)]],
                    comment_html=f"<p>Seeded E2E comment {index:04d}.</p>",
                    external_source="seed_e2e",
                    external_id=external_id,
                )
            else:
                comment.deleted_at = None
            comment.save(created_by_id=admin.id)

    def _seed_attachments(self, project, items, admin):
        for index in range(1, EXPECTED_COUNTS["attachments"] + 1):
            issue = items[(index - 1) % len(items)]
            external_id = f"e2e:{project.workspace.slug}:attachment-{index:03d}"
            attachment = IssueAttachment.objects.filter(
                project=project, external_source="seed_e2e", external_id=external_id
            ).first()
            if attachment is None:
                attachment = IssueAttachment(
                    project=project,
                    workspace=project.workspace,
                    issue=issue,
                    attributes={
                        "kind": "e2e-seed",
                        "index": index,
                        "content": f"E2E attachment {index:03d}\n",
                    },
                    external_source="seed_e2e",
                    external_id=external_id,
                )
            else:
                attachment.deleted_at = None
            # Assign the storage key directly. Calling FileField.save() would
            # require a working object-storage backend; the deterministic key
            # keeps repeat runs idempotent in local/staging environments.
            attachment.asset.name = f"e2e/{project.workspace.slug}/attachment-{index:03d}.txt"
            attachment.save(created_by_id=admin.id)

    def _seed_cycle_and_module_links(self, project, items, cycles, modules, admin):
        for index in range(1, 11):
            CycleIssue.objects.get_or_create(
                cycle=cycles[0],
                issue=items[index - 1],
                defaults={"project": project, "created_by_id": admin.id},
            )
        for index, item in enumerate(items[:6], start=1):
            ModuleIssue.objects.get_or_create(
                module=modules[0],
                issue=item,
                defaults={"project": project, "created_by_id": admin.id},
            )
        epic = next(item for item in items if item.type.key == "epic")
        Module.objects.filter(pk=modules[0].pk).update(epic=epic)

    def _seed_webhooks(self, workspace, project, admin, webhook_secret=None):
        webhook_ids = []
        for index in range(1, WEBHOOK_COUNT + 1):
            url = self._webhook_url(index)
            webhook = Webhook.objects.filter(workspace=workspace, url=url).first()
            if webhook is None:
                webhook = Webhook.objects.create(
                    workspace=workspace,
                    url=url,
                    is_active=True,
                    project=True,
                    issue=True,
                    issue_comment=True,
                    created_by_id=admin.id,
                )
            else:
                update_fields = {"is_active": True, "deleted_at": None}
                if webhook_secret:
                    update_fields["secret_key"] = webhook_secret
                Webhook.objects.filter(pk=webhook.pk).update(**update_fields)
            if webhook_secret and webhook.secret_key != webhook_secret:
                Webhook.objects.filter(pk=webhook.pk).update(secret_key=webhook_secret)
            ProjectWebhook.objects.get_or_create(
                project=project,
                webhook=webhook,
                defaults={"created_by_id": admin.id},
            )
            webhook_ids.append(webhook.id)
        Webhook.objects.filter(workspace=workspace, url__startswith="http://127.0.0.1:8787/receiver/e2e/").exclude(
            pk__in=webhook_ids
        ).delete(soft=False)
        return len(webhook_ids)

    def _seed_mock_integrations(self, workspace, admin):
        """Create provider integrations only from operator-supplied mock config.

        No provider account, token, channel or webhook secret is invented here.
        A mock integration is created only when the operator supplies the
        corresponding environment variable.
        """

        github_secret = os.environ.get(GITHUB_WEBHOOK_SECRET_ENV)
        github_url = os.environ.get(GITHUB_MOCK_URL_ENV, "").strip().rstrip("/")
        slack_url = os.environ.get(SLACK_MOCK_URL_ENV, "").strip().rstrip("/")
        count = 0

        if github_secret and github_url:
            integration, _ = ExternalAccountIntegration.objects.get_or_create(
                workspace=workspace,
                provider="github",
                provider_account_id="e2e-github-mock",
                defaults={
                    "account_name": "E2E GitHub mock",
                    "host": github_url,
                    "created_by_id": admin.id,
                },
            )
            integration.set_webhook_secret(github_secret)
            ExternalAccountIntegration.objects.filter(pk=integration.pk).update(
                account_name="E2E GitHub mock",
                host=github_url,
                is_active=True,
                webhook_secret=integration.webhook_secret,
            )
            count += 1

        if slack_url:
            integration, _ = ExternalAccountIntegration.objects.get_or_create(
                workspace=workspace,
                provider="slack",
                provider_account_id="e2e-slack-mock",
                defaults={
                    "account_name": "E2E Slack mock",
                    "host": slack_url,
                    "created_by_id": admin.id,
                },
            )
            ExternalAccountIntegration.objects.filter(pk=integration.pk).update(
                account_name="E2E Slack mock",
                host=slack_url,
                is_active=True,
            )
            SlackChannelSubscription.objects.get_or_create(
                integration=integration,
                channel_id="e2e-mock-channel",
                defaults={
                    "workspace": workspace,
                    "channel_name": "e2e-mock-channel",
                    "events": {key: False for key in SLACK_EVENT_KEYS},
                    "created_by_id": admin.id,
                },
            )
            SlackChannelSubscription.objects.filter(integration=integration).update(is_active=True)
            count += 1

        return count

    def _reset_project(self, project, workspace):
        """Remove seeded data for this project only, leaving users intact."""
        for model in (
            IssueActivity,
            IssueComment,
            IssueAssignee,
            IssueLabel,
            IssueSequence,
            IssueAttachment,
            CycleIssue,
            ModuleIssue,
            Description,
            Issue,
            Cycle,
            Module,
            IssueView,
            WorkflowTransition,
            WorkflowState,
            Workflow,
            ProjectIssueType,
        ):
            manager = getattr(model, "all_objects", model.objects)
            manager.filter(project=project).delete()
        State.all_state_objects.filter(project=project).delete()
        Label.objects.filter(project=project).delete()
        urls = [self._webhook_url(index) for index in range(1, WEBHOOK_COUNT + 1)]
        ProjectWebhook.objects.filter(project=project).delete(soft=False)
        Webhook.objects.filter(workspace=workspace, url__in=urls).delete(soft=False)
