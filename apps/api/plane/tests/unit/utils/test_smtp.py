# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.utils.smtp import (
    SMTPConfigurationError,
    send_email_message,
    suppress_email,
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
        "EMAIL_TIMEOUT": "30",
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
        from smtplib import SMTPAuthenticationError

        config = enabled_config()
        mocker.patch("plane.utils.smtp.get_smtp_configuration", return_value=config)
        connection = mocker.patch("plane.utils.smtp.get_smtp_connection")
        connection.return_value.send_messages.side_effect = SMTPAuthenticationError(535, b"denied")

        with pytest.raises(SMTPConfigurationError, match="Invalid SMTP credentials"):
            send_email_message("Subject", "Body", ["recipient@example.invalid"], configuration=config)
