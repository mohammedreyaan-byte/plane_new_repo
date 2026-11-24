# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Read-only state audit for PLN-002 (states, priorities and labels)."""

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from django.core.management import BaseCommand, CommandError
from django.db.models import Count, Q

from plane.db.models import Issue, Project, State, Workflow, WorkflowState


class Command(BaseCommand):
    help = "Audit active and soft-deleted states. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace slug")
        parser.add_argument("--project", help="Project name or identifier")
        parser.add_argument("--output", help="Optional report path")

    def handle(self, *args, **options):
        slug = options["workspace"]
        projects = Project.objects.filter(workspace__slug=slug, deleted_at__isnull=True)
        if options.get("project"):
            projects = projects.filter(Q(name__iexact=options["project"]) | Q(identifier__iexact=options["project"]))
            if not projects.exists():
                raise CommandError(f"Project {options['project']!r} was not found in {slug!r}.")

        report = {
            "workspace": slug,
            "generated_on": str(date.today()),
            "projects": [],
        }
        for project in projects.order_by("name"):
            issues = Issue.objects.filter(project=project, deleted_at__isnull=True)
            # UUIDs must be normalised to strings: state ids below are compared as strings.
            issue_counts = {
                str(state_id): total
                for state_id, total in issues.values_list("state_id").annotate(total=Count("id"))
            }
            active = list(State.objects.filter(project=project, deleted_at__isnull=True))
            deleted = list(State.all_state_objects.filter(project=project, deleted_at__isnull=False))

            by_group = defaultdict(list)
            for state in active:
                by_group[state.group].append(
                    {
                        "id": str(state.id),
                        "name": state.name,
                        "default": state.default,
                        "issues": issue_counts.get(str(state.id), 0),
                    }
                )

            names = defaultdict(list)
            for state in active:
                names[state.name.casefold()].append(str(state.id))

            workflow_state_ids = set(
                WorkflowState.objects.filter(
                    project=project, deleted_at__isnull=True, workflow__deleted_at__isnull=True
                ).values_list("state_id", flat=True)
            )
            workflows = list(
                Workflow.objects.filter(project=project, deleted_at__isnull=True).values("id", "name", "is_active")
            )

            report["projects"].append(
                {
                    "project": project.name,
                    "identifier": project.identifier,
                    "active_states_by_group": dict(by_group),
                    "soft_deleted_states": [
                        {
                            "id": str(state.id),
                            "name": state.name,
                            "issues": Issue.objects.filter(state=state).count(),
                        }
                        for state in deleted
                    ],
                    "states_not_in_any_workflow": [
                        {"id": str(state.id), "name": state.name}
                        for state in active
                        if state.id not in workflow_state_ids
                    ],
                    "workflow_states_without_issues": [
                        {"id": str(state.id), "name": state.name}
                        for state in active
                        if state.id in workflow_state_ids and not issue_counts.get(str(state.id), 0)
                    ],
                    "duplicate_names": [
                        {"name": name, "state_ids": ids} for name, ids in names.items() if len(ids) > 1
                    ],
                    "completed_without_timestamp": list(
                        issues.filter(state__group="completed", completed_at__isnull=True).values_list("id", flat=True)
                    ),
                    "not_completed_with_timestamp": list(
                        issues.exclude(state__group="completed")
                        .filter(completed_at__isnull=False)
                        .values_list("id", flat=True)
                    ),
                    "workflows": [{"id": str(w["id"]), "name": w["name"], "is_active": w["is_active"]} for w in workflows],
                }
            )

        path = Path(options.get("output") or f"var/reports/state-audit-{date.today().isoformat()}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        self.stdout.write(f"State audit: {len(report['projects'])} project(s). Report: {path}")
        for entry in report["projects"]:
            self.stdout.write(f"\n{entry['project']} ({entry['identifier']})")
            for group, states in entry["active_states_by_group"].items():
                summary = ", ".join("{} ({})".format(s["name"], s["issues"]) for s in states) or "-"
                self.stdout.write(f"  {group}: {summary}")
            self.stdout.write(f"  soft-deleted: {len(entry['soft_deleted_states'])}")
            self.stdout.write(f"  duplicate names: {len(entry['duplicate_names'])}")
            self.stdout.write(f"  no workflow: {len(entry['states_not_in_any_workflow'])}")
            self.stdout.write(f"  workflow state with no issues: {len(entry['workflow_states_without_issues'])}")
            self.stdout.write(f"  completed_at mismatches: {len(entry['completed_without_timestamp']) + len(entry['not_completed_with_timestamp'])}")
