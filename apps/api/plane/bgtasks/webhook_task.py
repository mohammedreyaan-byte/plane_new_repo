# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import hmac
import json
import logging
import uuid

import requests
from typing import Any, Dict, List, Optional, Union

# Third party imports
from celery import shared_task

# Django imports
from django.conf import settings
from django.db.models import Prefetch
from django.core.serializers.json import DjangoJSONEncoder
from django.template.loader import render_to_string
from django.core.exceptions import ObjectDoesNotExist

# Module imports
from plane.api.serializers import (
    CycleIssueSerializer,
    CycleSerializer,
    IssueCommentSerializer,
    IssueExpandSerializer,
    ModuleIssueSerializer,
    ModuleSerializer,
    ProjectSerializer,
    UserLiteSerializer,
    IntakeIssueSerializer,
)
from plane.db.models import (
    Cycle,
    CycleIssue,
    Issue,
    IssueActivity,
    IssueComment,
    Module,
    ModuleIssue,
    Project,
    User,
    Webhook,
    WebhookLog,
    IntakeIssue,
    IssueLabel,
    IssueAssignee,
)
from plane.bgtasks.email_task import deliver_email_message
from plane.license.utils.instance_value import is_smtp_enabled
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception
from plane.utils.url_security import pinned_fetch


SERIALIZER_MAPPER = {
    "project": ProjectSerializer,
    "issue": IssueExpandSerializer,
    "cycle": CycleSerializer,
    "module": ModuleSerializer,
    "cycle_issue": CycleIssueSerializer,
    "module_issue": ModuleIssueSerializer,
    "issue_comment": IssueCommentSerializer,
    "user": UserLiteSerializer,
    "intake_issue": IntakeIssueSerializer,
}

MODEL_MAPPER = {
    "project": Project,
    "issue": Issue,
    "cycle": Cycle,
    "module": Module,
    "cycle_issue": CycleIssue,
    "module_issue": ModuleIssue,
    "issue_comment": IssueComment,
    "user": User,
    "intake_issue": IntakeIssue,
}


logger = logging.getLogger("plane.worker")


def get_issue_prefetches():
    return [
        Prefetch("label_issue", queryset=IssueLabel.objects.select_related("label")),
        Prefetch("issue_assignee", queryset=IssueAssignee.objects.select_related("assignee")),
    ]


def _context_from_transition_activity(activity) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    if activity is None:
        return context
    context["from_state_id"] = str(activity.old_value) if activity.old_value else None
    try:
        extra = json.loads(activity.comment or "{}")
    except (TypeError, ValueError):
        extra = {}
    if isinstance(extra, dict):
        for key in ("workflow_id", "transition_id"):
            if extra.get(key):
                context[key] = str(extra[key])
    return context


def _transition_context(issue_id: Union[str, uuid.UUID]) -> Dict[str, Any]:
    """Read the durable transition activity written by the workflow service."""
    activity = (
        IssueActivity.objects.filter(issue_id=issue_id, field="state", verb="transition")
        .order_by("-created_at")
        .first()
    )
    return _context_from_transition_activity(activity)


def _transition_contexts(issue_ids: List[Union[str, uuid.UUID]]) -> Dict[str, Dict[str, Any]]:
    """Batch the transition lookup so webhook fan-out stays at one query per event."""
    if not issue_ids:
        return {}
    contexts: Dict[str, Dict[str, Any]] = {}
    activities = (
        IssueActivity.objects.filter(issue_id__in=issue_ids, field="state", verb="transition")
        .order_by("issue_id", "-created_at")
    )
    for activity in activities:
        key = str(activity.issue_id)
        if key not in contexts:
            contexts[key] = _context_from_transition_activity(activity)
    return contexts


def _issue_event_fields(issue: Issue, transition_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """PLN-004/005/007 additive fields for issue webhook payloads."""
    if issue is None:
        return {}
    issue_type = issue.type if issue.type_id else None
    fields: Dict[str, Any] = {
        "type_id": str(issue.type_id) if issue.type_id else None,
        "type_key": issue_type.key if issue_type else None,
        "type_name": issue_type.name if issue_type else None,
        # Nested projection mirrors IssueTypeLiteSerializer. The flat fields above
        # are kept for existing webhook consumers.
        "type": {
            "id": str(issue_type.id),
            "key": issue_type.key,
            "name": issue_type.name,
            "logo_props": issue_type.logo_props,
            "is_epic": issue_type.is_epic,
        }
        if issue_type
        else None,
        "state_id": str(issue.state_id) if issue.state_id else None,
        "state_name": issue.state.name if issue.state_id and issue.state else None,
    }
    if transition_context is None:
        transition_context = _transition_context(issue.id)
    fields.update(transition_context)
    return fields


def save_webhook_log(
    webhook: Webhook,
    request_method: str,
    request_headers: str,
    request_body: str,
    response_status: str,
    response_headers: str,
    response_body: str,
    retry_count: int,
    event_type: str,
) -> None:
    log_data = {
        "workspace_id": str(webhook.workspace_id),
        "webhook": str(webhook.id),
        "event_type": str(event_type),
        "request_method": str(request_method),
        "request_headers": str(request_headers),
        "request_body": str(request_body),
        "response_status": str(response_status),
        "response_headers": str(response_headers),
        "response_body": str(response_body),
        "retry_count": retry_count,
    }

    try:
        WebhookLog.objects.create(**log_data)
        logger.info("Webhook log saved successfully to database")
    except Exception as e:
        log_exception(e, warning=True)
        logger.error(f"Failed to save webhook log: {e}")


def get_model_data(event: str, event_id: Union[str, List[str]], many: bool = False) -> Dict[str, Any]:
    """
    Retrieve and serialize model data based on the event type.

    Args:
        event (str): The type of event/model to retrieve data for
        event_id (Union[str, List[str]]): The ID or list of IDs of the model instance(s)
        many (bool): Whether to retrieve multiple instances

    Returns:
        Dict[str, Any]: Serialized model data

    Raises:
        ValueError: If serializer is not found for the event
        ObjectDoesNotExist: If model instance is not found
    """
    model = MODEL_MAPPER.get(event)
    if model is None:
        raise ValueError(f"Model not found for event: {event}")

    try:
        serializer = SERIALIZER_MAPPER.get(event)
        if serializer is None:
            raise ValueError(f"Serializer not found for event: {event}")

        if event == "issue":
            issue_prefetches = get_issue_prefetches()
            if many:
                issues = list(
                    model.objects.filter(pk__in=event_id)
                    .select_related("state", "type")
                    .prefetch_related(*issue_prefetches)
                )
                issues_by_id = {str(issue.id): issue for issue in issues}
                transition_contexts = _transition_contexts([issue.id for issue in issues])
                data = serializer(issues, many=True, context={"expand": ["labels", "assignees"]}).data
                rows = []
                for row in data:
                    item = dict(row)
                    issue_id_str = str(item.get("id"))
                    item.update(
                        _issue_event_fields(issues_by_id.get(issue_id_str), transition_contexts.get(issue_id_str, {}))
                    )
                    rows.append(item)
                return rows

            issue = (
                model.objects.filter(pk=event_id)
                .select_related("state", "type")
                .prefetch_related(*issue_prefetches)
                .first()
            )
            if issue is None:
                raise ObjectDoesNotExist(f"No {event} found with id: {event_id}")
            data = dict(serializer(issue, context={"expand": ["labels", "assignees"]}).data)
            data.update(_issue_event_fields(issue))
            return data

        queryset = model.objects.get(pk=event_id) if not many else model.objects.filter(pk__in=event_id)
        return serializer(queryset, many=many).data
    except ObjectDoesNotExist:
        raise ObjectDoesNotExist(f"No {event} found with id: {event_id}")


@shared_task
def send_webhook_deactivation_email(webhook_id: str, receiver_id: str, current_site: str, reason: str) -> None:
    """
    Send an email notification when a webhook is deactivated.

    Args:
        webhook_id (str): ID of the deactivated webhook
        receiver_id (str): ID of the user to receive the notification
        current_site (str): Current site URL
        reason (str): Reason for webhook deactivation
    """
    try:
        if not is_smtp_enabled():
            return

        receiver = User.objects.get(pk=receiver_id)
        webhook = Webhook.objects.get(pk=webhook_id)

        # Get the webhook payload
        subject = "Webhook Deactivated"
        message = f"Webhook {webhook.url} has been deactivated due to failed requests."

        # Send the mail
        context = {
            "email": receiver.email,
            "message": message,
            "webhook_url": f"{current_site}/{str(webhook.workspace.slug)}/settings/webhooks/{str(webhook.id)}",
        }
        html_content = render_to_string("emails/notifications/webhook-deactivate.html", context)
        text_content = generate_plain_text_from_html(html_content)

        if deliver_email_message(
            subject=subject,
            body=text_content,
            recipients=[receiver.email],
            html_body=html_content,
        ):
            logger.info("Email sent successfully.")
    except Exception as e:
        log_exception(e, warning=True)
        logger.error(f"Failed to send email: {e}")


@shared_task(
    bind=True,
    autoretry_for=(requests.RequestException,),
    retry_backoff=600,
    max_retries=5,
    retry_jitter=True,
)
def webhook_send_task(
    self,
    webhook_id: str,
    slug: str,
    event: str,
    event_data: Optional[Dict[str, Any]],
    action: str,
    current_site: str,
    activity: Optional[Dict[str, Any]],
) -> None:
    """
    Send webhook notifications to configured endpoints.

    Args:
        webhook (str): Webhook ID
        slug (str): Workspace slug
        event (str): Event type
        event_data (Optional[Dict[str, Any]]): Event data to be sent
        action (str): HTTP method/action
        current_site (str): Current site URL
        activity (Optional[Dict[str, Any]]): Activity data
    """
    try:
        webhook = Webhook.objects.get(id=webhook_id, workspace__slug=slug)

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Autopilot",
            "X-Plane-Delivery": str(uuid.uuid4()),
            "X-Plane-Event": event,
        }

        # # Your secret key
        event_data = json.loads(json.dumps(event_data, cls=DjangoJSONEncoder)) if event_data is not None else None

        activity = json.loads(json.dumps(activity, cls=DjangoJSONEncoder)) if activity is not None else None

        action = {
            "POST": "create",
            "PATCH": "update",
            "PUT": "update",
            "DELETE": "delete",
        }.get(action, action)

        payload = {
            "event": event,
            "action": action,
            "webhook_id": str(webhook.id),
            "workspace_id": str(webhook.workspace_id),
            "workspace_slug": slug,
            "data": event_data,
            "activity": activity,
        }

        # Use HMAC for generating signature
        if webhook.secret_key:
            hmac_signature = hmac.new(
                webhook.secret_key.encode("utf-8"),
                json.dumps(payload).encode("utf-8"),
                hashlib.sha256,
            )
            signature = hmac_signature.hexdigest()
            headers["X-Plane-Signature"] = signature
    except Exception as e:
        log_exception(e)
        logger.error(f"Failed to send webhook: {e}")
        return

    try:
        # Resolve + validate the webhook URL and pin the connection to the
        # validated IP. Pinning closes the DNS-rebinding TOCTOU (validating the
        # name then letting requests re-resolve it lets an attacker swap in an
        # internal IP between the two lookups). Redirects are never followed, so
        # a 3xx Location cannot bounce the request to an internal address
        # (GHSA-mq87-52pf-hm3h / cluster C).
        response = pinned_fetch(
            "POST",
            webhook.url,
            allowed_ips=settings.WEBHOOK_ALLOWED_IPS,
            allowed_hosts=settings.WEBHOOK_ALLOWED_HOSTS,
            headers=headers,
            json=payload,
            timeout=30,
        )

        # Log the webhook request
        save_webhook_log(
            webhook=webhook,
            request_method=action,
            request_headers=headers,
            request_body=payload,
            response_status=response.status_code,
            response_headers=response.headers,
            response_body=response.text,
            retry_count=self.request.retries,
            event_type=event,
        )
        logger.info(f"Webhook {webhook.id} sent successfully")
    except requests.RequestException as e:
        # Log the failed webhook request
        save_webhook_log(
            webhook=webhook,
            request_method=action,
            request_headers=headers,
            request_body=payload,
            response_status=500,
            response_headers="",
            response_body=str(e),
            retry_count=self.request.retries,
            event_type=event,
        )
        logger.error(f"Webhook {webhook.id} failed with error: {e}")
        # Retry logic
        if self.request.retries >= self.max_retries:
            Webhook.objects.filter(pk=webhook.id).update(is_active=False)
            if webhook:
                # send email for the deactivation of the webhook
                send_webhook_deactivation_email.delay(
                    webhook_id=webhook.id,
                    receiver_id=webhook.created_by_id,
                    reason=str(e),
                    current_site=current_site,
                )
            return
        raise requests.RequestException()

    except ValueError as e:
        # SSRF validation failure (blocked/internal target or unresolvable host).
        # Not retryable — record it so the failure is visible to the admin, but
        # do not raise (no Celery retry) and do not auto-deactivate (the cause
        # may be transient DNS).
        save_webhook_log(
            webhook=webhook,
            request_method=action,
            request_headers=headers,
            request_body=payload,
            response_status=400,
            response_headers="",
            response_body=f"Webhook URL rejected: {e}",
            retry_count=self.request.retries,
            event_type=event,
        )
        logger.warning(f"Webhook {webhook.id} URL rejected: {e}")
        return

    except Exception as e:
        log_exception(e)
        return


@shared_task
def webhook_activity(
    event: str,
    verb: str,
    field: Optional[str],
    old_value: Any,
    new_value: Any,
    actor_id: str | uuid.UUID,
    slug: str,
    current_site: str,
    event_id: str | uuid.UUID,
    old_identifier: Optional[str],
    new_identifier: Optional[str],
) -> None:
    """
    Process and send webhook notifications for various activities in the system.

    This task filters relevant webhooks based on the event type and sends notifications
    to all active webhooks for the workspace.

    Args:
        event (str): Type of event (project, issue, module, cycle, issue_comment)
        verb (str): Action performed (created, updated, deleted)
        field (Optional[str]): Name of the field that was changed
        old_value (Any): Previous value of the field
        new_value (Any): New value of the field
        actor_id (str | uuid.UUID): ID of the user who performed the action
        slug (str): Workspace slug
        current_site (str): Current site URL
        event_id (str | uuid.UUID): ID of the event object
        old_identifier (Optional[str]): Previous identifier if any
        new_identifier (Optional[str]): New identifier if any

    Returns:
        None

    Note:
        The function silently returns on ObjectDoesNotExist exceptions to handle
        race conditions where objects might have been deleted.
    """
    try:
        webhooks = Webhook.objects.filter(workspace__slug=slug, is_active=True)

        if event == "project":
            webhooks = webhooks.filter(project=True)

        if event == "issue":
            webhooks = webhooks.filter(issue=True)

        if event == "module" or event == "module_issue":
            webhooks = webhooks.filter(module=True)

        if event == "cycle" or event == "cycle_issue":
            webhooks = webhooks.filter(cycle=True)

        if event == "issue_comment":
            webhooks = webhooks.filter(issue_comment=True)

        for webhook in webhooks:
            webhook_send_task.delay(
                webhook_id=webhook.id,
                slug=slug,
                event=event,
                event_data=({"id": event_id} if verb == "deleted" else get_model_data(event=event, event_id=event_id)),
                action=verb,
                current_site=current_site,
                activity={
                    "field": field,
                    "new_value": new_value,
                    "old_value": old_value,
                    "actor": get_model_data(event="user", event_id=actor_id),
                    "old_identifier": old_identifier,
                    "new_identifier": new_identifier,
                },
            )
        return
    except Exception as e:
        # Return if a does not exist error occurs
        if isinstance(e, ObjectDoesNotExist):
            return
        if settings.DEBUG:
            print(e)
        log_exception(e)
        return


@shared_task
def model_activity(model_name, model_id, requested_data, current_instance, actor_id, slug, origin=None):
    """Function takes in two json and computes differences between keys of both the json"""
    if current_instance is None:
        webhook_activity.delay(
            event=model_name,
            verb="created",
            field=None,
            old_value=None,
            new_value=None,
            actor_id=actor_id,
            slug=slug,
            current_site=origin,
            event_id=model_id,
            old_identifier=None,
            new_identifier=None,
        )
        return

    # Load the current instance
    current_instance = json.loads(current_instance) if current_instance is not None else None

    # Loop through all keys in requested data and check the current value and requested value
    for key in requested_data:
        # Check if key is present in current instance or not
        if key in current_instance:
            current_value = current_instance.get(key, None)
            requested_value = requested_data.get(key, None)
            if current_value != requested_value:
                webhook_activity.delay(
                    event=model_name,
                    verb="updated",
                    field=key,
                    old_value=current_value,
                    new_value=requested_value,
                    actor_id=actor_id,
                    slug=slug,
                    current_site=origin,
                    event_id=model_id,
                    old_identifier=None,
                    new_identifier=None,
                )

    return
