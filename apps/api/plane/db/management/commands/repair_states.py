# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Dry-run-by-default state repairs for PLN-002."""

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from plane.db.models import Issue, Project, State, WorkflowState, WorkflowTransition

BUILT_IN_NAMES = {
    "backlog": "Backlog",
    "todo": "Todo",
    "in progress": "In Progress",
    "done": "Done",
    "cancelled": "Cancelled",
}


def _normalise(name):
    return " ".join(str(name).strip().split())


class Command(BaseCommand):
    help = "Normalise names, merge case-insensitive duplicates and fix completed_at. Dry run by default."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace slug")
        parser.add_argument("--project", help="Project name or identifier")
        parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
        parser.add_argument("--output", help="Optional report path")

    def handle(self, *args, **options):
        projects = Project.objects.filter(workspace__slug=options["workspace"], deleted_at__isnull=True)
        if options.get("project"):
            projects = projects.filter(
                Q(name__iexact=options["project"]) | Q(identifier__iexact=options["project"])
            )
            if not projects.exists():
                raise CommandError(f"Project {options['project']!r} was not found.")

        actions = []
        for project in projects.order_by("name"):
            states = list(State.objects.filter(project=project, deleted_at__isnull=True))
            by_name = defaultdict(list)
            for state in states:
                by_name[_normalise(state.name).casefold()].append(state)

            for normalized, group in by_name.items():
                if len(group) < 2:
                    continue
                target = min(group, key=lambda s: (s.created_at or s.updated_at, str(s.id)))
                for duplicate in group:
                    if duplicate.id == target.id:
                        continue
                    actions.append(
                        {
                            "project": project.name,
                            "action": "merge_state",
                            "from": str(duplicate.id),
                            "from_name": duplicate.name,
                            "to": str(target.id),
                            "to_name": target.name,
                            "issues": Issue.objects.filter(state=duplicate).count(),
                            "workflow_states": WorkflowState.objects.filter(state=duplicate).count(),
                        }
                    )
                    if options["apply"]:
                        with transaction.atomic():
                            Issue.objects.filter(state=duplicate).update(state=target)
                            for transition in WorkflowTransition.objects.filter(from_state=duplicate):
                                transition.from_state = target
                                transition.save(update_fields=["from_state"])
                            for transition in WorkflowTransition.objects.filter(to_state=duplicate):
                                transition.to_state = target
                                transition.save(update_fields=["to_state"])
                            for row in WorkflowState.objects.filter(state=duplicate):
                                if not WorkflowState.objects.filter(workflow=row.workflow, state=target).exists():
                                    WorkflowState.objects.filter(pk=row.pk).update(state=target)
                                else:
                                    row.delete()
                            duplicate.delete()

            for state in State.objects.filter(project=project, deleted_at__isnull=True):
                normalized = _normalise(state.name)
                canonical = BUILT_IN_NAMES.get(normalized.casefold())
                new_name = canonical if canonical else normalized
                if new_name and new_name != state.name:
                    actions.append(
                        {
                            "project": project.name,
                            "action": "rename_state",
                            "state": str(state.id),
                            "from": state.name,
                            "to": new_name,
                        }
                    )
                    if options["apply"]:
                        state.name = new_name
                        state.save(update_fields=["name", "slug"])

            for issue in Issue.objects.filter(project=project, deleted_at__isnull=True).select_related("state"):
                should_be_complete = issue.state and issue.state.group == "completed"
                needs_change = (should_be_complete and not issue.completed_at) or (
                    not should_be_complete and issue.completed_at
                )
                if not needs_change:
                    continue
                actions.append(
                    {
                        "project": project.name,
                        "action": "completed_at",
                        "issue": str(issue.id),
                        "from": str(issue.completed_at),
                        "to": str(issue.updated_at) if should_be_complete else None,
                    }
                )
                if options["apply"]:
                    issue.completed_at = issue.updated_at if should_be_complete else None
                    issue.save(update_fields=["completed_at", "updated_at"])

        path = Path(options.get("output") or f"var/reports/state-repair-{date.today().isoformat()}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actions, indent=2), encoding="utf-8")
        self.stdout.write(
            f"State repair {'APPLIED' if options['apply'] else 'DRY RUN'}: {len(actions)} action(s). Report: {path}"
        )
        for action in actions:
            self.stdout.write("  " + ", ".join(f"{key}={value}" for key, value in action.items()))
