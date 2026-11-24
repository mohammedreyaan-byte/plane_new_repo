# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Give existing work items a type (PLN-004). Re-runnable, reports counts.

    python manage.py backfill_issue_types --workspace <slug> --project <IDENTIFIER> [--dry-run]

* Work items without a type get the project's default type (Task).
* Work items carrying the label ``type: bug`` become Bugs and lose that label link.
* Only projects that have types enabled are touched.

Prints {scanned, updated, skipped, bugs_from_label}. Run it on a copy of the database first.
"""

import json

from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from plane.db.models import Issue, IssueLabel, Project
from plane.utils.issue_types import get_default_issue_type
from plane.db.models import IssueType

BATCH = 500
BUG_LABEL = "type: bug"


class Command(BaseCommand):
    help = "Backfill work item types for a project."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--project", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        project = Project.objects.filter(workspace__slug=options["workspace"], identifier=options["project"]).first()
        if project is None:
            raise CommandError("Project not found.")
        if not project.is_issue_type_enabled:
            raise CommandError("Work item types are not enabled on this project. Run enable_work_item_types first.")

        dry = options["dry_run"]
        default_type = get_default_issue_type(project.id)
        bug_type = IssueType.objects.filter(workspace=project.workspace, key="bug").first()
        if default_type is None or bug_type is None:
            raise CommandError("Default types are missing for this project.")

        # Items that already have a type (and are not label-migrated bugs) are left alone.
        already_typed = Issue.objects.filter(project=project, type__isnull=False).count()
        report = {"scanned": 0, "updated": 0, "skipped": already_typed, "bugs_from_label": 0, "dry_run": dry}

        # 1. type: bug label -> Bug
        bug_issue_ids = list(
            IssueLabel.objects.filter(project=project, label__name__iexact=BUG_LABEL).values_list("issue_id", flat=True)
        )
        with transaction.atomic():
            for chunk_start in range(0, len(bug_issue_ids), BATCH):
                chunk = bug_issue_ids[chunk_start : chunk_start + BATCH]
                report["scanned"] += len(chunk)
                if not dry:
                    Issue.objects.filter(pk__in=chunk).update(type=bug_type)
                    IssueLabel.objects.filter(issue_id__in=chunk, label__name__iexact=BUG_LABEL).update(
                        deleted_at=timezone.now()
                    )
                report["updated"] += len(chunk)
                report["bugs_from_label"] += len(chunk)

            # 2. everything else without a type -> project default
            pending = Issue.objects.filter(project=project, type__isnull=True)
            if dry:
                count = pending.exclude(pk__in=bug_issue_ids).count()
                report["scanned"] += count
                report["updated"] += count
            else:
                while True:
                    ids = list(pending.values_list("pk", flat=True)[:BATCH])
                    if not ids:
                        break
                    report["scanned"] += len(ids)
                    report["updated"] += len(ids)
                    Issue.objects.filter(pk__in=ids).update(type=default_type)

        self.stdout.write(json.dumps(report, indent=2))
