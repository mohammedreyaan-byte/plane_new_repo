# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Transactional email for workspace invitation responses."""

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
def workspace_invitation_response(
    inviter_email,
    invited_email,
    workspace_name,
    workspace_slug,
    accepted,
    current_site,
):
    """Notify the inviter when an invitation is accepted or declined.

    The task is safe to enqueue when SMTP is disabled: it returns without
    touching the mail backend so the request that recorded the response cannot
    fail because email is unconfigured.
    """

    if not is_smtp_enabled() or not inviter_email or not invited_email:
        return

    try:
        response = "accepted" if accepted else "declined"
        context = {
            "inviter_email": inviter_email,
            "invited_email": invited_email,
            "workspace_name": workspace_name,
            "workspace_url": f"{str(current_site).rstrip('/')}/{workspace_slug}/",
            "response": response,
        }
        subject = f"{invited_email} {response} your invitation to {workspace_name} on Plane"
        html_content = render_to_string("emails/invitations/workspace_invitation_response.html", context)
        text_content = generate_plain_text_from_html(html_content)

        deliver_email_message(
            subject=subject,
            body=text_content,
            recipients=[inviter_email],
            html_body=html_content,
        )
    except Exception as error:  # pragma: no cover - defensive guard for workers
        log_exception(error)
