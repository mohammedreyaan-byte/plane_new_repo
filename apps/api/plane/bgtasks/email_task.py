# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Async SMTP delivery and bounded retry helpers.

All application email should go through ``deliver_email_message`` so a disabled or
misconfigured SMTP server never raises into a request or a worker.
"""

# Python imports
from datetime import timedelta

# Third party imports
from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

# Module imports
from plane.db.models import EmailNotificationLog
from plane.license.utils.instance_value import is_smtp_enabled
from plane.utils.smtp import SMTPConfigurationError, is_email_suppressed, send_email_message


def max_delivery_attempts():
    """Return the configured retry ceiling, always at least one attempt."""

    try:
        value = int(getattr(settings, "EMAIL_DELIVERY_MAX_ATTEMPTS", 3))
    except (TypeError, ValueError):
        return 3
    return max(1, min(value, 10))


def retry_delay_for_attempt(attempt):
    """Exponential backoff with a fixed upper bound."""

    try:
        base = int(getattr(settings, "EMAIL_RETRY_BACKOFF_SECONDS", 300))
    except (TypeError, ValueError):
        base = 300
    base = max(1, min(base, 3600))
    return min(base * (2 ** max(attempt - 1, 0)), 3600)


def mark_delivery_failure(log_ids, message, terminal=False):
    """Record a failed delivery and schedule a bounded retry where appropriate."""

    log_ids = [log_id for log_id in (log_ids or []) if log_id]
    if not log_ids:
        return

    now = timezone.now()
    error_message = (message or "Could not send email")[:1000]
    ceiling = max_delivery_attempts()
    for log in EmailNotificationLog.objects.filter(pk__in=log_ids):
        attempts = log.attempts + 1
        values = {
            "attempts": attempts,
            "last_error": error_message,
            "next_retry_at": None if terminal or attempts >= ceiling else now + timedelta(seconds=retry_delay_for_attempt(attempts)),  # noqa: E501
        }
        EmailNotificationLog.objects.filter(pk=log.pk).update(**values)


def mark_delivery_success(log_ids):
    if not log_ids:
        return
    EmailNotificationLog.objects.filter(pk__in=log_ids).update(
        sent_at=timezone.now(),
        last_error="",
        next_retry_at=None,
    )


def deliver_email_message(subject, body, recipients, html_body=None, log_ids=None):
    """Deliver one message through the shared SMTP helper.

    Returns True when the server accepted the message and False for every
    configuration, suppression or delivery failure. Failures are recorded on the
    existing ``EmailNotificationLog`` rows via the retry fields.
    """

    if not is_smtp_enabled():
        return False

    try:
        send_email_message(
            subject=subject,
            body=body,
            recipients=recipients,
            html_body=html_body,
        )
    except SMTPConfigurationError as error:
        message = str(error)
        terminal = "suppressed" in message.lower()
        mark_delivery_failure(log_ids, message, terminal=terminal)
        return False
    except Exception as error:  # pragma: no cover - defensive guard for workers
        mark_delivery_failure(log_ids, f"Unexpected email delivery error: {type(error).__name__}")
        return False

    mark_delivery_success(log_ids)
    return True


@shared_task
def send_email(subject, body, recipients, html_body=None, log_ids=None):
    """Celery entry point for a single templated transactional email."""

    return deliver_email_message(
        subject=subject,
        body=body,
        recipients=recipients,
        html_body=html_body,
        log_ids=log_ids,
    )


@shared_task
def retry_failed_email_notifications():
    """Re-queue notification logs that failed but still have retries left.

    This is invoked by the already-scheduled ``stack_email_notification`` beat
    task, so no new beat registry entry is required.
    """

    if not is_smtp_enabled():
        return 0

    now = timezone.now()
    candidates = EmailNotificationLog.objects.filter(
        sent_at__isnull=True,
        processed_at__isnull=False,
        attempts__lt=max_delivery_attempts(),
    ).filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))

    queued = 0
    for log in candidates.select_related("receiver"):
        if not log.entity_identifier or not log.data:
            continue

        receiver_email = getattr(log.receiver, "email", "")
        if is_email_suppressed(receiver_email):
            mark_delivery_failure([log.pk], "Recipient address is suppressed", terminal=True)
            continue

        # Reserve the log until the worker picks it up so successive beat runs
        # do not enqueue the same failure repeatedly.
        EmailNotificationLog.objects.filter(pk=log.pk).update(next_retry_at=now + timedelta(minutes=10))

        # Imported lazily to avoid a module-level cycle with the notification task.
        from plane.bgtasks.email_notification_task import send_email_notification

        activity = log.data.get("issue_activity") or {}
        triggered_by = str(activity.get("actor") or log.triggered_by_id)
        send_email_notification.delay(
            issue_id=log.entity_identifier,
            notification_data={triggered_by: [log.data]},
            receiver_id=str(log.receiver_id),
            email_notification_ids=[str(log.pk)],
        )
        queued += 1

    return queued
