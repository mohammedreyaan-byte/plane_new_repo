# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Opt-in event sink for PLN-026 credential-free integration E2E tests.

The sink is disabled unless the process is explicitly marked as local/staging
and the Django settings module is not a production module. It forwards only
non-sensitive delivery metadata to a configured mock endpoint; it never sends
provider tokens, webhook secrets or user passwords.
"""

import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

PRODUCTION_VALUES = {"prod", "production", "live"}
SAFE_TARGET_VALUES = {"local", "staging"}
TARGET_ENV_VARS = ("PLANE_ENV", "DEPLOY_ENV", "APP_ENV", "ENVIRONMENT", "E2E_ENV")
SINK_ENV = "E2E_EVENT_SINK_URL"
SAFETY_OPT_IN_ENV = "E2E_ALLOW_LOCAL_STAGING"
TARGET_ENV_NAME = "PLANE_E2E_ENV"
ALLOWED_PATHS = {"events": "/events", "messages": "/messages"}
TIMEOUT_SECONDS = 2


def _settings_module() -> str:
    from django.conf import settings

    return str(os.environ.get("DJANGO_SETTINGS_MODULE") or getattr(settings, "SETTINGS_MODULE", "")).lower()


def is_production_target() -> bool:
    """True for any production settings module or production environment marker."""

    settings_module = _settings_module()
    if any(f".{value}" in settings_module or settings_module.endswith(value) for value in PRODUCTION_VALUES):
        return True
    return any(os.environ.get(name, "").strip().lower() in PRODUCTION_VALUES for name in TARGET_ENV_VARS)


def has_explicit_safe_environment() -> bool:
    """True only for an explicit local/staging test target."""

    opt_in = os.environ.get(SAFETY_OPT_IN_ENV, "").strip().lower()
    if opt_in in {"1", "true", "yes", "on"}:
        return True
    return os.environ.get(TARGET_ENV_NAME, "").strip().lower() in SAFE_TARGET_VALUES


def event_sink_url() -> Optional[str]:
    """Return the validated sink URL, or None when the sink is disabled."""

    if is_production_target() or not has_explicit_safe_environment():
        return None
    raw = os.environ.get(SINK_ENV, "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme != "http" or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    return (
        f"{parsed.scheme}://{parsed.hostname}{':' + str(parsed.port) if parsed.port else ''}{parsed.path.rstrip('/')}"
    )


def e2e_event_sink_enabled() -> bool:
    return event_sink_url() is not None


def record_e2e_event(kind: str, payload: Dict[str, Any]) -> bool:
    """Best-effort delivery of a test-only event to the configured mock."""

    path = ALLOWED_PATHS.get(kind)
    base_url = event_sink_url()
    if not path or not base_url:
        return False
    try:
        response = requests.post(f"{base_url}{path}", json=payload, timeout=TIMEOUT_SECONDS)
        return 200 <= response.status_code < 300
    except requests.RequestException:
        # The mock must never change application behaviour; a missing record
        # makes the E2E assertion fail instead of masking a product defect.
        return False
