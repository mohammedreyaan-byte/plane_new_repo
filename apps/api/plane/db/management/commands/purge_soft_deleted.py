# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Purge unreferenced soft-deleted states and labels (PLN-002).

Preview by default. ``--apply`` is deliberately conservative: rows that are still
referenced by issues, workflows, work items or pages are reported but never removed.
"""

import json
from datetime import date, timedelta
from pathlib import Path

from django.core.management import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from plane.db.models import DraftIssueLabel, Issue, IssueLabel, Label, PageLabel, State, WorkflowState, WorkflowTransition


class Command(BaseCommand):
    help = "Preview or apply a safe purge of soft-deleted states and labels."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace slug")
        parser.add_argument("--older-than-days", type=int, default=30, help="Minimum age (default: 30)")
        parser.add_argument("--apply", action="store_true", help="Permanently delete (default: dry run)")
        parser.add_argument("--output", help="Optional report path")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=max(0, options["older_than_days"]))
        report = {"workspace": options["workspace"], "cutoff": str(cutoff), "candidates": [], "skipped": []}

        states = State.all_state_objects.filter(
            workspace__slug=options["workspace"],
            deleted_at__isnull=False,
            deleted_at__lte=cutoff,
        ).select_related("project")
        for state in states:
            reasons = []
            if Issue.objects.filter(state=state).exists():
                reasons.append("issues")
            if WorkflowState.objects.filter(state=state).exists():
                reasons.append("workflow_states")
            if WorkflowTransition.objects.filter(Q(from_state=state) | Q(to_state=state)).exists():
                reasons.append("workflow_transitions")
            entry = {
                "kind": "state",
                "id": str(state.id),
                "project": state.project.name if state.project else None,
                "name": state.name,
                "deleted_at": str(state.deleted_at),
                "reasons": reasons,
            }
            if reasons:
                report["skipped"].append(entry)
            else:
                report["candidates"].append(entry)

        labels = Label.all_objects.filter(
            workspace__slug=options["workspace"],
            deleted_at__isnull=False,
            deleted_at__lte=cutoff,
        ).select_related("project")
        for label in labels:
            reasons = []
            if IssueLabel.objects.filter(label=label).exists():
                reasons.append("issues")
            if DraftIssueLabel.objects.filter(label=label).exists():
                reasons.append("drafts")
            if PageLabel.objects.filter(label=label).exists():
                reasons.append("pages")
            if Label.objects.filter(parent=label).exists():
                reasons.append("child_labels")
            entry = {
                "kind": "label",
                "id": str(label.id),
                "project": label.project.name if label.project else None,
                "name": label.name,
                "deleted_at": str(label.deleted_at),
                "reasons": reasons,
            }
            if reasons:
                report["skipped"].append(entry)
            else:
                report["candidates"].append(entry)

        if options["apply"]:
            for entry in report["candidates"]:
                model = State.all_state_objects if entry["kind"] == "state" else Label.all_objects
                model.filter(pk=entry["id"], deleted_at__isnull=False).delete()

        path = Path(options.get("output") or f"var/reports/purge-soft-deleted-{date.today().isoformat()}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        mode = "PURGED" if options["apply"] else "DRY RUN"
        self.stdout.write(
            f"Soft-delete purge {mode}: {len(report['candidates'])} candidate(s), "
            f"{len(report['skipped'])} referenced row(s) kept. Report: {path}"
        )
        for entry in report["candidates"]:
            self.stdout.write(f"  candidate {entry['kind']} {entry['name']} ({entry['id']})")
