# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Notification dispatch for comments on pages.

Email delivery is deliberately not attempted here: ``EmailNotificationLog``
rows are queued for the existing email worker, so this task never fails when
SMTP is disabled.
"""

import logging

from celery import shared_task
from django.db.models import Q

from plane.db.models import (
    EmailNotificationLog,
    Notification,
    PageComment,
    ProjectMember,
    UserNotificationPreference,
)

logger = logging.getLogger("plane.worker")


def get_thread_root(comment):
    """Return the top level comment of the thread containing ``comment``."""
    root = comment
    seen = set()
    while root.parent_id and str(root.parent_id) not in seen:
        seen.add(str(root.id))
        parent = PageComment.all_objects.filter(pk=root.parent_id).first()
        if parent is None:
            break
        root = parent
    return root


def get_comment_recipients(comment):
    """Return user ids that should receive an in-app notification."""
    root = get_thread_root(comment)
    page_owner_id = comment.page.owned_by_id
    if comment.parent_id:
        thread_actor_ids = set(
            PageComment.objects.filter(
                page_id=comment.page_id,
                deleted_at__isnull=True,
            )
            .filter(Q(pk=root.pk) | Q(parent_id=root.pk))
            .exclude(actor_id__isnull=True)
            .values_list("actor_id", flat=True)
        )
        recipients = thread_actor_ids | {page_owner_id}
    else:
        recipients = {page_owner_id}

    recipients.discard(None)
    recipients.discard(comment.actor_id)

    # Only users who can still view the page should be notified.
    return set(
        ProjectMember.objects.filter(
            project_id=comment.project_id,
            is_active=True,
            member_id__in=recipients,
        ).values_list("member_id", flat=True)
    )


@shared_task
def notify_page_comment(comment_id):
    try:
        comment = (
            PageComment.objects.select_related("page", "workspace", "project", "actor")
            .filter(pk=comment_id, deleted_at__isnull=True)
            .first()
        )
        if comment is None:
            return

        recipients = get_comment_recipients(comment)
        if not recipients:
            return

        actor_name = comment.actor.display_name if comment.actor_id and comment.actor else "Someone"
        is_reply = comment.parent_id is not None
        title = (
            f"{actor_name} replied to a comment on {comment.page.name}"
            if is_reply
            else f"{actor_name} commented on {comment.page.name}"
        )
        payload = {
            "page": {
                "id": str(comment.page_id),
                "name": comment.page.name,
            },
            "page_comment": {
                "id": str(comment.id),
                "parent_id": str(comment.parent_id) if comment.parent_id else None,
                "comment": comment.comment_stripped,
            },
        }

        # An existing preference row is required before an email log is queued.
        preferences = {
            preference.user_id: preference
            for preference in UserNotificationPreference.objects.filter(user_id__in=recipients)
        }

        notifications = []
        email_logs = []
        for receiver_id in recipients:
            notifications.append(
                Notification(
                    workspace=comment.workspace,
                    project=comment.project,
                    sender=(
                        "in_app:page_comments:replied" if is_reply else "in_app:page_comments:created"
                    ),
                    triggered_by_id=comment.actor_id,
                    receiver_id=receiver_id,
                    entity_identifier=comment.page_id,
                    entity_name="page",
                    title=title,
                    message={"comment": comment.comment_stripped},
                    message_html=comment.comment_html,
                    message_stripped=comment.comment_stripped,
                    data=payload,
                )
            )
            preference = preferences.get(receiver_id)
            if preference is not None and preference.comment:
                email_logs.append(
                    EmailNotificationLog(
                        receiver_id=receiver_id,
                        triggered_by_id=comment.actor_id,
                        entity_identifier=comment.page_id,
                        entity_name="page",
                        entity="page_comment",
                        new_value=comment.comment_stripped[:300],
                        data=payload,
                    )
                )

        Notification.objects.bulk_create(notifications, batch_size=100)
        EmailNotificationLog.objects.bulk_create(email_logs, batch_size=100, ignore_conflicts=True)
    except Exception:
        logger.exception("Failed to dispatch page comment notifications")
