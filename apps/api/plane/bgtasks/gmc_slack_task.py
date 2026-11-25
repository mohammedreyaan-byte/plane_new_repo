# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Slack message delivery and audit logging."""

from typing import Any, Dict, List, Optional

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from plane.db.models import ExternalAccountIntegration, ExternalMessageLog, Issue, SlackChannelSubscription, User


def _message_payload(issue: Issue, event_type: str, origin: Optional[str]) -> Dict[str, Any]:
    workspace_slug = issue.project.workspace.slug
    identifier = f"{issue.project.identifier}-{issue.sequence_id}"
    base = (origin or "").rstrip("/")
    url = f"{base}/{workspace_slug}/browse/{identifier}/" if base else ""
    lines = [f"*{identifier}* {issue.name}", f"Event: {event_type}"]
    if issue.state_id:
        lines.append(f"State: {issue.state.name}")
    if issue.assignees.exists():
        lines.append("Assignees: " + ", ".join(user.display_name or user.email for user in issue.assignees.all()))
    if url:
        lines.append(url)
    text = "\n".join(lines)
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        }
    ]
    return {"text": text, "blocks": blocks, "work_item_identifier": identifier, "url": url}


@shared_task(bind=True)
def dispatch_slack_event(
    self,
    event_type: str,
    project_id: str,
    issue_id: str,
    actor_id: Optional[str] = None,
    origin: Optional[str] = None,
) -> List[str]:
    """Post a work item event to every subscribed Slack channel."""

    from plane.utils.gmc_integrations import ProviderAPIError, post_slack_message

    issue = Issue.all_objects.select_related("project", "project__workspace", "state").get(pk=issue_id)
    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    payload = _message_payload(issue, event_type, origin)
    log_ids: List[str] = []

    subscriptions = (
        SlackChannelSubscription.objects.filter(
            is_active=True,
            integration__is_active=True,
            integration__provider="slack",
            integration__workspace_id=issue.workspace_id,
        )
        .filter(Q(project__isnull=True) | Q(project_id=issue.project_id))
        .select_related("integration")
    )
    for subscription in subscriptions:
        events = subscription.events or {}
        if not events.get(event_type):
            continue
        token = subscription.integration.get_access_token()
        if not token:
            continue
        status = "sent"
        error = ""
        provider_message_id = ""
        try:
            response = post_slack_message(token, subscription.channel_id, payload["text"], payload["blocks"])
            provider_message_id = str(response.get("ts", ""))
            SlackChannelSubscription.objects.filter(pk=subscription.pk).update(
                last_posted_at=timezone.now(), last_error=""
            )
        except ProviderAPIError as exc:
            status = "failed"
            error = str(exc)
            SlackChannelSubscription.objects.filter(pk=subscription.pk).update(last_error=error)
        log = ExternalMessageLog.objects.create(
            workspace_id=issue.workspace_id,
            project_id=project_id,
            integration=subscription.integration,
            provider="slack",
            event_type=event_type,
            channel=subscription.channel_name,
            work_item=issue,
            status=status,
            provider_message_id=provider_message_id,
            error=error,
            sent_at=timezone.now() if status == "sent" else None,
            metadata={"work_item": payload["work_item_identifier"], "url": payload["url"], "actor": actor.email if actor else ""},
        )
        log_ids.append(str(log.id))
    return log_ids


@shared_task(bind=True)
def send_slack_test_message(self, integration_id: str, channel_id: str) -> str:
    """Send a real test message to a selected Slack channel."""

    from plane.utils.gmc_integrations import ProviderAPIError, post_slack_message

    integration = ExternalAccountIntegration.objects.get(pk=integration_id, provider="slack")
    subscription = SlackChannelSubscription.objects.get(integration=integration, channel_id=channel_id, is_active=True)
    token = integration.get_access_token()
    if not token:
        raise ValueError("Slack token is unavailable")
    status = "sent"
    error = ""
    message_id = ""
    try:
        response = post_slack_message(
            token,
            channel_id,
            "Plane Slack integration test. This message confirms the connection works.",
        )
        message_id = str(response.get("ts", ""))
    except ProviderAPIError as exc:
        status = "failed"
        error = str(exc)
    log = ExternalMessageLog.objects.create(
        workspace_id=integration.workspace_id,
        project=integration.project,
        integration=integration,
        provider="slack",
        event_type="test",
        channel=subscription.channel_name,
        status=status,
        provider_message_id=message_id,
        error=error,
        sent_at=timezone.now() if status == "sent" else None,
        metadata={"source": "test"},
    )
    return str(log.id)
