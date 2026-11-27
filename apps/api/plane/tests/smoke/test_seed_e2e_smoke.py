# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Smoke coverage of the PLN-026 seed command's counts, determinism and reset."""

import pytest
from django.core.management import call_command
from django.utils import timezone

from plane.db.management.commands import seed_e2e
from plane.db.models.issue import IssueAttachment
from plane.db.models import (
    Cycle,
    Issue,
    IssueComment,
    IssueType,
    Label,
    Module,
    Project,
    State,
    User,
    Webhook,
    Workspace,
    Workflow,
    IssueView,
)

pytestmark = [pytest.mark.smoke, pytest.mark.slow]


def _seed(monkeypatch, slug, *extra_args):
    for name in (seed_e2e.PASSWORD_ENV, seed_e2e.TARGET_ENV_NAME, "PLANE_ENV", "DEPLOY_ENV", "APP_ENV", "ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(seed_e2e.TARGET_ENV_NAME, "local")
    call_command("seed_e2e", "--workspace", slug, "--project", "E2E", *extra_args)


def _snapshot(slug):
    workspace = Workspace.objects.get(slug=slug)
    project = Project.objects.get(workspace=workspace, identifier="E2E")
    return {
        "users": list(
            User.objects.filter(email__endswith=f"@{slug}.example.invalid")
            .order_by("email")
            .values_list("email", flat=True)
        ),
        "types": list(IssueType.objects.filter(workspace=workspace).order_by("key").values_list("key", flat=True)),
        "workflows": list(Workflow.objects.filter(project=project).order_by("name").values_list("name", flat=True)),
        "states": list(
            State.all_state_objects.filter(project=project).order_by("sequence").values_list("name", flat=True)
        ),
        "labels": list(Label.objects.filter(project=project).order_by("name").values_list("name", flat=True)),
        "cycles": list(Cycle.objects.filter(project=project).order_by("name").values_list("name", flat=True)),
        "modules": list(Module.objects.filter(project=project).order_by("name").values_list("name", flat=True)),
        "views": list(IssueView.objects.filter(project=project).order_by("name").values_list("name", flat=True)),
        "items": list(
            Issue.all_objects.filter(project=project)
            .order_by("external_id")
            .values_list("external_id", "name", "state__name", "type__key")
        ),
        "comments": list(
            IssueComment.objects.filter(project=project)
            .order_by("external_id")
            .values_list("external_id", "comment_html")
        ),
        "attachments": list(
            IssueAttachment.objects.filter(project=project)
            .order_by("external_id")
            .values_list("external_id", flat=True)
        ),
        "webhooks": list(Webhook.objects.filter(workspace=workspace).order_by("url").values_list("url", flat=True)),
    }


def _assert_expected_counts(slug):
    workspace = Workspace.objects.get(slug=slug)
    project = Project.objects.get(workspace=workspace, identifier="E2E")
    assert User.objects.filter(email__endswith=f"@{slug}.example.invalid").count() == seed_e2e.EXPECTED_COUNTS["users"]
    assert IssueType.objects.filter(workspace=workspace).count() == seed_e2e.EXPECTED_COUNTS["work_item_types"]
    assert Workflow.objects.filter(project=project).count() == seed_e2e.EXPECTED_COUNTS["workflows"]
    assert State.all_state_objects.filter(project=project).count() == seed_e2e.EXPECTED_COUNTS["states"]
    assert Label.objects.filter(project=project).count() == seed_e2e.EXPECTED_COUNTS["labels"]
    assert Cycle.objects.filter(project=project).count() == seed_e2e.EXPECTED_COUNTS["cycles"]
    assert Module.objects.filter(project=project).count() == seed_e2e.EXPECTED_COUNTS["modules"]
    assert IssueView.objects.filter(project=project).count() == seed_e2e.EXPECTED_COUNTS["views"]
    assert Issue.all_objects.filter(project=project).count() == seed_e2e.EXPECTED_COUNTS["work_items"]
    assert IssueComment.objects.filter(project=project).count() == seed_e2e.EXPECTED_COUNTS["comments"]
    assert IssueAttachment.objects.filter(project=project).count() == seed_e2e.EXPECTED_COUNTS["attachments"]
    assert Webhook.objects.filter(workspace=workspace).count() == seed_e2e.EXPECTED_COUNTS["webhooks"]


@pytest.mark.smoke
@pytest.mark.slow
def test_seed_with_documented_command_creates_expected_counts(db, monkeypatch, capsys):
    _seed(monkeypatch, "e2e", "--reset")
    output = capsys.readouterr().out

    _assert_expected_counts("e2e")
    assert "E2E seed counts" in output
    for key, value in seed_e2e.EXPECTED_COUNTS.items():
        assert f"{key:<18} {value}" in output
    assert Cycle.objects.filter(
        name__contains="(active)",
        start_date__lte=timezone.now(),
        end_date__gte=timezone.now(),
    ).exists()


@pytest.mark.smoke
@pytest.mark.slow
def test_seed_is_deterministic_and_idempotent(db, monkeypatch):
    slug = "e2e-idempotent"
    _seed(monkeypatch, slug, "--reset")
    first = _snapshot(slug)

    _seed(monkeypatch, slug)
    second = _snapshot(slug)

    assert first == second
    _assert_expected_counts(slug)


@pytest.mark.smoke
@pytest.mark.slow
def test_reset_removes_extra_rows_and_restores_deterministic_data(db, monkeypatch):
    slug = "e2e-reset"
    _seed(monkeypatch, slug, "--reset")
    expected = _snapshot(slug)
    workspace = Workspace.objects.get(slug=slug)
    project = Project.objects.get(workspace=workspace, identifier="E2E")

    Issue.objects.create(project=project, name="Stray E2E item", external_source="manual-test")
    Label.objects.create(project=project, name="Stray E2E label")

    _seed(monkeypatch, slug, "--reset")

    assert _snapshot(slug) == expected
    assert not Issue.all_objects.filter(project=project, name="Stray E2E item").exists()
    assert not Label.objects.filter(project=project, name="Stray E2E label").exists()
    _assert_expected_counts(slug)
