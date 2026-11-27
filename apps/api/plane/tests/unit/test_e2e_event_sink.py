# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for the PLN-026 opt-in event sink guard."""

from unittest.mock import Mock

import pytest

from plane.utils import e2e_event_sink

pytestmark = pytest.mark.unit


def _clear_sink_env(monkeypatch):
    for name in (
        e2e_event_sink.SINK_ENV,
        e2e_event_sink.SAFETY_OPT_IN_ENV,
        e2e_event_sink.TARGET_ENV_NAME,
        "PLANE_ENV",
        "DEPLOY_ENV",
        "APP_ENV",
        "ENVIRONMENT",
        "E2E_ENV",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.unit
def test_sink_is_disabled_without_explicit_safe_target(monkeypatch):
    _clear_sink_env(monkeypatch)
    monkeypatch.setenv(e2e_event_sink.SINK_ENV, "http://127.0.0.1:8787")

    assert e2e_event_sink.event_sink_url() is None


@pytest.mark.unit
def test_sink_is_disabled_when_any_production_marker_is_present(monkeypatch):
    _clear_sink_env(monkeypatch)
    monkeypatch.setenv(e2e_event_sink.SINK_ENV, "http://127.0.0.1:8787")
    monkeypatch.setenv(e2e_event_sink.SAFETY_OPT_IN_ENV, "1")
    monkeypatch.setenv("PLANE_ENV", "production")

    assert e2e_event_sink.event_sink_url() is None


@pytest.mark.unit
def test_sink_accepts_explicit_local_target(monkeypatch):
    _clear_sink_env(monkeypatch)
    monkeypatch.setenv(e2e_event_sink.SINK_ENV, "http://127.0.0.1:8787/")
    monkeypatch.setenv(e2e_event_sink.SAFETY_OPT_IN_ENV, "1")

    assert e2e_event_sink.event_sink_url() == "http://127.0.0.1:8787"


@pytest.mark.unit
def test_record_event_uses_only_allowlisted_mock_paths(monkeypatch):
    _clear_sink_env(monkeypatch)
    monkeypatch.setenv(e2e_event_sink.SINK_ENV, "http://127.0.0.1:8787")
    monkeypatch.setenv(e2e_event_sink.SAFETY_OPT_IN_ENV, "1")
    post = Mock(return_value=Mock(status_code=201))
    monkeypatch.setattr(e2e_event_sink.requests, "post", post)

    assert e2e_event_sink.record_e2e_event("events", {"delivery_id": "unit"}) is True
    assert post.call_args.args[0] == "http://127.0.0.1:8787/events"
    assert e2e_event_sink.record_e2e_event("../../admin", {}) is False
    assert post.call_count == 1
