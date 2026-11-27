# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Daily due-date reminder emails for open work items."""

# Python imports
from datetime import timedelta

# Django imports
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

# Third party imports
from celery import shared_task

# Module imports
from plane.bgtasks.email_task import deliver_email_message, max_delivery_attempts
from plane.db.models import EmailNotificationLog, Issue, IssueAssignee, IssueSubscriber
from plane.license.utils.instance_value import is_smtp_enabled
from plane.utils.email import generate_plain_text_from_html, truncate_email_subject
from plane.utils.exception_logger import log_exception
from plane.utils.smtp import is_email_suppressed
from plane.utils.unsubscribe import email_preference_allows

COMPLETED_STATE_GROUPS = ("completed", "cancelled")
DUE_SOON_DAYS = 3
OVERDUE_DAYS = 7
REMINDER_LABELS = {"overdue": "Overdue", "due_today": "Due today", "due_soon": "Due soon"}
REMINDER_PHRASES = {"overdue": "overdue", "due_today": "due today", "due_soon": "due soon"}


def _reminder_kind(target_date, today):
    if target_date < today:
        return "overdue"
    if target_date == today:
        return "due_today"
    return "due_soon"


def _render_reminder(context):
    html_content = render_to_string("emails/notifications/due_date_reminder.html", context)
    return html_content, generate_plain_text_from_html(html_content)


def _reminder_subject(context):
    kind = context.get("reminder_kind", "due_today")
    return truncate_email_subject(
        f"{REMINDER_LABELS.get(kind, 'Due today')}: {context.get('issue_name', 'Work item')} on Plane"
    )


def _deliver_reminder(log):
    """Render one persisted reminder log and deliver it through the shared path."""

    context = log.data or {}
    html_content, text_content = _render_reminder(context)
    return deliver_email_message(
        subject=_reminder_subject(context),
        body=text_content,
        recipients=[log.receiver.email],
        html_body=html_content,
        log_ids=[log.pk],
    )


def _retry_failed_reminders():
    now = timezone.now()
    candidates = EmailNotificationLog.objects.filter(
        entity_name="due_date_reminder",
        sent_at__isnull=True,
        attempts__lt=max_delivery_attempts(),
    ).filter(next_retry_at__isnull=False, next_retry_at__lte=now)

    retried = 0
    for log in candidates.select_related("receiver"):
        if is_email_suppressed(log.receiver.email):
            continue
        # Reserve the log before delivery so a second beat run cannot enqueue it twice.
        EmailNotificationLog.objects.filter(pk=log.pk).update(next_retry_at=now + timedelta(minutes=10))
        retried += int(_deliver_reminder(log))
    return retried


def _due_window(today):
    """Work items that are overdue, due today or due soon."""

    return (
        Issue.objects.filter(
            target_date__range=(
                today - timedelta(days=OVERDUE_DAYS),
                today + timedelta(days=DUE_SOON_DAYS),
            )
        )
        .exclude(state__group__in=COMPLETED_STATE_GROUPS)
        .select_related("project", "project__workspace", "created_by")
    )


def _issue_recipients(issue):
    recipients = {}
    for assignee in IssueAssignee.objects.filter(issue=issue).select_related("assignee"):
        recipients[assignee.assignee_id] = assignee.assignee
    for subscriber in IssueSubscriber.objects.filter(issue=issue).select_related("subscriber"):
        recipients.setdefault(subscriber.subscriber_id, subscriber.subscriber)
    return recipients


@shared_task
def send_due_date_reminders():
    """Email assignees/subscribers for overdue, due-today and due-soon work items.

    Disabled or unconfigured SMTP makes this a no-op; it never raises into the
    beat worker. Recipients are deduplicated and one reminder per issue per day
    is recorded in ``EmailNotificationLog``.
    """

    if not is_smtp_enabled():
        return 0

    try:
        sent = _retry_failed_reminders()
        today = timezone.localdate()
        base_url = str(settings.WEB_URL or "http://localhost").rstrip("/")

        for issue in _due_window(today).iterator():
            kind = _reminder_kind(issue.target_date, today)
            for user in _issue_recipients(issue).values():
                if not user or not getattr(user, "email", "") or not getattr(user, "is_active", True):
                    continue
                if is_email_suppressed(user.email):
                    continue
                if not email_preference_allows(
                    user, "issue_updates", workspace=issue.project.workspace, project=issue.project
                ):
                    continue

                already_sent = EmailNotificationLog.objects.filter(
                    entity_name="due_date_reminder",
                    entity_identifier=issue.id,
                    receiver=user,
                    created_at__date=today,
                ).exists()
                if already_sent:
                    continue

                workspace = issue.project.workspace
                context = {
                    "issue_name": issue.name,
                    "project_name": issue.project.name,
                    "workspace_name": workspace.name,
                    "workspace_url": base_url,
                    "issue_url": f"{base_url}/{workspace.slug}/{issue.project_id}/issues/{issue.id}",
                    "target_date": str(issue.target_date),
                    "reminder_kind": kind,
                    "reminder_label": REMINDER_LABELS[kind],
                    "reminder_phrase": REMINDER_PHRASES[kind],
                }
                html_content, text_content = _render_reminder(context)
                log = EmailNotificationLog.objects.create(
                    receiver=user,
                    triggered_by=issue.created_by or user,
                    entity_identifier=issue.id,
                    entity_name="due_date_reminder",
                    entity="issue",
                    data=context,
                )
                sent += int(
                    deliver_email_message(
                        subject=_reminder_subject(context),
                        body=text_content,
                        recipients=[user.email],
                        html_body=html_content,
                        log_ids=[log.pk],
                    )
                )

        return sent
    except Exception as error:  # pragma: no cover - defensive guard for beat workers
        log_exception(error)
        return 0


@shared_task
def send_daily_digest():
    """Send one summary per recipient of their overdue/upcoming work items."""

    if not is_smtp_enabled():
        return 0

    try:
        today = timezone.localdate()
        base_url = str(settings.WEB_URL or "http://localhost").rstrip("/")
        users = {}
        items_by_user = {}
        for issue in _due_window(today).iterator():
            workspace = issue.project.workspace
            item = {
                "name": issue.name,
                "identifier": f"{issue.project.identifier}-{issue.sequence_id}",
                "url": f"{base_url}/{workspace.slug}/{issue.project_id}/issues/{issue.id}",
                "target_date": str(issue.target_date),
                "kind": REMINDER_LABELS[_reminder_kind(issue.target_date, today)],
            }
            for user in _issue_recipients(issue).values():
                if not user or not getattr(user, "email", "") or not getattr(user, "is_active", True):
                    continue
                users.setdefault(user.pk, user)
                items_by_user.setdefault(user.pk, []).append(item)

        sent = 0
        for user_key, user in users.items():
            items = items_by_user.get(user_key, [])
            if not items or is_email_suppressed(user.email):
                continue
            if not email_preference_allows(user, "issue_updates"):
                continue
            if EmailNotificationLog.objects.filter(
                entity_name="daily_digest",
                receiver=user,
                created_at__date=today,
            ).exists():
                continue

            context = {
                "issues": items[:20],
                "issue_count": len(items),
                "recipient_email": user.email,
                "workspace_url": base_url,
            }
            html_content = render_to_string("emails/notifications/daily_digest.html", context)
            text_content = generate_plain_text_from_html(html_content)
            log = EmailNotificationLog.objects.create(
                receiver=user,
                triggered_by=user,
                entity_identifier=user.pk,
                entity_name="daily_digest",
                entity="digest",
                data={"issue_count": len(items)},
            )
            sent += int(
                deliver_email_message(
                    subject=truncate_email_subject("Your daily Plane digest"),
                    body=text_content,
                    recipients=[user.email],
                    html_body=html_content,
                    log_ids=[log.pk],
                )
            )
        return sent
    except Exception as error:  # pragma: no cover - defensive guard for beat workers
        log_exception(error)
        return 0
