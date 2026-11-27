# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.core import mail
from django.template.loader import render_to_string
from django.test import override_settings

from plane.utils.email import generate_plain_text_from_html, truncate_email_subject
from plane.utils.smtp import send_email_message


def smtp_config():
    return {
        "ENABLE_SMTP": "1",
        "EMAIL_HOST": "mailpit",
        "EMAIL_PORT": "1025",
        "EMAIL_HOST_USER": "",
        "EMAIL_HOST_PASSWORD": "",
        "EMAIL_USE_TLS": "0",
        "EMAIL_USE_SSL": "0",
        "EMAIL_FROM": "notifications@example.invalid",
        "EMAIL_TIMEOUT": "10",
    }


@pytest.mark.unit
class TestSubjectTruncation:
    def test_long_title_is_truncated_by_bytes_without_splitting_a_code_point(self):
        title = "Štúdia 😀 " + ("Very long work item title " * 20)
        subject = truncate_email_subject(title, max_bytes=60)

        assert len(subject.encode("utf-8")) <= 60
        assert subject.endswith("…")
        subject.encode("utf-8").decode("utf-8")
        assert "😀" in subject

    def test_subject_newlines_are_flattened(self):
        assert truncate_email_subject("Hello\nworld\r\nagain\t!") == "Hello world again !"


@pytest.mark.unit
@pytest.mark.django_db
class TestEmailTemplateDelivery:
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_TEST_MODE=False)
    def test_issue_update_render_has_plain_text_alternative_and_unsubscribe_link(self):
        mail.outbox.clear()
        unsubscribe_url = "https://plane.example.invalid/api/public/unsubscribe/signed-token/"
        context = {
            "entity_type": "issue",
            "entity_name": "PLN-1",
            "issue": {
                "name": "Znamená 😀 správu" + (" dlhý názov" * 20),
                "issue_identifier": "PLN-1",
                "issue_url": "https://plane.example.invalid/test-ws/projects/1/issues/2",
            },
            "project": "Delivery",
            "project_url": "https://plane.example.invalid/test-ws/projects/1/issues/",
            "workspace": "test-ws",
            "receiver": {"email": "recipient@example.invalid"},
            "actors_involved": 1,
            "summary": "Updates were made to the issue by",
            "data": [
                {
                    "actor_detail": {"first_name": "Jana", "last_name": "Nováková"},
                    "changes": {},
                    "activity_time": "today",
                }
            ],
            "comments": [],
            "user_preference": "https://plane.example.invalid/settings/account/notifications/",
            "unsubscribe_url": unsubscribe_url,
        }
        html_content = render_to_string("emails/notifications/issue-updates.html", context)
        text_content = generate_plain_text_from_html(html_content)

        assert "Znamená 😀 správu" in html_content
        assert unsubscribe_url in html_content
        assert "Znamená 😀 správu" in text_content

        send_email_message(
            subject=truncate_email_subject("PLN-1 Znamená 😀 správu" + (" dlhý názov" * 20)),
            body=text_content,
            recipients=["recipient@example.invalid"],
            html_body=html_content,
            configuration=smtp_config(),
        )

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == ["recipient@example.invalid"]
        assert len(message.subject.encode("utf-8")) <= 150
        assert message.body == text_content
        assert message.alternatives[0] == (html_content, "text/html")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_TEST_MODE=False)
    def test_daily_digest_renders_one_summary(self):
        html_content = render_to_string(
            "emails/notifications/daily_digest.html",
            {
                "issue_count": 2,
                "issues": [
                    {
                        "identifier": "PLN-1",
                        "name": "Overdue task",
                        "kind": "Overdue",
                        "target_date": "2026-11-26",
                        "url": "https://plane.example.invalid/test-ws/projects/1/issues/2",
                    },
                    {
                        "identifier": "PLN-2",
                        "name": "Due soon task",
                        "kind": "Due soon",
                        "target_date": "2026-11-29",
                        "url": "https://plane.example.invalid/test-ws/projects/1/issues/3",
                    },
                ],
                "workspace_url": "https://plane.example.invalid",
            },
        )
        text_content = generate_plain_text_from_html(html_content)

        assert "Overdue task" in html_content
        assert "Due soon task" in text_content
