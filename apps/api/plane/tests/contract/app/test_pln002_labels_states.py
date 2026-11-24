# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Focused PLN-002 tests for priority sorting, label validation/merge and state defaults."""

import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from plane.app.serializers.issue import IssueCreateSerializer
from plane.db.models import Issue, IssueLabel, Label, State, WorkflowState
from plane.tests.workflow_helpers import client_for, make_project, state_of
from plane.utils.labels import merge_labels, validate_label_attrs
from plane.utils.order_queryset import PRIORITY_ORDER, order_issue_queryset

pytestmark = pytest.mark.contract


@pytest.mark.django_db
def test_priority_sort_is_semantic_in_both_directions(workspace, create_user):
    project = make_project(workspace, create_user, governed=False)
    for priority in reversed(PRIORITY_ORDER):
        Issue.objects.create(project=project, workspace=workspace, name=priority, priority=priority)

    queryset = Issue.objects.filter(project=project)
    ordered, _ = order_issue_queryset(queryset, "priority")
    assert [issue.priority for issue in ordered] == PRIORITY_ORDER
    ordered, _ = order_issue_queryset(queryset, "-priority")
    assert [issue.priority for issue in ordered] == PRIORITY_ORDER[::-1]


@pytest.mark.django_db
def test_label_validation_codes_for_duplicate_colour_cycle_and_depth(workspace):
    root = Label.objects.create(workspace=workspace, name="Root", color="#123456")
    child = Label.objects.create(workspace=workspace, name="Child", parent=root, color="#abcdef")
    grandchild = Label.objects.create(workspace=workspace, name="Grandchild", parent=child, color="")

    with pytest.raises(ValidationError) as duplicate:
        validate_label_attrs({"name": " root "}, workspace_id=workspace.id)
    assert duplicate.value.detail["error"]["code"] == "duplicate_label_name"

    with pytest.raises(ValidationError) as color:
        validate_label_attrs({"color": "red"}, instance=root, workspace_id=workspace.id)
    assert color.value.detail["error"]["code"] == "invalid_label_color"

    with pytest.raises(ValidationError) as cycle:
        validate_label_attrs({"parent": grandchild}, instance=root, workspace_id=workspace.id)
    assert cycle.value.detail["error"]["code"] == "label_cycle"

    with pytest.raises(ValidationError) as depth:
        validate_label_attrs({"parent": grandchild}, workspace_id=workspace.id)
    assert depth.value.detail["error"]["code"] == "label_depth_exceeded"


@pytest.mark.django_db
def test_merge_labels_preview_and_apply(workspace, create_user):
    project = make_project(workspace, create_user, governed=False)
    target = Label.objects.create(workspace=workspace, name="Bug", color="#ff0000")
    source = Label.objects.create(workspace=workspace, name="bug", color="#00ff00")
    issue = Issue.objects.create(project=project, workspace=workspace, name="merged")
    IssueLabel.objects.create(issue=issue, label=target, project=project, workspace=workspace)
    IssueLabel.objects.create(issue=issue, label=source, project=project, workspace=workspace)

    kwargs = {"workspace_slug": workspace.slug, "target_id": target.id, "source_ids": [source.id]}
    preview = merge_labels(**kwargs, dry_run=True)
    assert preview["merged"] is False
    assert preview["affected_issue_count"] == 1
    assert IssueLabel.objects.filter(label=source).exists()

    result = merge_labels(**kwargs, dry_run=False)
    assert result["merged"] is True
    assert not IssueLabel.objects.filter(label=source).exists()
    assert IssueLabel.objects.filter(label=target, issue=issue).count() == 1
    source.refresh_from_db()
    assert source.deleted_at is not None


@pytest.mark.django_db
def test_issue_serializer_rejects_more_than_ten_labels(workspace, create_user):
    project = make_project(workspace, create_user, governed=False)
    labels = [Label.objects.create(workspace=workspace, name=f"Label {index}", color="#123456") for index in range(11)]

    serializer = IssueCreateSerializer(
        data={"name": "too many labels", "label_ids": [label.id for label in labels]},
        context={"project_id": project.id},
    )

    assert not serializer.is_valid()
    assert "10 labels" in str(serializer.errors["label_ids"])


@pytest.mark.django_db
def test_mark_as_default_requires_workflow_impact_confirmation(workspace, create_user):
    project = make_project(workspace, create_user, governed=True)
    target = state_of(project, "Todo")
    admin = client_for(create_user)
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/states/{target.id}/mark-default/"

    blocked = admin.post(url, {}, format="json")
    assert blocked.status_code == 409
    assert blocked.data["error"]["code"] == "workflow_impact_confirmation_required"
    assert blocked.data["error"]["details"]["affected_workflows"]

    confirmed = admin.post(url, {"confirm_workflow_impact": True}, format="json")
    assert confirmed.status_code == 204

    target.refresh_from_db()
    assert target.default is True
    assert not State.objects.filter(project=project, default=True).exclude(pk=target.pk).exists()
    assert WorkflowState.objects.filter(workflow__project=project, state=target, is_initial=True).count() == 4


@pytest.mark.django_db
def test_audit_commands_report_real_issue_counts(workspace, create_user, tmp_path):
    project = make_project(workspace, create_user, governed=False)
    state = state_of(project, "Todo")
    label = Label.objects.create(workspace=workspace, name="Audit", color="#123456")
    issue = Issue.objects.create(project=project, workspace=workspace, name="counted", state=state)
    IssueLabel.objects.create(issue=issue, label=label, project=project, workspace=workspace)

    state_report = tmp_path / "states.json"
    call_command("audit_states", workspace=workspace.slug, output=str(state_report))
    project_report = json.loads(state_report.read_text(encoding="utf-8"))["projects"][0]
    state_entry = next(
        item for item in project_report["active_states_by_group"]["unstarted"] if item["id"] == str(state.id)
    )
    assert state_entry["issues"] == 1

    label_report = tmp_path / "labels.json"
    call_command("audit_labels", workspace=workspace.slug, output=str(label_report))
    label_report = json.loads(label_report.read_text(encoding="utf-8"))
    assert label_report["labels"]["active_labels"][0]["issue_count"] == 1
    assert label_report["labels"]["duplicates"] == []


@pytest.mark.django_db
def test_repair_states_is_dry_run_then_idempotent(workspace, create_user, tmp_path):
    project = make_project(workspace, create_user, governed=False)
    duplicate = State.objects.create(
        project=project, workspace=workspace, name="todo", slug="todo-duplicate", group="unstarted"
    )
    report = tmp_path / "repair.json"

    call_command("repair_states", workspace=workspace.slug, output=str(report))
    actions = json.loads(report.read_text(encoding="utf-8"))
    assert any(action["action"] == "merge_state" and action["from"] == str(duplicate.id) for action in actions)
    assert State.objects.filter(project=project, deleted_at__isnull=True).count() == 2

    call_command("repair_states", workspace=workspace.slug, apply=True, output=str(report))
    assert not State.objects.filter(pk=duplicate.pk, deleted_at__isnull=True).exists()

    call_command("repair_states", workspace=workspace.slug, apply=True, output=str(report))
    second_run = json.loads(report.read_text(encoding="utf-8"))
    assert not any(action["action"] == "merge_state" for action in second_run)


@pytest.mark.django_db
def test_merge_labels_command_previews_then_applies(workspace, create_user, tmp_path):
    project = make_project(workspace, create_user, governed=False)
    target = Label.objects.create(workspace=workspace, name="Bug", color="#ff0000")
    source = Label.objects.create(workspace=workspace, name="bug", color="#00ff00")
    issue = Issue.objects.create(project=project, workspace=workspace, name="merge command")
    IssueLabel.objects.create(issue=issue, label=source, project=project, workspace=workspace)
    report = tmp_path / "merge.json"
    options = {"workspace": workspace.slug, "target": str(target.id), "source": [str(source.id)]}

    call_command("merge_labels", **options, output=str(report))
    assert json.loads(report.read_text(encoding="utf-8"))["merged"] is False
    assert IssueLabel.objects.filter(label=source).exists()

    call_command("merge_labels", **options, apply=True, output=str(report))
    assert json.loads(report.read_text(encoding="utf-8"))["merged"] is True
    assert not IssueLabel.objects.filter(label=source).exists()


@pytest.mark.django_db
def test_purge_soft_deleted_refuses_references_and_applies_dry_run(workspace, create_user, tmp_path):
    project = make_project(workspace, create_user, governed=False)
    old = timezone.now() - timedelta(days=40)
    unreferenced = Label.objects.create(workspace=workspace, name="old", color="#000000")
    referenced = Label.objects.create(workspace=workspace, name="used", color="#111111")
    issue = Issue.objects.create(project=project, workspace=workspace, name="keeps label")
    IssueLabel.objects.create(issue=issue, label=referenced, project=project, workspace=workspace)
    Label.all_objects.filter(pk__in=[unreferenced.pk, referenced.pk]).update(deleted_at=old)
    report = tmp_path / "purge.json"

    call_command("purge_soft_deleted", workspace=workspace.slug, output=str(report))
    preview = json.loads(report.read_text(encoding="utf-8"))
    assert [item["id"] for item in preview["candidates"]] == [str(unreferenced.id)]
    assert preview["skipped"][0]["reasons"] == ["issues"]
    assert Label.all_objects.filter(pk__in=[unreferenced.pk, referenced.pk]).count() == 2

    call_command("purge_soft_deleted", workspace=workspace.slug, apply=True, output=str(report))
    assert not Label.all_objects.filter(pk=unreferenced.pk).exists()
    assert Label.all_objects.filter(pk=referenced.pk).exists()
