# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Read-only label and priority audit for PLN-002."""

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from django.core.management import BaseCommand
from django.db.models import Count

from plane.db.models import Issue, IssueLabel, Label, Project, Workspace

PRIORITIES = ["urgent", "high", "medium", "low", "none"]


class Command(BaseCommand):
    help = "Audit label duplicates and priority usage. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace slug")
        parser.add_argument("--output", help="Optional report path")

    def handle(self, *args, **options):
        slug = options["workspace"]
        workspace = Workspace.objects.filter(slug=slug).first()
        if workspace is None:
            self.stdout.write(f"No workspace found for {slug!r}.")
            return

        labels = list(Label.objects.filter(workspace=workspace).select_related("project"))
        # Labels are workspace scoped, so duplicates must be detected across the
        # whole workspace, not only within one project page.
        names = defaultdict(list)
        for label in labels:
            names[label.name.casefold()].append(str(label.id))
        duplicates = [
            {"name": name, "label_ids": ids} for name, ids in names.items() if len(ids) > 1
        ]

        usage = {
            str(label_id): total
            for label_id, total in Issue.objects.filter(workspace=workspace, deleted_at__isnull=True)
            .values_list("labels__id")
            .annotate(total=Count("id"))
            if label_id is not None
        }
        priorities = dict(
            Issue.objects.filter(workspace=workspace, deleted_at__isnull=True)
            .values_list("priority")
            .annotate(total=Count("id"))
        )

        projects = Project.objects.filter(workspace=workspace, deleted_at__isnull=True)
        soft_deleted = list(Label.all_objects.filter(workspace=workspace, deleted_at__isnull=False))
        type_like = [
            str(label.id)
            for label in labels
            if label.name.casefold().replace("/", ":").replace(" ", "") in {"type:bug", "bug", "task", "story", "epic"}
        ]
        report = {
            "workspace": slug,
            "generated_on": str(date.today()),
            "labels": {
                "active": len(labels),
                "active_labels": [
                    {
                        "id": str(label.id),
                        "name": label.name,
                        "project": label.project.name if label.project else None,
                        "issue_count": usage.get(str(label.id), 0),
                    }
                    for label in labels
                ],
                "soft_deleted": len(soft_deleted),
                "soft_deleted_labels": [
                    {
                        "id": str(label.id),
                        "name": label.name,
                        "issue_count": IssueLabel.objects.filter(label=label).count(),
                    }
                    for label in soft_deleted
                ],
                "duplicates": duplicates,
                "unused": [str(label.id) for label in labels if not usage.get(str(label.id))],
                "type_like": type_like,
            },
            "priorities": {
                key: {"issues": priorities.get(key, 0), "allowed": True} for key in PRIORITIES
            },
            "unexpected_priorities": [
                {"priority": key, "issues": value} for key, value in priorities.items() if key not in PRIORITIES
            ],
            "projects": [{"id": str(p.id), "name": p.name, "identifier": p.identifier} for p in projects],
        }

        path = Path(options.get("output") or f"var/reports/label-audit-{date.today().isoformat()}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.stdout.write(
            f"Label audit: {len(labels)} active, {len(duplicates)} duplicate group(s), "
            f"{len(report['labels']['unused'])} unused. Report: {path}"
        )
