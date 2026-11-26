# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.bgtasks.page_comment_task import notify_page_comment
from plane.db.models import (
    EmailNotificationLog,
    Notification,
    Page,
    PageComment,
    Project,
    ProjectMember,
    ProjectPage,
    UserNotificationPreference,
    User,
)


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Page comments project",
        identifier="PC",
        workspace=workspace,
        created_by=create_user,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def page(db, workspace, project, create_user):
    page = Page.objects.create(
        name="Roadmap",
        workspace=workspace,
        owned_by=create_user,
        access=Page.PUBLIC_ACCESS,
        created_by=create_user,
    )
    ProjectPage.objects.create(
        workspace=workspace,
        project=project,
        page=page,
        created_by=create_user,
    )
    return page


@pytest.fixture
def member_user(db):
    user = User.objects.create(email="member@plane.so", username="page-comment-member", first_name="Page", last_name="Member")
    user.set_password("test-password")
    user.save()
    return user


@pytest.fixture
def other_project(db, workspace, member_user):
    project = Project.objects.create(
        name="Other project",
        identifier="OP",
        workspace=workspace,
        created_by=member_user,
    )
    ProjectMember.objects.create(project=project, member=member_user, role=20, is_active=True)
    return project


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def list_url(workspace_slug, project_id, page_id):
    return f"/api/workspaces/{workspace_slug}/projects/{project_id}/pages/{page_id}/comments/"


def detail_url(workspace_slug, project_id, page_id, comment_id):
    return f"{list_url(workspace_slug, project_id, page_id)}{comment_id}/"


@pytest.mark.unit
class TestPageCommentModel:
    @pytest.mark.django_db
    def test_save_strips_html(self, workspace, project, page, create_user):
        comment = PageComment.objects.create(
            workspace=workspace,
            project=project,
            page=page,
            actor=create_user,
            comment_html="<p>Hello <strong>world</strong></p>",
            created_by=create_user,
        )
        assert comment.comment_stripped == "Hello world"

        comment.comment_html = "<p>Updated</p>"
        comment.save()
        comment.refresh_from_db()
        assert comment.comment_stripped == "Updated"
        assert str(comment.id) == str(comment.id)


@pytest.mark.contract
class TestPageCommentApi:
    @pytest.mark.django_db
    def test_create_and_reply_with_pagination(self, session_client, workspace, project, page, create_user, member_user):
        ProjectMember.objects.create(project=project, member=member_user, role=15, is_active=True)
        url = list_url(workspace.slug, project.id, page.id)

        with patch("plane.app.views.page.comment.notify_page_comment.delay") as mock_delay:
            response = session_client.post(url, {"comment_html": "<p>First comment</p>"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["content"] == "<p>First comment</p>"
        assert response.data["content_stripped"] == "First comment"
        assert str(response.data["actor_detail"]["id"]) == str(create_user.id)
        mock_delay.assert_called_once()

        parent_id = response.data["id"]
        member_client = client_for(member_user)
        with patch("plane.app.views.page.comment.notify_page_comment.delay") as mock_delay:
            reply = member_client.post(
                url,
                {"comment_html": "<p>A reply</p>", "parent": parent_id},
                format="json",
            )
        assert reply.status_code == status.HTTP_201_CREATED
        assert reply.data["parent"] == parent_id
        mock_delay.assert_called_once()

        with patch("plane.app.views.page.comment.notify_page_comment.delay"):
            for index in range(2):
                assert (
                    session_client.post(url, {"comment_html": f"<p>Extra {index}</p>"}, format="json").status_code
                    == status.HTTP_201_CREATED
                )

        paginated = session_client.get(url, {"per_page": 2, "cursor": "2:0:0"})
        assert paginated.status_code == status.HTTP_200_OK
        assert paginated.data["count"] == 2
        assert paginated.data["total_count"] == 4
        assert "results" in paginated.data

    @pytest.mark.django_db
    def test_edit_and_delete_permissions(self, session_client, workspace, project, page, create_user, member_user):
        ProjectMember.objects.create(project=project, member=member_user, role=15, is_active=True)
        other_member = User.objects.create(
            email="other@plane.so",
            username="page-comment-other",
            first_name="Page",
            last_name="Other",
        )
        ProjectMember.objects.create(project=project, member=other_member, role=15, is_active=True)
        member_client = client_for(member_user)
        other_member_client = client_for(other_member)
        comment = PageComment.objects.create(
            workspace=workspace,
            project=project,
            page=page,
            actor=member_user,
            comment_html="<p>Mine</p>",
            created_by=member_user,
        )
        detail = detail_url(workspace.slug, project.id, page.id, comment.id)

        forbidden = session_client.patch(detail, {"comment_html": "<p>Not yours</p>"}, format="json")
        assert forbidden.status_code == status.HTTP_403_FORBIDDEN

        updated = member_client.patch(detail, {"comment_html": "<p>Edited</p>"}, format="json")
        assert updated.status_code == status.HTTP_200_OK
        comment.refresh_from_db()
        assert comment.comment_html == "<p>Edited</p>"
        assert comment.edited_at is not None

        forbidden_delete = other_member_client.delete(detail)
        assert forbidden_delete.status_code == status.HTTP_403_FORBIDDEN
        assert not PageComment.all_objects.filter(pk=comment.pk, deleted_at__isnull=False).exists()

        deleted = member_client.delete(detail)
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert PageComment.all_objects.filter(pk=comment.pk, deleted_at__isnull=False).exists()

        other_comment = PageComment.objects.create(
            workspace=workspace,
            project=project,
            page=page,
            actor=member_user,
            comment_html="<p>Admin deletes</p>",
            created_by=member_user,
        )
        admin_delete = session_client.delete(
            detail_url(workspace.slug, project.id, page.id, other_comment.id)
        )
        assert admin_delete.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.django_db
    def test_cross_project_and_private_page_denied(
        self, session_client, workspace, project, page, create_user, member_user, other_project
    ):
        ProjectMember.objects.create(project=project, member=member_user, role=15, is_active=True)
        member_client = client_for(member_user)

        # The page does not belong to other_project.
        foreign_list = member_client.get(list_url(workspace.slug, other_project.id, page.id))
        assert foreign_list.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

        private_page = Page.objects.create(
            name="Private",
            workspace=workspace,
            owned_by=create_user,
            access=Page.PRIVATE_ACCESS,
            created_by=create_user,
        )
        ProjectPage.objects.create(workspace=workspace, project=project, page=private_page, created_by=create_user)
        private_comment = PageComment.objects.create(
            workspace=workspace,
            project=project,
            page=private_page,
            actor=create_user,
            comment_html="<p>Secret</p>",
            created_by=create_user,
        )
        private_list = member_client.get(list_url(workspace.slug, project.id, private_page.id))
        assert private_list.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        private_detail = member_client.get(
            detail_url(workspace.slug, project.id, private_page.id, private_comment.id)
        )
        assert private_detail.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    @pytest.mark.django_db
    def test_guest_can_comment_and_notification_dispatch(
        self, workspace, project, page, create_user, member_user
    ):
        UserNotificationPreference.objects.create(user=create_user, comment=True)
        ProjectMember.objects.create(project=project, member=member_user, role=5, is_active=True)
        project.guest_view_all_features = True
        project.save(update_fields=["guest_view_all_features"])
        guest_client = client_for(member_user)

        with patch("plane.app.views.page.comment.notify_page_comment.delay") as mock_delay:
            response = guest_client.post(
                list_url(workspace.slug, project.id, page.id),
                {"comment_html": "<p>Guest comment</p>"},
                format="json",
            )
        assert response.status_code == status.HTTP_201_CREATED
        mock_delay.assert_called_once()

        comment = PageComment.objects.get(pk=response.data["id"])
        notify_page_comment(comment_id=str(comment.id))

        notifications = Notification.objects.filter(entity_name="page", entity_identifier=page.id)
        assert notifications.count() == 1
        assert notifications.first().receiver_id == create_user.id
        assert notifications.first().triggered_by_id == member_user.id
        assert EmailNotificationLog.objects.filter(receiver=create_user, entity_name="page").count() == 1

        # Reply notification: participants are deduplicated, the actor is excluded,
        # and email logs respect an explicit disabled comment preference.
        UserNotificationPreference.objects.filter(user=member_user).update(comment=False)
        reply = PageComment.objects.create(
            workspace=workspace,
            project=project,
            page=page,
            actor=create_user,
            comment_html="<p>Reply</p>",
            parent=comment,
            created_by=create_user,
        )
        Notification.objects.all().delete()
        EmailNotificationLog.objects.all().delete()
        notify_page_comment(comment_id=str(reply.id))
        reply_notifications = Notification.objects.filter(entity_name="page", entity_identifier=page.id)
        assert set(reply_notifications.values_list("receiver_id", flat=True)) == {member_user.id}
        assert not EmailNotificationLog.objects.filter(receiver_id=member_user).exists()

    @pytest.mark.django_db
    def test_page_serializer_exposes_comment_count(self, session_client, workspace, project, page, create_user):
        PageComment.objects.create(
            workspace=workspace,
            project=project,
            page=page,
            actor=create_user,
            comment_html="<p>Count me</p>",
            created_by=create_user,
        )
        response = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/pages/{page.id}/"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["comment_count"] == 1
