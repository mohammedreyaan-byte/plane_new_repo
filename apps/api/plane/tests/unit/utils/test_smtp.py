# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from smtplib import SMTPAuthenticationError

import pytest
from django.core.mail import EmailMultiAlternatives
from django.test import override_settings

from plane.utils.smtp import (
    SMTPConfigurationError,
    describe_smtp_error,
    reset_outbound_rate_limit,
    send_email_message,
    suppress_email,
    smtp_response_details,
    validate_smtp_configuration,
)


def enabled_config(**overrides):
    config = {
        "ENABLE_SMTP": "1",
        "EMAIL_HOST": "smtp.example.invalid",
        "EMAIL_PORT": "587",
        "EMAIL_HOST_USER": "",
        "EMAIL_HOST_PASSWORD": "",
        "EMAIL_USE_TLS": "1",
        "EMAIL_USE_SSL": "0",
        "EMAIL_FROM": "notifications@example.invalid",
        "EMAIL_TIMEOUT": "10",
    }
    config.update(overrides)
    return config


@pytest.mark.unit
class TestSMTPConfigurationValidation:
    def test_disabled_smtp_is_rejected_without_a_connection(self):
        with pytest.raises(SMTPConfigurationError, match="SMTP is disabled"):
            validate_smtp_configuration(enabled_config(ENABLE_SMTP="0"))

    @pytest.mark.parametrize(
        "overrides, expected",
        [
            ({"EMAIL_HOST": ""}, "host is required"),
            ({"EMAIL_FROM": "not-an-address"}, "sender email"),
            ({"EMAIL_PORT": "not-a-number"}, "port must be a number"),
            ({"EMAIL_PORT": "70000"}, "between 1 and 65535"),
            ({"EMAIL_USE_TLS": "1", "EMAIL_USE_SSL": "1"}, "TLS and SSL cannot both"),
        ],
    )
    def test_invalid_configuration_is_rejected(self, overrides, expected):
        with pytest.raises(SMTPConfigurationError, match=expected):
            validate_smtp_configuration(enabled_config(**overrides))

    def test_valid_tls_configuration_is_accepted(self):
        validate_smtp_configuration(enabled_config())


@pytest.mark.unit
@pytest.mark.django_db
class TestSMTPDeliveryGuards:
    def test_suppressed_recipient_is_not_handed_to_the_backend(self, mocker):
        config = enabled_config()
        mocker.patch("plane.utils.smtp.get_smtp_configuration", return_value=config)
        send = mocker.patch("plane.utils.smtp.EmailMultiAlternatives.send", return_value=1)

        suppress_email("blocked@example.invalid")

        with pytest.raises(SMTPConfigurationError, match="suppressed"):
            send_email_message("Subject", "Body", ["blocked@example.invalid"], configuration=config)

        send.assert_not_called()

    def test_delivery_failure_is_wrapped_without_a_server_error(self, mocker):
        config = enabled_config()
        mocker.patch("plane.utils.smtp.get_smtp_configuration", return_value=config)
        connection = mocker.patch("plane.utils.smtp.get_smtp_connection")
        connection.return_value.send_messages.side_effect = SMTPAuthenticationError(535, b"denied")

        with pytest.raises(SMTPConfigurationError, match="Invalid SMTP credentials"):
            send_email_message("Subject", "Body", ["recipient@example.invalid"], configuration=config)

    def test_authentication_error_never_echoes_credentials(self):
        error = SMTPAuthenticationError(535, b"5.7.8 Username and password not accepted for secret-value")
        assert describe_smtp_error(error) == "Invalid SMTP credentials provided"
        assert "secret-value" not in describe_smtp_error(error)

    def test_smtp_code_and_enhanced_status_are_logged_without_body(self):
        error = SMTPAuthenticationError(535, b"5.7.8 Username and password not accepted")
        assert smtp_response_details(error=error) == {"smtp_code": 535, "smtp_status": "5.7.8"}

    @override_settings(EMAIL_TEST_MODE="1", EMAIL_TEST_RECIPIENT="qa@example.invalid")
    def test_test_mode_redirects_recipient_and_prefixes_subject(self, mocker):
        config = enabled_config(EMAIL_HOST="mailpit")
        mocker.patch("plane.utils.smtp.get_smtp_configuration", return_value=config)
        mocker.patch("plane.utils.smtp.get_smtp_connection")
        messages = []

        def capture(self, *args, **kwargs):
            messages.append(self)
            return 1

        mocker.patch.object(EmailMultiAlternatives, "send", capture)

        send_email_message("Original subject", "Body", ["real@example.invalid"], configuration=config)

        assert len(messages) == 1
        assert messages[0].to == ["qa@example.invalid"]
        assert messages[0].subject == "[EMAIL TEST MODE] Original subject"

    @override_settings(EMAIL_TEST_MODE="1", EMAIL_TEST_RECIPIENT="qa@example.invalid")
    def test_test_mode_refuses_a_real_relay_unless_explicitly_allowed(self):
        config = enabled_config(EMAIL_HOST="smtp.example.com")
        with pytest.raises(
            SMTPConfigurationError,
            match=(
                "EMAIL_TEST_MODE is enabled with a real SMTP relay\\. Use a local test relay or set "
                "EMAIL_TEST_MODE_ALLOW_REAL_RELAY=1 explicitly for staging\\."
            ),
        ):
            send_email_message("Subject", "Body", ["real@example.invalid"], configuration=config)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_RATE_LIMIT_PER_MINUTE=1,
        EMAIL_TEST_MODE=False,
    )
    def test_outbound_rate_limit_is_enforced_for_real_backends(self, mocker):
        reset_outbound_rate_limit()
        config = enabled_config()
        mocker.patch("plane.utils.smtp.get_smtp_configuration", return_value=config)
        mocker.patch("plane.utils.smtp.get_smtp_connection")
        mocker.patch.object(EmailMultiAlternatives, "send", return_value=1)

        send_email_message("First", "Body", ["one@example.invalid"], configuration=config)
        with pytest.raises(SMTPConfigurationError, match="Outbound email rate limit of 1 per minute reached"):
            send_email_message("Second", "Body", ["two@example.invalid"], configuration=config)
        reset_outbound_rate_limit()
