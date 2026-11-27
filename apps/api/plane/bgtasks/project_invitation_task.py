# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from celery import shared_task

# Django imports
from django.template.loader import render_to_string

# Module imports
from plane.bgtasks.email_task import deliver_email_message
from plane.db.models import Project, ProjectMemberInvite, User
from plane.license.utils.instance_value import is_smtp_enabled
from plane.utils.email import generate_plain_text_from_html, truncate_email_subject
from plane.utils.exception_logger import log_exception
from plane.utils.unsubscribe import (
    build_unsubscribe_url,
    email_preference_allows,
    is_email_unsubscribed,
)


@shared_task
def project_invitation(email, project_id, token, current_site, invitor):
    try:
        user = User.objects.get(email=invitor)
        project = Project.objects.get(pk=project_id)
        project_member_invite = ProjectMemberInvite.objects.get(token=token, email=email)
        invitee = User.objects.filter(email__iexact=email).first()

        if is_email_unsubscribed(email, "project_invitation") or (
            invitee is not None and not email_preference_allows(invitee, "project_invitation", project=project)
        ):
            return

        relativelink = f"/project-invitations/?invitation_id={project_member_invite.id}&email={email}&slug={project.workspace.slug}&project_id={str(project_id)}"  # noqa: E501
        abs_url = current_site + relativelink

        subject = truncate_email_subject(
            f"{user.first_name or user.display_name or user.email} invited you to join {project.name} on Plane"
        )

        context = {
            "email": email,
            "first_name": user.first_name,
            "project_name": project.name,
            "invitation_url": abs_url,
            "current_site": current_site,
            "mirror": current_site,
            "unsubscribe": build_unsubscribe_url(
                invitee,
                email,
                "project_invitation",
                workspace=project.workspace,
                project=project,
            ),
        }

        html_content = render_to_string("emails/invitations/project_invitation.html", context)
        text_content = generate_plain_text_from_html(html_content)

        project_member_invite.message = text_content
        project_member_invite.save()

        if not is_smtp_enabled():
            return

        deliver_email_message(
            subject=subject,
            body=text_content,
            recipients=[email],
            html_body=html_content,
        )
        return
    except (Project.DoesNotExist, ProjectMemberInvite.DoesNotExist):
        return
    except Exception as e:
        log_exception(e)
        return
