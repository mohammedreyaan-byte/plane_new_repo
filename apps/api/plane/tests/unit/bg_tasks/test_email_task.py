# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from plane.bgtasks.due_date_reminder_task import send_due_date_reminders
from plane.bgtasks.email_notification_task import stack_email_notification
from plane.bgtasks.email_task import deliver_email_message, retry_failed_email_notifications
from plane.bgtasks.workspace_invitation_response_task import workspace_invitation_response
from plane.db.models import EmailNotificationLog, User
from plane.utils.smtp import SMTPConfigurationError


def create_log(attempts=0, next_retry_at=None, processed_at=None):
    suffix = uuid4().hex
    sender = User.objects.create(username=f"sender-{suffix}", email=f"sender-{suffix}@example.invalid")
    receiver = User.objects.create(username=f"receiver-{suffix}", email=f"receiver-{suffix}@example.invalid")
    return EmailNotificationLog.objects.create(
        receiver=receiver,
        triggered_by=sender,
        entity_identifier=uuid4(),
        entity_name="issue",
        entity="issue",
        data={"issue_activity": {"actor": str(sender.id)}},
        processed_at=processed_at,
        attempts=attempts,
        next_retry_at=next_retry_at,
    )


@pytest.mark.unit
@pytest.mark.django_db
class TestSMTPBackgroundDelivery:
    def test_disabled_smtp_makes_no_delivery_attempt(self, mocker):
        mocker.patch("plane.bgtasks.email_task.is_smtp_enabled", return_value=False)
        send = mocker.patch("plane.bgtasks.email_task.send_email_message")

        assert deliver_email_message("Subject", "Body", ["recipient@example.invalid"]) is False
        send.assert_not_called()

    def test_disabled_smtp_skips_notification_stack(self, mocker):
        mocker.patch("plane.bgtasks.email_notification_task.is_smtp_enabled", return_value=False)
        retry = mocker.patch("plane.bgtasks.email_notification_task.retry_failed_email_notifications")
        delay = mocker.patch("plane.bgtasks.email_notification_task.send_email_notification.delay")

        stack_email_notification()

        retry.assert_not_called()
        delay.assert_not_called()

    def test_failure_records_attempt_and_schedules_retry(self, mocker):
        log = create_log()
        mocker.patch("plane.bgtasks.email_task.is_smtp_enabled", return_value=True)
        mocker.patch(
            "plane.bgtasks.email_task.send_email_message",
            side_effect=SMTPConfigurationError("Relay unavailable"),
        )

        assert deliver_email_message("Subject", "Body", ["recipient@example.invalid"], log_ids=[log.pk]) is False

        log.refresh_from_db()
        assert log.sent_at is None
        assert log.attempts == 1
        assert log.last_error == "Relay unavailable"
        assert log.next_retry_at is not None

    @override_settings(EMAIL_DELIVERY_MAX_ATTEMPTS=2)
    def test_final_failure_clears_next_retry(self, mocker):
        log = create_log(attempts=1)
        mocker.patch("plane.bgtasks.email_task.is_smtp_enabled", return_value=True)
        mocker.patch(
            "plane.bgtasks.email_task.send_email_message",
            side_effect=SMTPConfigurationError("Relay unavailable"),
        )

        deliver_email_message("Subject", "Body", ["recipient@example.invalid"], log_ids=[log.pk])

        log.refresh_from_db()
        assert log.attempts == 2
        assert log.next_retry_at is None

    @override_settings(EMAIL_DELIVERY_MAX_ATTEMPTS=3)
    def test_retry_queues_only_due_logs(self, mocker):
        due = create_log(attempts=1, next_retry_at=timezone.now() - timedelta(minutes=1), processed_at=timezone.now())
        later = create_log(attempts=1, next_retry_at=timezone.now() + timedelta(minutes=10), processed_at=timezone.now())
        task = mocker.patch("plane.bgtasks.email_notification_task.send_email_notification")

        mocker.patch("plane.bgtasks.email_task.is_smtp_enabled", return_value=True)

        assert retry_failed_email_notifications() == 1
        assert task.delay.call_count == 1
        kwargs = task.delay.call_args.kwargs
        assert str(due.pk) in kwargs["email_notification_ids"]

        due.refresh_from_db()
        later.refresh_from_db()
        assert due.next_retry_at > timezone.now()
        assert later.next_retry_at < timezone.now() + timedelta(minutes=10)


@pytest.mark.unit
class TestAdditionalSmtpNotificationPaths:
    def test_invitation_response_is_a_noop_when_smtp_is_disabled(self, mocker):
        mocker.patch("plane.bgtasks.workspace_invitation_response_task.is_smtp_enabled", return_value=False)
        send = mocker.patch("plane.bgtasks.workspace_invitation_response_task.deliver_email_message")

        workspace_invitation_response(
            "inviter@example.invalid",
            "invitee@example.invalid",
            "Example Workspace",
            "example-workspace",
            True,
            "http://localhost",
        )

        send.assert_not_called()

    def test_invitation_response_notifies_the_inviter(self, mocker):
        mocker.patch("plane.bgtasks.workspace_invitation_response_task.is_smtp_enabled", return_value=True)
        send = mocker.patch("plane.bgtasks.workspace_invitation_response_task.deliver_email_message")

        workspace_invitation_response(
            "inviter@example.invalid",
            "invitee@example.invalid",
            "Example Workspace",
            "example-workspace",
            False,
            "http://localhost",
        )

        assert send.call_count == 1
        kwargs = send.call_args.kwargs
        assert kwargs["recipients"] == ["inviter@example.invalid"]
        assert "declined your invitation" in kwargs["subject"]

    def test_due_date_reminders_do_not_query_when_smtp_is_disabled(self, mocker):
        mocker.patch("plane.bgtasks.due_date_reminder_task.is_smtp_enabled", return_value=False)
        issue_query = mocker.patch("plane.bgtasks.due_date_reminder_task.Issue.objects.filter")

        assert send_due_date_reminders() == 0
        issue_query.assert_not_called()

    def test_management_command_does_not_send_when_smtp_is_disabled(self, mocker):
        mocker.patch("plane.db.management.commands.test_email.is_smtp_enabled", return_value=False)
        send = mocker.patch("plane.db.management.commands.test_email.send_email_message")

        call_command("test_email", "recipient@example.invalid")

        send.assert_not_called()
