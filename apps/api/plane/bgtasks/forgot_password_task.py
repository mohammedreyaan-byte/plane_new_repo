# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from celery import shared_task

# Django imports
from django.template.loader import render_to_string

# Module imports
from plane.bgtasks.email_task import deliver_email_message
from plane.license.utils.instance_value import is_smtp_enabled
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception


@shared_task
def forgot_password(first_name, email, uidb64, token, current_site):
    try:
        if not is_smtp_enabled():
            return

        relative_link = f"/accounts/reset-password/?uidb64={uidb64}&token={token}&email={email}"
        abs_url = str(current_site) + relative_link

        subject = "A new password to your Plane account has been requested"

        context = {
            "first_name": first_name,
            "forgot_password_url": abs_url,
            "email": email,
        }

        html_content = render_to_string("emails/auth/forgot_password.html", context)
        text_content = generate_plain_text_from_html(html_content)

        deliver_email_message(
            subject=subject,
            body=text_content,
            recipients=[email],
            html_body=html_content,
        )
        return
    except Exception as e:
        log_exception(e)
        return
