# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared SMTP delivery helpers used by notification and invitation tasks.

Every outbound path goes through this module so test-mode redirection, recipient
suppression, a bounded rate limit and SMTP response logging cannot be bypassed.
"""

# Python imports
import logging
import re
import smtplib
import threading
import time
from collections import deque

# Third party imports
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.mail.backends.base import BaseEmailBackend
from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPSenderRefused,
    SMTPServerDisconnected,
)

# Module imports
from plane.db.models import EmailSuppression
from plane.license.utils.instance_value import (
    _as_bool,
    get_smtp_configuration,
)

logger = logging.getLogger("plane.email")

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# SMTP servers report enhanced status either as ``535 5.7.8 ...`` or,
# in exception payloads, simply as ``5.7.8 ...``.
ENHANCED_STATUS_PATTERN = re.compile(r"^(?:\d{3}\s+)?([2-5]\.\d+\.\d+)")

# Hosts that are never a production relay. ``*.invalid`` and ``*.test`` are
# reserved names, so a staging guard cannot accidentally point at real mail.
LOCAL_RELAY_HOSTS = {"localhost", "127.0.0.1", "::1", "mailpit", "mailhog"}

_rate_limit_lock = threading.Lock()
_recent_sends = deque()


class SMTPConfigurationError(Exception):
    """Raised when SMTP is not usable or the server rejects a message."""


class ResponseCapturingSMTP(smtplib.SMTP):
    """SMTP client that retains the last response code for safe delivery logs."""

    def __init__(self, *args, **kwargs):
        self.last_response = None
        super().__init__(*args, **kwargs)

    def getreply(self):
        code, message = super().getreply()
        self.last_response = (code, message)
        return code, message


def smtp_response_details(connection=None, error=None):
    """Return only a numeric code and enhanced status code (never credentials)."""

    code = None
    message = ""
    if error is not None and isinstance(error, SMTPResponseException):
        code = error.smtp_code
        message = bytes(error.smtp_error or b"").decode("utf-8", "replace")
    if code is None and connection is not None:
        response = getattr(connection, "connection", None)
        last_response = getattr(response, "last_response", None)
        if isinstance(last_response, (tuple, list)) and len(last_response) >= 2:
            code, message = last_response[0], last_response[1]
            message = str(message)

    enhanced = ENHANCED_STATUS_PATTERN.match(message.strip())
    return {
        "smtp_code": int(code) if isinstance(code, int) else None,
        "smtp_status": enhanced.group(1) if enhanced else "",
    }


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
    if isinstance(error, SMTPResponseException):
        details = smtp_response_details(error=error)
        code = details["smtp_code"]
        status = details["smtp_status"]
        return f"The SMTP server rejected the message (code {code}{', status ' + status if status else ''})"
    # Unknown exception text can contain configuration details from a relay
    # library. Return only the exception class so operators get a useful signal
    # without risking credential or header disclosure.
    return f"Unexpected {type(error).__name__}"


def email_test_mode_enabled():
    return _as_bool(getattr(settings, "EMAIL_TEST_MODE", False))


def _is_real_relay_host(host):
    host = str(host or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host in LOCAL_RELAY_HOSTS or host.endswith((".invalid", ".test", ".localhost")):
        return False
    return True


def validate_email_test_mode(configuration):
    """Refuse a dangerous staging setup before any message is handed to a relay."""

    if not email_test_mode_enabled():
        return

    recipient = str(getattr(settings, "EMAIL_TEST_RECIPIENT", "") or "").strip()
    if not EMAIL_PATTERN.match(recipient):
        raise SMTPConfigurationError("EMAIL_TEST_MODE requires a valid EMAIL_TEST_RECIPIENT")

    if not _as_bool(getattr(settings, "EMAIL_TEST_MODE_ALLOW_REAL_RELAY", False)):
        host = str(configuration.get("EMAIL_HOST") or "").strip()
        if _is_real_relay_host(host):
            raise SMTPConfigurationError(
                "EMAIL_TEST_MODE is enabled with a real SMTP relay. Use a local test relay "
                "or set EMAIL_TEST_MODE_ALLOW_REAL_RELAY=1 explicitly for staging."
            )


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

    validate_email_test_mode(configuration)


def apply_email_test_mode(subject, recipients, configuration=None):
    """Return the effective subject and recipients for the current environment."""

    config = configuration or get_smtp_configuration()
    validate_email_test_mode(config)
    if not email_test_mode_enabled():
        return subject, list(dict.fromkeys(recipients))
    recipient = str(getattr(settings, "EMAIL_TEST_RECIPIENT", "") or "").strip()
    return f"[EMAIL TEST MODE] {subject}", [recipient]


def enforce_outbound_rate_limit():
    """Token bucket for outbound mail; locmem tests are never throttled."""

    backend = str(getattr(settings, "EMAIL_BACKEND", ""))
    if "locmem" in backend:
        return

    try:
        limit = int(getattr(settings, "EMAIL_RATE_LIMIT_PER_MINUTE", 60) or 60)
    except (TypeError, ValueError):
        limit = 60
    if limit <= 0:
        return

    now = time.monotonic()
    with _rate_limit_lock:
        while _recent_sends and now - _recent_sends[0] >= 60:
            _recent_sends.popleft()
        if len(_recent_sends) >= limit:
            raise SMTPConfigurationError(
                f"Outbound email rate limit of {limit} per minute reached; delivery will be retried"
            )
        _recent_sends.append(now)


def reset_outbound_rate_limit():
    """Test-only helper to clear the in-process rate-limit window."""

    with _rate_limit_lock:
        _recent_sends.clear()


def get_smtp_connection(configuration=None, connection_class=None):
    config = configuration or get_smtp_configuration()
    return get_connection(
        host=str(config.get("EMAIL_HOST") or "").strip(),
        port=int(config.get("EMAIL_PORT") or 587),
        username=str(config.get("EMAIL_HOST_USER") or "").strip() or None,
        password=config.get("EMAIL_HOST_PASSWORD") or None,
        use_tls=_as_bool(config.get("EMAIL_USE_TLS")),
        use_ssl=_as_bool(config.get("EMAIL_USE_SSL")),
        timeout=int(config.get("EMAIL_TIMEOUT") or 10),
        connection_class=connection_class or ResponseCapturingSMTP,
    )


def validate_smtp_connection(overrides=None):
    """Open and close an SMTP connection using the supplied candidate values."""

    configuration = get_smtp_configuration(overrides)
    validate_smtp_configuration(configuration)
    connection = get_smtp_connection(configuration)
    try:
        response = connection.open()
        code, message = response if isinstance(response, tuple) else (None, "")
        logger.info(
            "SMTP connection validated",
            extra={
                "smtp_code": code,
                "smtp_status": (
                    ENHANCED_STATUS_PATTERN.match(str(message).strip()).group(1)
                    if ENHANCED_STATUS_PATTERN.match(str(message).strip())
                    else ""
                ),
            },
        )
    except Exception as error:
        details = smtp_response_details(connection=connection, error=error)
        logger.warning(
            "SMTP connection validation failed",
            extra={"error_type": type(error).__name__, **details},
        )
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
    subject, recipient_list = apply_email_test_mode(subject, recipient_list, config)
    deliverable = [email for email in recipient_list if not is_email_suppressed(email)]
    if not deliverable:
        raise SMTPConfigurationError("All recipient addresses are suppressed")

    enforce_outbound_rate_limit()

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
        logger.warning(
            "SMTP recipient refused",
            extra={"recipient_count": len(deliverable), **smtp_response_details(connection=connection, error=error)},
        )
        raise SMTPConfigurationError(describe_smtp_error(error)) from error
    except Exception as error:
        logger.warning(
            "SMTP delivery failed",
            extra={"error_type": type(error).__name__, **smtp_response_details(connection=connection, error=error)},
        )
        raise SMTPConfigurationError(describe_smtp_error(error)) from error
    finally:
        if isinstance(connection, BaseEmailBackend):
            try:
                connection.close()
            except Exception:
                pass

    logger.info(
        "SMTP message accepted",
        extra={
            "recipient_count": len(deliverable),
            "message_id": str(message.message().get("Message-ID") or "")[:200],
            **smtp_response_details(connection=connection),
        },
    )
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
