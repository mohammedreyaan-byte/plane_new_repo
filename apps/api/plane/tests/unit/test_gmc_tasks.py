# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for GMC background processing against real database records."""

from unittest.mock import patch

import pytest

from plane.bgtasks.gmc_automation_task import evaluate_issue_event
from plane.bgtasks.gmc_event_dispatch import dispatch_gmc_issue_event
from plane.bgtasks.gmc_import_task import process_import_job
from plane.bgtasks.gmc_slack_task import dispatch_slack_event
from plane.bgtasks.gmc_webhook_task import process_webhook_event
from plane.db.models import (
    APIToken,
    AutomationRule,
    AutomationRun,
    ExternalAccountIntegration,
    ExternalMessageLog,
    ExternalWebhookEvent,
    Importer,
    Issue,
    IssueLink,
    Project,
    ProjectMember,
    SlackChannelSubscription,
    State,
)
from plane.license.utils.encryption import encrypt_data

pytestmark = pytest.mark.unit


@pytest.fixture
def gmc_project(db, create_user, workspace):
    project = Project.objects.create(name="GMC Project", identifier="GMC", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(workspace=workspace, project=project, member=create_user, role=20)
    State.objects.create(
        name="Todo",
        project=project,
        workspace=workspace,
        group="unstarted",
        color="#000000",
        default=True,
    )
    return project


def test_csv_import_creates_real_work_items(gmc_project, workspace, create_user):
    token = APIToken.objects.create(user=create_user, workspace=workspace, label="gmc-import")
    content = "Title,Description,State,Priority\nImported item,Imported description,Todo,High\n"
    importer = Importer.objects.create(
        project=gmc_project,
        workspace=workspace,
        initiated_by=create_user,
        token=token,
        service="csv",
        status="queued",
        config={"csv_content": encrypt_data(content)},
    )

    process_import_job.run(str(importer.id))

    importer.refresh_from_db()
    assert importer.status == "completed"
    assert importer.total_count == 1
    assert importer.created_count == 1
    assert importer.error_count == 0
    assert importer.progress == 100
    issue = Issue.objects.get(project=gmc_project, name="Imported item")
    assert issue.priority == "high"
    assert issue.external_source == "import"


def test_automation_applies_actions_and_records_audit(gmc_project, workspace, create_user):
    rule = AutomationRule.objects.create(
        project=gmc_project,
        workspace=workspace,
        name="Set priority",
        trigger="state_changed",
        conditions=[{"field": "state", "operator": "is", "value": "Todo"}],
        actions=[{"type": "set_priority", "value": "High"}],
        created_by=create_user,
    )
    issue = Issue.objects.create(
        project=gmc_project,
        workspace=workspace,
        name="Automation target",
        state=State.objects.get(project=gmc_project, name="Todo"),
        created_by=create_user,
    )

    run_ids = evaluate_issue_event.run(
        trigger="state_changed",
        project_id=str(gmc_project.id),
        issue_id=str(issue.id),
        actor_id=str(create_user.id),
    )

    assert len(run_ids) == 1
    run = AutomationRun.objects.get(pk=run_ids[0])
    assert run.status == AutomationRun.Status.SUCCESS
    assert "Priority set to high" in run.message
    issue.refresh_from_db()
    assert issue.priority == "high"
    rule.refresh_from_db()
    assert rule.last_evaluated_at is not None


def test_automation_skips_rules_whose_conditions_do_not_match(gmc_project, workspace, create_user):
    AutomationRule.objects.create(
        project=gmc_project,
        workspace=workspace,
        name="Only completed",
        trigger="state_changed",
        conditions=[{"field": "state", "operator": "is", "value": "Done"}],
        actions=[{"type": "set_priority", "value": "High"}],
        created_by=create_user,
    )
    issue = Issue.objects.create(
        project=gmc_project,
        workspace=workspace,
        name="Not matched",
        state=State.objects.get(project=gmc_project, name="Todo"),
        created_by=create_user,
    )

    assert (
        evaluate_issue_event.run(
            trigger="state_changed",
            project_id=str(gmc_project.id),
            issue_id=str(issue.id),
            actor_id=str(create_user.id),
        )
        == []
    )
    assert AutomationRun.objects.count() == 0


def test_slack_dispatch_only_uses_subscriptions_for_the_workspace_and_project(gmc_project, workspace, create_user):
    integration = ExternalAccountIntegration.objects.create(
        workspace=workspace,
        provider="slack",
        provider_account_id="T123",
        account_name="Company Slack",
        created_by=create_user,
    )
    integration.set_access_token("xoxb-token")
    integration.save()
    SlackChannelSubscription.objects.create(
        workspace=workspace,
        integration=integration,
        channel_id="C-GLOBAL",
        channel_name="global",
        events={"work_item.created": True},
        created_by=create_user,
    )
    SlackChannelSubscription.objects.create(
        workspace=workspace,
        project=gmc_project,
        integration=integration,
        channel_id="C-PROJECT",
        channel_name="project",
        events={"work_item.created": True},
        created_by=create_user,
    )
    other_project = Project.objects.create(
        name="Other Project", identifier="OTH", workspace=workspace, created_by=create_user
    )
    SlackChannelSubscription.objects.create(
        workspace=workspace,
        project=other_project,
        integration=integration,
        channel_id="C-OTHER",
        channel_name="other",
        events={"work_item.created": True},
        created_by=create_user,
    )
    issue = Issue.objects.create(
        project=gmc_project,
        workspace=workspace,
        name="Slack target",
        state=State.objects.get(project=gmc_project, name="Todo"),
        created_by=create_user,
    )

    with patch("plane.utils.gmc_integrations.post_slack_message", return_value={"ts": "123.456"}) as post:
        log_ids = dispatch_slack_event.run(
            event_type="work_item.created",
            project_id=str(gmc_project.id),
            issue_id=str(issue.id),
            actor_id=str(create_user.id),
            origin="https://plane.company.example",
        )

    assert len(log_ids) == 2
    assert post.call_count == 2
    assert {call.args[1] for call in post.call_args_list} == {"C-GLOBAL", "C-PROJECT"}
    assert ExternalMessageLog.objects.count() == 2
    assert all(log.status == "sent" for log in ExternalMessageLog.objects.all())


def test_webhook_event_links_referenced_work_item(gmc_project, workspace, create_user):
    issue = Issue.objects.create(
        project=gmc_project,
        workspace=workspace,
        name="Webhook target",
        state=State.objects.get(project=gmc_project, name="Todo"),
        created_by=create_user,
    )
    reference = f"{gmc_project.identifier}-{issue.sequence_id}"
    event = ExternalWebhookEvent.objects.create(
        workspace=workspace,
        provider="github",
        event_type="push",
        delivery_id="delivery-1",
        signature_verified=True,
        payload={
            "body": f"Fixes {reference}",
            "html_url": "https://github.com/company/repo/commit/abc",
        },
        created_by=create_user,
    )

    process_webhook_event.run(str(event.id))

    event.refresh_from_db()
    assert event.status == "linked"
    assert event.work_item_id == issue.id
    assert IssueLink.objects.filter(issue=issue, url="https://github.com/company/repo/commit/abc").exists()


def test_activity_dispatch_queues_automation_and_slack_only_for_relevant_events(gmc_project, create_user):
    AutomationRule.objects.create(
        project=gmc_project,
        workspace=gmc_project.workspace,
        name="Created rule",
        trigger="created",
        actions=[{"type": "add_comment", "value": "Automated comment"}],
        created_by=create_user,
    )
    issue = Issue.objects.create(
        project=gmc_project,
        workspace=gmc_project.workspace,
        name="Activity target",
        state=State.objects.get(project=gmc_project, name="Todo"),
        created_by=create_user,
    )

    with patch(
        "plane.bgtasks.gmc_event_dispatch.evaluate_issue_event.delay"
    ) as evaluate, patch("plane.bgtasks.gmc_event_dispatch.dispatch_slack_event.delay") as slack:
        dispatch_gmc_issue_event(
            activity_type="issue.activity.created",
            requested_data='{"name": "Activity target"}',
            current_instance=None,
            issue_id=str(issue.id),
            project_id=str(gmc_project.id),
            actor_id=str(create_user.id),
            origin="https://plane.company.example",
        )
        evaluate.assert_called_once()
        assert evaluate.call_args.kwargs["trigger"] == "created"
        slack.assert_called_once()
        assert slack.call_args.kwargs["event_type"] == "work_item.created"

    with patch(
        "plane.bgtasks.gmc_event_dispatch.evaluate_issue_event.delay"
    ) as evaluate, patch("plane.bgtasks.gmc_event_dispatch.dispatch_slack_event.delay") as slack:
        dispatch_gmc_issue_event(
            activity_type="comment.activity.created",
            requested_data={},
            current_instance={},
            issue_id=str(issue.id),
            project_id=str(gmc_project.id),
            actor_id=str(create_user.id),
            origin=None,
        )
        evaluate.assert_not_called()
        slack.assert_called_once()
        assert slack.call_args.kwargs["event_type"] == "work_item.commented"
