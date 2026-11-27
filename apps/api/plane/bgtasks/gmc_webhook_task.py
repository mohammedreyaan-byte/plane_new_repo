# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Inbound provider webhook processing and work item linkage."""

import json
import re
from typing import Any, Dict

from celery import shared_task

from plane.db.models import ExternalWebhookEvent, Issue, IssueLink

REFERENCE_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_]{1,9})-(\d+)\b")


def _payload_text(payload: Dict[str, Any]) -> str:
    return json.dumps(payload)


def _find_issue(workspace_id, text: str):
    for identifier, sequence in REFERENCE_PATTERN.findall(text):
        issue = Issue.objects.filter(
            workspace_id=workspace_id,
            project__identifier__iexact=identifier,
            sequence_id=int(sequence),
        ).first()
        if issue:
            return issue, f"{identifier}-{sequence}"
    return None, ""


@shared_task(bind=True)
def process_webhook_event(self, event_id: str) -> str:
    """Link a verified provider event to any referenced work item."""

    event = ExternalWebhookEvent.objects.select_related("workspace").get(pk=event_id)
    if event.status == "linked":
        return str(event.id)
    issue, reference = _find_issue(event.workspace_id, _payload_text(event.payload or {}))
    detail = event.detail or ""
    if issue:
        url = ""
        payload = event.payload or {}
        if isinstance(payload, dict):
            url = str(
                payload.get("html_url")
                or payload.get("web_url")
                or (payload.get("object_attributes") or {}).get("url", "")
                or ""
            )
        if url:
            IssueLink.objects.get_or_create(
                issue=issue,
                project_id=issue.project_id,
                workspace_id=issue.workspace_id,
                url=url,
                defaults={
                    "title": f"{event.provider} {event.event_type}",
                    "metadata": {"delivery_id": event.delivery_id, "signature_verified": event.signature_verified},
                    "created_by_id": event.created_by_id,
                },
            )
        detail = f"{event.provider} {event.event_type} referenced {reference}" + (f" ({url})" if url else "")
        ExternalWebhookEvent.objects.filter(pk=event.pk).update(work_item=issue, status="linked", detail=detail)
    else:
        ExternalWebhookEvent.objects.filter(pk=event.pk).update(
            status="ignored", detail=detail or "No work item reference"
        )

    from plane.utils.e2e_event_sink import record_e2e_event

    record_e2e_event(
        "events",
        {
            "provider": event.provider,
            "event": event.event_type,
            "delivery_id": event.delivery_id,
            "deliveryId": event.delivery_id,
            "work_item_reference": reference,
            "url": detail,
            "status": event.status,
        },
    )
    return str(event.id)
