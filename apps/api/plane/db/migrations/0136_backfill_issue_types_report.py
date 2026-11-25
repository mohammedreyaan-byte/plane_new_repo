# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Backfill ``issues.type_id`` for projects with work item types enabled (PLN-004).

Re-runnable and deliberately reportable. It only touches projects where the feature
flag is on, and it removes the temporary ``type: bug`` label link after using it.
The report is printed and logged as JSON: ``{scanned, updated, skipped,
bugs_from_label, label_links_removed}``.
"""

import json
import logging

from django.db import migrations
from django.utils import timezone

logger = logging.getLogger("plane.migrations")

BATCH_SIZE = 500
BUG_LABEL = "type: bug"


def backfill(apps, schema_editor):
    Project = apps.get_model("db", "Project")
    ProjectIssueType = apps.get_model("db", "ProjectIssueType")
    Issue = apps.get_model("db", "Issue")
    IssueLabel = apps.get_model("db", "IssueLabel")
    Label = apps.get_model("db", "Label")

    report = {
        "scanned": 0,
        "updated": 0,
        "skipped": 0,
        "bugs_from_label": 0,
        "label_links_removed": 0,
    }

    for project in Project.objects.filter(is_issue_type_enabled=True).iterator(chunk_size=BATCH_SIZE):
        defaults = (
            ProjectIssueType.objects.filter(project_id=project.pk, is_default=True, deleted_at__isnull=True)
            .select_related("issue_type")
            .first()
        )
        bug_row = (
            ProjectIssueType.objects.filter(
                project_id=project.pk,
                issue_type__key="bug",
                is_enabled=True,
                deleted_at__isnull=True,
            )
            .select_related("issue_type")
            .first()
        )
        if defaults is None or bug_row is None:
            # A broken configuration must not silently assign the wrong type.
            report["skipped"] += Issue.issue_objects.filter(project_id=project.pk).count()
            continue

        label_ids = list(
            Label.objects.filter(
                project_id=project.pk,
                name__iexact=BUG_LABEL,
                deleted_at__isnull=True,
            ).values_list("pk", flat=True)
        )
        bug_label_issue_ids = set()
        label_link_pks = []
        if label_ids:
            links = IssueLabel.objects.filter(
                issue__project_id=project.pk,
                label_id__in=label_ids,
                deleted_at__isnull=True,
            ).only("pk", "issue_id")
            for link in links.iterator(chunk_size=BATCH_SIZE):
                bug_label_issue_ids.add(link.issue_id)
                label_link_pks.append(link.pk)

        now = timezone.now()
        for issue in Issue.issue_objects.filter(project_id=project.pk).iterator(chunk_size=BATCH_SIZE):
            report["scanned"] += 1
            # The backfill only seeds missing types. An issue that already has a
            # type (including one assigned by an earlier run) must never be
            # rewritten, otherwise the migration is not re-runnable.
            if issue.type_id is not None:
                report["skipped"] += 1
                continue
            from_label = issue.pk in bug_label_issue_ids
            target_id = bug_row.issue_type_id if from_label else defaults.issue_type_id
            Issue.issue_objects.filter(pk=issue.pk).update(type_id=target_id, updated_at=now)
            report["updated"] += 1
            if from_label:
                report["bugs_from_label"] += 1

        if label_link_pks:
            for start in range(0, len(label_link_pks), BATCH_SIZE):
                batch = label_link_pks[start : start + BATCH_SIZE]
                report["label_links_removed"] += IssueLabel.objects.filter(pk__in=batch, deleted_at__isnull=True).update(
                    deleted_at=now, updated_at=now
                )

    message = json.dumps(report, sort_keys=True)
    logger.info("backfill_issue_types %s", message)
    print(f"backfill_issue_types {message}")


class Migration(migrations.Migration):
    dependencies = [("db", "0135_label_parent_set_null")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
