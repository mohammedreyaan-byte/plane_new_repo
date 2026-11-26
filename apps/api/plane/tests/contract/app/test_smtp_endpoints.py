# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import User
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from plane.license.utils.encryption import decrypt_data
from plane.utils.smtp import SMTPConfigurationError


@pytest.fixture
def instance_admin_client(create_user):
    instance = Instance.objects.create(
        instance_name="Test Instance",
        instance_id=uuid4().hex,
        current_version="0.0.0",
        last_checked_at=timezone.now(),
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user, role=20)
    client = APIClient()
    client.force_authenticate(user=create_user)
    return client


def enabled_config():
    return {
        "ENABLE_SMTP": "1",
        "EMAIL_HOST": "smtp.example.invalid",
        "EMAIL_PORT": "587",
        "EMAIL_HOST_USER": "",
        "EMAIL_HOST_PASSWORD": "",
        "EMAIL_USE_TLS": "1",
        "EMAIL_USE_SSL": "0",
        "EMAIL_FROM": "notifications@example.invalid",
        "EMAIL_TIMEOUT": "30",
    }


@pytest.mark.contract
@pytest.mark.django_db
class TestInstanceSMTPEndpoints:
    def test_test_email_success_persists_result(self, instance_admin_client, mocker):
        mocker.patch(
            "plane.license.api.views.configuration.get_smtp_configuration",
            return_value=enabled_config(),
        )
        send = mocker.patch("plane.license.api.views.configuration.send_email_message", return_value=True)

        response = instance_admin_client.post(
            reverse("instance-smtp-test-email"),
            {"receiver_email": "recipient@example.invalid"},
            format="json",
        )

        assert response.status_code == 200
        send.assert_called_once()
        assert InstanceConfiguration.objects.get(key="EMAIL_LAST_TEST_STATUS").value == "success"
        assert InstanceConfiguration.objects.get(key="EMAIL_LAST_TEST_MESSAGE").value
        assert InstanceConfiguration.objects.get(key="EMAIL_LAST_TEST_AT").value

    def test_test_email_failure_persists_error_without_credentials(self, instance_admin_client, mocker):
        mocker.patch(
            "plane.license.api.views.configuration.get_smtp_configuration",
            return_value=enabled_config(),
        )
        mocker.patch(
            "plane.license.api.views.configuration.send_email_message",
            side_effect=SMTPConfigurationError("Invalid SMTP credentials provided"),
        )

        response = instance_admin_client.post(
            reverse("instance-smtp-test-email"),
            {"receiver_email": "recipient@example.invalid"},
            format="json",
        )

        assert response.status_code == 400
        assert response.data["error"] == "Invalid SMTP credentials provided"
        assert InstanceConfiguration.objects.get(key="EMAIL_LAST_TEST_STATUS").value == "failed"
        assert "password@example.invalid" not in InstanceConfiguration.objects.get(key="EMAIL_LAST_TEST_MESSAGE").value

    def test_non_admin_cannot_send_test_email(self, api_client, mocker):
        send = mocker.patch("plane.license.api.views.configuration.send_email_message")

        response = api_client.post(
            reverse("instance-smtp-test-email"),
            {"receiver_email": "recipient@example.invalid"},
            format="json",
        )

        assert response.status_code in (401, 403)
        send.assert_not_called()

    def test_patch_creates_keys_encrypts_password_and_clears_old_test_result(self, instance_admin_client, mocker):
        mocker.patch("plane.license.api.views.configuration.validate_smtp_connection")
        InstanceConfiguration.objects.create(
            key="EMAIL_LAST_TEST_STATUS", value="success", category="SMTP", is_encrypted=False
        )

        response = instance_admin_client.patch(
            reverse("instance-smtp"),
            {
                "EMAIL_HOST": "smtp.example.invalid",
                "EMAIL_PORT": "587",
                "EMAIL_FROM": "notifications@example.invalid",
                "EMAIL_HOST_PASSWORD": "password@example.invalid",
            },
            format="json",
        )

        assert response.status_code == 200
        assert response.data["EMAIL_HOST_PASSWORD_SET"] is True
        assert "password@example.invalid" not in str(response.data)
        password_config = InstanceConfiguration.objects.get(key="EMAIL_HOST_PASSWORD")
        assert password_config.is_encrypted is True
        assert password_config.value != "password@example.invalid"
        assert decrypt_data(password_config.value) == "password@example.invalid"
        assert InstanceConfiguration.objects.get(key="EMAIL_LAST_TEST_STATUS").value == ""

    def test_enabling_smtp_without_connection_changes_does_not_validate(self, instance_admin_client, mocker):
        validate = mocker.patch("plane.license.api.views.configuration.validate_smtp_connection")

        response = instance_admin_client.patch(
            reverse("instance-smtp"),
            {"ENABLE_SMTP": "1"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["ENABLE_SMTP"] == "1"
        validate.assert_not_called()
        assert InstanceConfiguration.objects.get(key="ENABLE_SMTP").value == "1"

    def test_smtp_configuration_endpoint_requires_admin(self, api_client):
        response = api_client.get(reverse("instance-smtp"))
        assert response.status_code in (401, 403)
