# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from plane.db.models import UnsubscribeToken, UserNotificationPreference
from plane.utils.unsubscribe import (
    build_unsubscribe_url,
    create_unsubscribe_token,
    is_email_unsubscribed,
    verify_unsubscribe_token,
)


@pytest.mark.unit
@pytest.mark.django_db
class TestSignedUnsubscribe:
    def test_token_only_disables_its_own_event(self, create_user, workspace):
        token = create_unsubscribe_token(create_user, create_user.email, "project_invitation", workspace=workspace)

        record = verify_unsubscribe_token(token, consume=True)
        assert record is not None

        from plane.utils.unsubscribe import apply_unsubscribe

        apply_unsubscribe(record)

        preference = UserNotificationPreference.objects.get(user=create_user, workspace=workspace)
        assert preference.project_invitation is False
        assert preference.assignment is True
        assert preference.comment is True

    def test_tampered_token_is_rejected(self, create_user):
        token = create_unsubscribe_token(create_user, create_user.email, "comment")
        record = verify_unsubscribe_token(token + "tampered")
        assert record is None

    @override_settings(WEB_URL="https://plane.example.invalid")
    def test_link_is_public_and_uses_configured_web_url(self, create_user):
        url = build_unsubscribe_url(create_user, create_user.email, "comment")
        assert url.startswith("https://plane.example.invalid/api/public/unsubscribe/")

        response = APIClient().get(url)
        assert response.status_code == 200
        assert b"Security emails such as password resets are unaffected." in response.content

    def test_consumed_token_blocks_address_without_an_account(self):
        email = "invitee@example.invalid"
        token = create_unsubscribe_token(None, email, "project_invitation")

        record = verify_unsubscribe_token(token, consume=True)
        assert record is not None
        assert record.user is None
        assert is_email_unsubscribed(email, "project_invitation") is True
        assert is_email_unsubscribed(email, "comment") is False
        assert UnsubscribeToken.objects.filter(token=token, used_at__isnull=False).exists()

    def test_public_post_returns_the_scoped_event_type(self, create_user):
        token = create_unsubscribe_token(create_user, create_user.email, "comment")
        response = APIClient().post(reverse("public-unsubscribe", kwargs={"token": token}), {}, format="json")

        assert response.status_code == 200
        assert response.data["unsubscribed"] is True
        assert response.data["event_type"] == "comment"
