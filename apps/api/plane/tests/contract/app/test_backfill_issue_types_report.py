# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Focused tests for the reportable issue-type backfill migration (PLN-004)."""

import importlib
import json

import pytest
from django.apps import apps

from plane.db.models import Issue, IssueLabel, Label, Project, ProjectIssueType
from plane.tests.workflow_helpers import make_project

pytestmark = pytest.mark.contract

migration = importlib.import_module("plane.db.migrations.0136_backfill_issue_types_report")


def _report(capsys):
    migration.backfill(apps, None)
    output = capsys.readouterr().out
    line = next(line for line in output.splitlines() if line.startswith("backfill_issue_types "))
    return json.loads(line.split(" ", 1)[1])


@pytest.mark.django_db
def test_backfill_is_reportable_re_runnable_and_respects_the_feature_flag(workspace, create_user, capsys):
    enabled = make_project(workspace, create_user, identifier="BF", governed=True)
    disabled = make_project(workspace, create_user, identifier="OFF", governed=False)
    Project.objects.filter(pk=disabled.pk).update(is_issue_type_enabled=False)

    bug_label = Label.objects.create(name="type: bug", project=enabled, workspace=workspace)
    labelled = Issue.objects.create(project=enabled, workspace=workspace, name="from label")
    plain = Issue.objects.create(project=enabled, workspace=workspace, name="no label")
    typed = Issue.objects.create(project=enabled, workspace=workspace, name="already typed")
    typed.type = ProjectIssueType.objects.get(project=enabled, is_default=True).issue_type
    typed.save(update_fields=["type", "updated_at"])
    label_link = IssueLabel.objects.create(
        issue=labelled, label=bug_label, project=enabled, workspace=workspace
    )
    legacy = Issue.objects.create(project=disabled, workspace=workspace, name="legacy")

    first = _report(capsys)
    assert first == {
        "scanned": 3,
        "updated": 2,
        "skipped": 1,
        "bugs_from_label": 1,
        "label_links_removed": 1,
    }

    labelled.refresh_from_db()
    plain.refresh_from_db()
    legacy.refresh_from_db()
    assert labelled.type.key == "bug"
    assert plain.type.key == "task"
    assert legacy.type_id is None
    assert not IssueLabel.objects.filter(pk=label_link.pk).exists()
    assert IssueLabel.all_objects.get(pk=label_link.pk).deleted_at is not None

    second = _report(capsys)
    assert second == {
        "scanned": 3,
        "updated": 0,
        "skipped": 3,
        "bugs_from_label": 0,
        "label_links_removed": 0,
    }
