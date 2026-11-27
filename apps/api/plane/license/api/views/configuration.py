# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import Case, Q, Value, When
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .base import BaseAPIView
from plane.bgtasks.email_task import send_test_email
from plane.db.models import EmailNotificationLog, EmailSuppression
from plane.license.api.permissions import InstanceAdminPermission
from plane.license.api.serializers import InstanceConfigurationSerializer
from plane.license.models import InstanceConfiguration
from plane.license.utils.encryption import encrypt_data
from plane.license.utils.instance_value import (
    _as_bool,
    get_smtp_configuration,
)
from plane.utils.cache import cache_response, invalidate_cache
from plane.utils.smtp import (
    SMTPConfigurationError,
    smtp_configuration_values,
    suppress_email,
    validate_smtp_connection,
)

SMTP_TEST_RESULT_KEYS = ["EMAIL_LAST_TEST_STATUS", "EMAIL_LAST_TEST_MESSAGE", "EMAIL_LAST_TEST_AT"]

SMTP_CONFIG_KEYS = [
    "ENABLE_SMTP",
    "EMAIL_HOST",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_PORT",
    "EMAIL_FROM",
    "EMAIL_USE_TLS",
    "EMAIL_USE_SSL",
    "EMAIL_TIMEOUT",
]
SMTP_CONNECTION_KEYS = [key for key in SMTP_CONFIG_KEYS if key != "ENABLE_SMTP"]


def _set_email_test_result(test_status, message):
    values = {
        "EMAIL_LAST_TEST_STATUS": test_status,
        "EMAIL_LAST_TEST_MESSAGE": str(message or "")[:500],
        "EMAIL_LAST_TEST_AT": timezone.now().isoformat(),
    }
    for key, value in values.items():
        InstanceConfiguration.objects.update_or_create(
            key=key,
            defaults={"value": value, "category": "SMTP", "is_encrypted": False},
        )


def _clear_email_test_result():
    """A changed or disabled configuration invalidates any previous test result."""

    for key in SMTP_TEST_RESULT_KEYS:
        InstanceConfiguration.objects.update_or_create(
            key=key,
            defaults={"value": "", "category": "SMTP", "is_encrypted": False},
        )


class InstanceConfigurationEndpoint(BaseAPIView):
    permission_classes = [InstanceAdminPermission]

    @cache_response(60 * 60 * 2, user=False)
    def get(self, request):
        instance_configurations = InstanceConfiguration.objects.all()
        serializer = InstanceConfigurationSerializer(instance_configurations, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @invalidate_cache(path="/api/instances/configurations/", user=False)
    @invalidate_cache(path="/api/instances/", user=False)
    def patch(self, request):
        if _as_bool(request.data.get("validate_connection", False)):
            overrides = {
                key: request.data[key]
                for key in SMTP_CONFIG_KEYS
                if key in request.data and not (key == "EMAIL_HOST_PASSWORD" and not request.data[key])
            }
            try:
                validate_smtp_connection(overrides)
            except SMTPConfigurationError as error:
                return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        configurations = InstanceConfiguration.objects.filter(key__in=request.data.keys())

        bulk_configurations = []
        for configuration in configurations:
            raw_value = request.data.get(configuration.key, configuration.value)
            value = "" if raw_value is None else str(raw_value).strip()
            if configuration.is_encrypted:
                configuration.value = encrypt_data(value)
            else:
                configuration.value = value
            bulk_configurations.append(configuration)

        InstanceConfiguration.objects.bulk_update(bulk_configurations, ["value"], batch_size=100)

        serializer = InstanceConfigurationSerializer(configurations, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class InstanceSMTPConfigurationEndpoint(BaseAPIView):
    """Admin API for the singleton instance's SMTP settings."""

    permission_classes = [InstanceAdminPermission]

    def _response_data(self):
        configuration = get_smtp_configuration()
        data = smtp_configuration_values(configuration)
        data.pop("EMAIL_HOST_PASSWORD", None)
        data["EMAIL_HOST_PASSWORD_SET"] = bool(configuration.get("EMAIL_HOST_PASSWORD"))
        for key in SMTP_TEST_RESULT_KEYS:
            data[key] = configuration.get(key, "") or ""
        return data

    @cache_response(60 * 60 * 2, user=False)
    def get(self, request):
        return Response(self._response_data(), status=status.HTTP_200_OK)

    @invalidate_cache(path="/api/instances/smtp/", user=False, multiple=True)
    @invalidate_cache(path="/api/instances/configurations/", user=False)
    @invalidate_cache(path="/api/instances/", user=False)
    def patch(self, request):
        updates = {}
        for key in SMTP_CONFIG_KEYS:
            if key not in request.data:
                continue
            value = request.data.get(key)
            if key in ("ENABLE_SMTP", "EMAIL_USE_TLS", "EMAIL_USE_SSL"):
                value = "1" if _as_bool(value) else "0"
            elif key == "EMAIL_PORT":
                try:
                    port = int(value)
                except (TypeError, ValueError):
                    return Response({"error": "SMTP port must be a number"}, status=status.HTTP_400_BAD_REQUEST)
                if port < 1 or port > 65535:
                    return Response(
                        {"error": "SMTP port must be between 1 and 65535"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                value = str(port)
            elif key == "EMAIL_TIMEOUT":
                try:
                    timeout = int(value)
                except (TypeError, ValueError):
                    return Response({"error": "SMTP timeout must be a number"}, status=status.HTTP_400_BAD_REQUEST)
                if timeout < 1 or timeout > 300:
                    return Response(
                        {"error": "SMTP timeout must be between 1 and 300 seconds"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                value = str(timeout)
            else:
                value = "" if value is None else str(value).strip()
            updates[key] = value

        candidate = get_smtp_configuration()
        candidate_overrides = {
            key: value for key, value in updates.items() if not (key == "EMAIL_HOST_PASSWORD" and not value)
        }
        candidate.update(candidate_overrides)
        # Enabling the feature is not a connection change. The settings form is
        # hidden until SMTP is enabled, so validating here would make it
        # impossible to enter the connection details on a fresh instance.
        # Connection changes and explicit test emails still validate.
        if any(key in request.data for key in SMTP_CONNECTION_KEYS) and _as_bool(candidate.get("ENABLE_SMTP")):
            try:
                validate_smtp_connection(candidate_overrides)
            except SMTPConfigurationError as error:
                return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        for key, value in updates.items():
            instance_configuration, _ = InstanceConfiguration.objects.get_or_create(
                key=key,
                defaults={"category": "SMTP", "is_encrypted": key == "EMAIL_HOST_PASSWORD"},
            )
            instance_configuration.value = encrypt_data(value) if key == "EMAIL_HOST_PASSWORD" else value
            instance_configuration.save(update_fields=["value", "updated_at"])

        if updates:
            _clear_email_test_result()

        return Response(self._response_data(), status=status.HTTP_200_OK)


class DisableEmailFeatureEndpoint(BaseAPIView):
    permission_classes = [InstanceAdminPermission]

    @invalidate_cache(path="/api/instances/smtp/", user=False, multiple=True)
    @invalidate_cache(path="/api/instances/", user=False)
    def delete(self, request):
        try:
            InstanceConfiguration.objects.filter(Q(key__in=[*SMTP_CONFIG_KEYS, *SMTP_TEST_RESULT_KEYS])).update(
                value=Case(
                    When(key="ENABLE_SMTP", then=Value("0")),
                    When(key="EMAIL_PORT", then=Value("587")),
                    When(key="EMAIL_USE_TLS", then=Value("1")),
                    When(key="EMAIL_USE_SSL", then=Value("0")),
                    When(key="EMAIL_TIMEOUT", then=Value("10")),
                    default=Value(""),
                )
            )
            return Response(status=status.HTTP_200_OK)
        except Exception:
            return Response(
                {"error": "Failed to disable email configuration"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class EmailCredentialCheckEndpoint(BaseAPIView):
    """Queue the admin test email and expose its persisted result."""

    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        configuration = get_smtp_configuration()
        state = str(configuration.get("EMAIL_LAST_TEST_STATUS") or "").strip() or "idle"
        return Response(
            {
                "state": state,
                "status": state,
                "message": configuration.get("EMAIL_LAST_TEST_MESSAGE") or "",
                "at": configuration.get("EMAIL_LAST_TEST_AT") or "",
            },
            status=status.HTTP_200_OK,
        )

    @invalidate_cache(path="/api/instances/smtp/", user=False, multiple=True)
    def post(self, request):
        receiver_email = str(request.data.get("receiver_email", "")).strip()
        if not receiver_email or "@" not in receiver_email:
            return Response(
                {"error": "A valid receiver email is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        configuration = get_smtp_configuration()
        if not _as_bool(configuration.get("ENABLE_SMTP")):
            _set_email_test_result("failed", "SMTP is disabled")
            return Response({"error": "SMTP is disabled"}, status=status.HTTP_400_BAD_REQUEST)

        _set_email_test_result("queued", "Test email queued for delivery")
        send_test_email.delay(receiver_email)
        return Response(
            {"state": "queued", "status": "queued", "message": "Test email queued for delivery"},
            status=status.HTTP_202_ACCEPTED,
        )


def _delivery_log_state(log):
    if log.sent_at:
        return "delivered"
    if log.attempts:
        return "failed"
    return "pending"


def _delivery_log_data(log, detail=False):
    data = {
        "id": str(log.pk),
        "receiver_email": log.receiver.email if log.receiver_id else "",
        "entity_name": log.entity_name,
        "entity_identifier": str(log.entity_identifier) if log.entity_identifier else None,
        "entity": log.entity,
        "state": _delivery_log_state(log),
        "attempts": log.attempts,
        "last_error": log.last_error,
        "next_retry_at": log.next_retry_at,
        "processed_at": log.processed_at,
        "sent_at": log.sent_at,
        "created_at": log.created_at,
    }
    if detail:
        data["data"] = log.data
        data["old_value"] = log.old_value
        data["new_value"] = log.new_value
    return data


class EmailDeliveryLogEndpoint(BaseAPIView):
    """Recent delivery attempts for the admin delivery panel."""

    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        queryset = EmailNotificationLog.objects.select_related("receiver").order_by("-created_at")
        email = str(request.query_params.get("email", "")).strip()
        state = str(request.query_params.get("state", "")).strip()
        entity_name = str(request.query_params.get("entity_name", "")).strip()
        if email:
            queryset = queryset.filter(receiver__email__icontains=email)
        if entity_name:
            queryset = queryset.filter(entity_name=entity_name)
        if state == "delivered":
            queryset = queryset.filter(sent_at__isnull=False)
        elif state == "failed":
            queryset = queryset.filter(sent_at__isnull=True, attempts__gt=0)
        elif state == "pending":
            queryset = queryset.filter(sent_at__isnull=True, attempts=0)
        return Response([_delivery_log_data(log) for log in queryset[:100]], status=status.HTTP_200_OK)


class EmailDeliveryLogDetailEndpoint(BaseAPIView):
    permission_classes = [InstanceAdminPermission]

    def get(self, request, pk):
        log = EmailNotificationLog.objects.select_related("receiver").filter(pk=pk).first()
        if log is None:
            return Response({"error": "Delivery log not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_delivery_log_data(log, detail=True), status=status.HTTP_200_OK)


class EmailSuppressionEndpoint(BaseAPIView):
    """Basic bounce handling: list and manage suppressed recipients."""

    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        suppressions = EmailSuppression.objects.filter(is_active=True).values("id", "email", "reason", "created_at")
        return Response(list(suppressions), status=status.HTTP_200_OK)

    def post(self, request):
        email = str(request.data.get("email", "")).strip()
        if not email or "@" not in email:
            return Response({"error": "A valid email is required"}, status=status.HTTP_400_BAD_REQUEST)
        suppress_email(email, request.data.get("reason", "Suppressed by administrator"))
        return Response({"message": "Email address suppressed"}, status=status.HTTP_200_OK)

    def delete(self, request):
        email = str(request.data.get("email", "")).strip()
        if not email:
            return Response({"error": "A valid email is required"}, status=status.HTTP_400_BAD_REQUEST)
        EmailSuppression.objects.filter(email__iexact=email).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
