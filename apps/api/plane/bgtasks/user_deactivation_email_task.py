# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from celery import shared_task

# Django imports
from django.template.loader import render_to_string

# Module imports
from plane.bgtasks.email_task import deliver_email_message
from plane.db.models import User
from plane.license.utils.instance_value import is_smtp_enabled
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception


@shared_task
def user_deactivation_email(current_site, user_id):
    try:
        if not is_smtp_enabled():
            return

        user = User.objects.get(id=user_id)
        subject = f"{user.first_name or user.display_name or user.email} has been deactivated on Plane"

        context = {"email": str(user.email), "login_url": current_site + "/login"}

        html_content = render_to_string("emails/user/user_deactivation.html", context)
        text_content = generate_plain_text_from_html(html_content)

        deliver_email_message(
            subject=subject,
            body=text_content,
            recipients=[user.email],
            html_body=html_content,
        )
        return
    except Exception as e:
        log_exception(e)
        return
