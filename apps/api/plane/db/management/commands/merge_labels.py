# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Merge duplicate labels into a target label. Dry-run by default (PLN-002)."""

import json
from datetime import date

from django.core.management import BaseCommand, CommandError

from plane.utils.labels import merge_labels


class Command(BaseCommand):
    help = "Preview or apply a workspace-scoped label merge."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace slug")
        parser.add_argument("--target", required=True, help="Label id to keep")
        parser.add_argument("--source", action="append", required=True, help="Label id to merge (repeatable)")
        parser.add_argument("--apply", action="store_true", help="Apply the merge; default is a preview")
        parser.add_argument("--output", help="Optional report path")

    def handle(self, *args, **options):
        try:
            preview = merge_labels(
                workspace_slug=options["workspace"],
                target_id=options["target"],
                source_ids=options["source"],
                actor=None,
                dry_run=not options["apply"],
            )
        except ValueError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(
            f"Label merge {'APPLIED' if preview.get('merged') else 'PREVIEW'}: "
            f"target={preview['target']['name']}, sources={len(preview['sources'])}, "
            f"affected issues={preview['affected_issue_count']}"
        )
        if preview.get("skipped"):
            self.stdout.write(f"Skipped (already removed): {', '.join(preview['skipped'])}")

        report = json.dumps(preview, indent=2, sort_keys=True)
        if options["output"]:
            path = options["output"]
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(report)
        elif not options["apply"]:
            self.stdout.write(report)
        else:
            self.stdout.write(f"Review: var/reports/label-merge-{date.today().isoformat()}.json")
