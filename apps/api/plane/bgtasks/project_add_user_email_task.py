# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from celery import shared_task

# Django imports
from django.template.loader import render_to_string

# Module imports
from plane.bgtasks.email_task import deliver_email_message
from plane.db.models import ProjectMember, User
from plane.license.utils.instance_value import is_smtp_enabled
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception


@shared_task
def project_add_user_email(current_site, project_member_id, invitor_id):
    try:
        if not is_smtp_enabled():
            return

        invitor = User.objects.get(pk=invitor_id)
        project_member = ProjectMember.objects.get(pk=project_member_id)

        member_email = project_member.member.email
        project_url = f"{current_site}/{project_member.workspace.slug}/projects/{project_member.project_id}/issues"
        context = {
            "project_name": project_member.project.name,
            "workspace_name": project_member.workspace.name,
            "email": member_email,
            "inviter_first_name": invitor.first_name,
            "project_url": project_url,
        }

        subject = "You have been invited to a Plane project"

        html_content = render_to_string("emails/notifications/project_addition.html", context)
        text_content = generate_plain_text_from_html(html_content)

        deliver_email_message(
            subject=subject,
            body=text_content,
            recipients=[member_email],
            html_body=html_content,
        )
        return
    except Exception as e:
        log_exception(e)
        return
