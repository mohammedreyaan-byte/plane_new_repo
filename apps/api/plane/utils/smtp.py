# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared SMTP delivery helpers used by notification and invitation tasks."""

# Python imports
import re

# Third party imports
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.mail.backends.base import BaseEmailBackend
from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPRecipientsRefused,
    SMTPSenderRefused,
    SMTPServerDisconnected,
)

# Module imports
from plane.db.models import EmailSuppression
from plane.license.utils.instance_value import (
    _as_bool,
    get_smtp_configuration,
)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SMTPConfigurationError(Exception):
    """Raised when SMTP is not usable or the server rejects a message."""


def describe_smtp_error(error):
    if isinstance(error, SMTPAuthenticationError):
        return "Invalid SMTP credentials provided"
    if isinstance(error, SMTPConnectError):
        return "Could not connect with the SMTP server"
    if isinstance(error, SMTPSenderRefused):
        return "The configured sender address was refused"
    if isinstance(error, SMTPServerDisconnected):
        return "The SMTP server disconnected unexpectedly"
    if isinstance(error, SMTPRecipientsRefused):
        return "All recipient addresses were refused"
    if isinstance(error, (TimeoutError, ConnectionError)):
        return "Timeout or network error while connecting to the SMTP server"
    if isinstance(error, SMTPConfigurationError):
        return str(error)
    message = str(error).strip()
    return message[:300] if message else "Could not send email"


def validate_smtp_configuration(configuration):
    if not _as_bool(configuration.get("ENABLE_SMTP")):
        raise SMTPConfigurationError("SMTP is disabled")

    host = str(configuration.get("EMAIL_HOST") or "").strip()
    sender = str(configuration.get("EMAIL_FROM") or "").strip()
    if not host:
        raise SMTPConfigurationError("SMTP host is required")
    if not sender or not EMAIL_PATTERN.match(sender):
        raise SMTPConfigurationError("A valid sender email address is required")

    try:
        port = int(configuration.get("EMAIL_PORT") or 0)
    except (TypeError, ValueError):
        raise SMTPConfigurationError("SMTP port must be a number") from None
    if port < 1 or port > 65535:
        raise SMTPConfigurationError("SMTP port must be between 1 and 65535")

    use_tls = _as_bool(configuration.get("EMAIL_USE_TLS"))
    use_ssl = _as_bool(configuration.get("EMAIL_USE_SSL"))
    if use_tls and use_ssl:
        raise SMTPConfigurationError("TLS and SSL cannot both be enabled")


def get_smtp_connection(configuration=None):
    config = configuration or get_smtp_configuration()
    return get_connection(
        host=str(config.get("EMAIL_HOST") or "").strip(),
        port=int(config.get("EMAIL_PORT") or 587),
        username=str(config.get("EMAIL_HOST_USER") or "").strip() or None,
        password=config.get("EMAIL_HOST_PASSWORD") or None,
        use_tls=_as_bool(config.get("EMAIL_USE_TLS")),
        use_ssl=_as_bool(config.get("EMAIL_USE_SSL")),
        timeout=int(config.get("EMAIL_TIMEOUT") or 30),
    )


def validate_smtp_connection(overrides=None):
    """Open and close an SMTP connection using the supplied candidate values."""

    configuration = get_smtp_configuration(overrides)
    validate_smtp_configuration(configuration)
    connection = get_smtp_connection(configuration)
    try:
        connection.open()
    except Exception as error:
        raise SMTPConfigurationError(describe_smtp_error(error)) from error
    finally:
        try:
            connection.close()
        except Exception:
            pass


def is_email_suppressed(email):
    if not email:
        return False
    return EmailSuppression.objects.filter(email__iexact=email.strip(), is_active=True).exists()


def suppress_email(email, reason="Recipient refused"):
    if not email:
        return
    EmailSuppression.objects.update_or_create(
        email=email.strip().lower(),
        defaults={"reason": str(reason)[:255], "is_active": True},
    )


def send_email_message(subject, body, recipients, html_body=None, configuration=None):
    """Send one transactional email through the configured SMTP server.

    Returns ``True`` when at least one recipient accepted the message. Callers
    handle ``SMTPConfigurationError`` so disabled SMTP never raises a 500.
    """

    config = configuration or get_smtp_configuration()
    validate_smtp_configuration(config)

    recipient_list = [str(email).strip() for email in recipients if str(email).strip()]
    deliverable = [email for email in recipient_list if not is_email_suppressed(email)]
    if not deliverable:
        raise SMTPConfigurationError("All recipient addresses are suppressed")

    connection = get_smtp_connection(config)
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=str(config.get("EMAIL_FROM")).strip(),
        to=deliverable,
        connection=connection,
    )
    if html_body:
        message.attach_alternative(html_body, "text/html")

    try:
        message.send(fail_silently=False)
    except SMTPRecipientsRefused as error:
        for refused_recipient in getattr(error, "recipients", {}) or {}:
            suppress_email(refused_recipient, "Recipient refused by SMTP server")
        raise SMTPConfigurationError(describe_smtp_error(error)) from error
    except Exception as error:
        raise SMTPConfigurationError(describe_smtp_error(error)) from error
    finally:
        if isinstance(connection, BaseEmailBackend):
            try:
                connection.close()
            except Exception:
                pass

    return True


def smtp_configuration_values(configuration):
    """Return only the caller-editable SMTP keys, encrypted password excluded."""

    return {
        "ENABLE_SMTP": "1" if _as_bool(configuration.get("ENABLE_SMTP")) else "0",
        "EMAIL_HOST": str(configuration.get("EMAIL_HOST") or ""),
        "EMAIL_PORT": str(configuration.get("EMAIL_PORT") or ""),
        "EMAIL_HOST_USER": str(configuration.get("EMAIL_HOST_USER") or ""),
        "EMAIL_USE_TLS": "1" if _as_bool(configuration.get("EMAIL_USE_TLS")) else "0",
        "EMAIL_USE_SSL": "1" if _as_bool(configuration.get("EMAIL_USE_SSL")) else "0",
        "EMAIL_FROM": str(configuration.get("EMAIL_FROM") or ""),
        "EMAIL_TIMEOUT": str(configuration.get("EMAIL_TIMEOUT") or ""),
    }
