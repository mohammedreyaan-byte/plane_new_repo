# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import os

# Django imports
from django.conf import settings

# Module imports
from plane.license.models import InstanceConfiguration
from plane.license.utils.encryption import decrypt_data


# Helper function to return value from the passed key
def get_configuration_value(keys):
    environment_list = []
    if settings.SKIP_ENV_VAR:
        # Get the configurations
        instance_configuration = InstanceConfiguration.objects.values("key", "value", "is_encrypted")

        for key in keys:
            for item in instance_configuration:
                if key.get("key") == item.get("key"):
                    if item.get("is_encrypted", False):
                        environment_list.append(decrypt_data(item.get("value")))
                    else:
                        environment_list.append(item.get("value"))

                    break
            else:
                environment_list.append(key.get("default"))
    else:
        # Get the configuration from os
        for key in keys:
            environment_list.append(os.environ.get(key.get("key"), key.get("default")))

    return tuple(environment_list)


def _as_bool(value):
    return str(value if value is not None else "").strip().lower() in ("1", "true", "yes", "on")


def get_smtp_configuration(overrides=None):
    """Return the effective SMTP configuration with encrypted values decrypted.

    The database configuration remains authoritative when SKIP_ENV_VAR is enabled;
    Django settings provide the environment-variable fallback.
    """

    keys = [
        {"key": "ENABLE_SMTP", "default": getattr(settings, "ENABLE_SMTP", "0")},
        {"key": "EMAIL_HOST", "default": getattr(settings, "EMAIL_HOST", "")},
        {"key": "EMAIL_HOST_USER", "default": getattr(settings, "EMAIL_HOST_USER", "")},
        {
            "key": "EMAIL_HOST_PASSWORD",
            "default": getattr(settings, "EMAIL_HOST_PASSWORD", ""),
        },
        {"key": "EMAIL_PORT", "default": getattr(settings, "EMAIL_PORT", 587)},
        {"key": "EMAIL_USE_TLS", "default": getattr(settings, "EMAIL_USE_TLS", "1")},
        {"key": "EMAIL_USE_SSL", "default": getattr(settings, "EMAIL_USE_SSL", "0")},
        {"key": "EMAIL_FROM", "default": getattr(settings, "EMAIL_FROM", "")},
        {"key": "EMAIL_TIMEOUT", "default": getattr(settings, "EMAIL_TIMEOUT", 10)},
        {"key": "EMAIL_LAST_TEST_STATUS", "default": ""},
        {"key": "EMAIL_LAST_TEST_MESSAGE", "default": ""},
        {"key": "EMAIL_LAST_TEST_AT", "default": ""},
    ]
    values = get_configuration_value(keys)
    configuration = {
        "ENABLE_SMTP": values[0],
        "EMAIL_HOST": values[1],
        "EMAIL_HOST_USER": values[2],
        "EMAIL_HOST_PASSWORD": values[3],
        "EMAIL_PORT": values[4],
        "EMAIL_USE_TLS": values[5],
        "EMAIL_USE_SSL": values[6],
        "EMAIL_FROM": values[7],
        "EMAIL_TIMEOUT": values[8],
        "EMAIL_LAST_TEST_STATUS": values[9],
        "EMAIL_LAST_TEST_MESSAGE": values[10],
        "EMAIL_LAST_TEST_AT": values[11],
    }
    if overrides:
        configuration.update(overrides)
    return configuration


def is_smtp_enabled():
    return _as_bool(get_smtp_configuration().get("ENABLE_SMTP"))


def get_email_configuration():
    configuration = get_smtp_configuration()
    return (
        configuration["EMAIL_HOST"],
        configuration["EMAIL_HOST_USER"],
        configuration["EMAIL_HOST_PASSWORD"],
        configuration["EMAIL_PORT"],
        configuration["EMAIL_USE_TLS"],
        configuration["EMAIL_USE_SSL"],
        configuration["EMAIL_FROM"],
    )
