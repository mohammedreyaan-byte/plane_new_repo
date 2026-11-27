# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Manual Mailpit delivery validation.

Run only with RUN_MAILPIT_INTEGRATION=1 and the Mailpit compose override from
docs/email-delivery.md. Nothing here contacts a production relay.
"""

import os

import pytest
import requests

from plane.utils.smtp import send_email_message


MAILPIT_API_URL = os.environ.get("MAILPIT_API_URL", "http://mailpit:8025").rstrip("/")
MAILPIT_SMTP_HOST = os.environ.get("MAILPIT_SMTP_HOST", "mailpit")
MAILPIT_SMTP_PORT = int(os.environ.get("MAILPIT_SMTP_PORT", "1025"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_MAILPIT_INTEGRATION") != "1",
        reason="Set RUN_MAILPIT_INTEGRATION=1 to run the manual Mailpit integration test",
    ),
]


def mailpit_config():
    return {
        "ENABLE_SMTP": "1",
        "EMAIL_HOST": MAILPIT_SMTP_HOST,
        "EMAIL_PORT": str(MAILPIT_SMTP_PORT),
        "EMAIL_HOST_USER": "",
        "EMAIL_HOST_PASSWORD": "",
        "EMAIL_USE_TLS": "0",
        "EMAIL_USE_SSL": "0",
        "EMAIL_FROM": "notifications@example.invalid",
        "EMAIL_TIMEOUT": "10",
    }


@pytest.mark.django_db
def test_message_is_delivered_to_mailpit_with_expected_subject_and_link():
    session = requests.Session()
    session.delete(f"{MAILPIT_API_URL}/api/v1/messages")

    send_email_message(
        subject="PLN-017 Mailpit integration <nön-ASCII> ✓",
        body="Plain-text body for delivery validation.",
        recipients=["recipient@example.invalid"],
        html_body=(
            "<p>Plain-text body for delivery validation.</p>"
            '<a href="https://plane.example.invalid/work-items/1">Open item</a>'
        ),
        configuration=mailpit_config(),
    )

    response = session.get(f"{MAILPIT_API_URL}/api/v1/messages")
    response.raise_for_status()
    messages = response.json().get("messages") or []
    assert len(messages) == 1
    assert messages[0]["Subject"] == "PLN-017 Mailpit integration <nön-ASCII> ✓"

    message_id = messages[0]["ID"]
    detail = session.get(f"{MAILPIT_API_URL}/api/v1/message/{message_id}")
    detail.raise_for_status()
    body = detail.text
    assert "Plain-text body for delivery validation." in body
    assert "https://plane.example.invalid/work-items/1" in body
