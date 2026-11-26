# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError
from django.core.validators import validate_email
from django.template.loader import render_to_string

# Module imports
from plane.license.utils.instance_value import is_smtp_enabled
from plane.utils.email import generate_plain_text_from_html
from plane.utils.smtp import SMTPConfigurationError, send_email_message


class Command(BaseCommand):
    """Send a test email through the same SMTP path used by notifications."""

    def add_arguments(self, parser):
        parser.add_argument("to_email", type=str, help="receiver's email")

    def handle(self, *args, **options):
        receiver_email = str(options.get("to_email") or "").strip()
        if not receiver_email:
            raise CommandError("Receiver email is required")

        try:
            validate_email(receiver_email)
        except ValidationError:
            raise CommandError("A valid receiver email address is required") from None

        if not is_smtp_enabled():
            self.stderr.write("SMTP is disabled; no test email was sent.")
            return

        html_content = render_to_string("emails/test_email.html")
        text_content = generate_plain_text_from_html(html_content)

        self.stdout.write("Trying to send test email...")
        try:
            send_email_message(
                subject="Test email from Plane",
                body=text_content,
                recipients=[receiver_email],
                html_body=html_content,
            )
            self.stdout.write(self.style.SUCCESS("Email successfully sent"))
        except SMTPConfigurationError as error:
            self.stderr.write(f"Error: Email could not be delivered due to {error}")
