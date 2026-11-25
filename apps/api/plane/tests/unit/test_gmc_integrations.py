# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for provider configuration and webhook signature verification."""

import hashlib
import hmac
import time
from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from plane.utils.gmc_integrations import (
    IntegrationConfigurationError,
    ProviderAPIError,
    jira_allowed_hosts,
    oauth_authorize_url,
    public_callback_url,
    safe_request,
    verify_webhook_signature,
)

pytestmark = pytest.mark.unit


def test_github_signature_is_verified_with_constant_time_comparison():
    raw = b'{"action":"opened"}'
    secret = "webhook-secret"
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    assert verify_webhook_signature("github", raw, {"X-Hub-Signature-256": signature}, secret)
    assert not verify_webhook_signature("github", raw, {"x-hub-signature-256": signature}, "wrong-secret")
    assert not verify_webhook_signature("github", raw, {"x-hub-signature-256": "sha1=bad"}, secret)


def test_gitlab_signature_is_verified():
    assert verify_webhook_signature("gitlab", b"{}", {"X-Gitlab-Token": "token"}, "token")
    assert not verify_webhook_signature("gitlab", b"{}", {"x-gitlab-token": "token"}, "different")


def test_slack_signature_is_verified_and_rejects_stale_requests():
    raw = b'{"type":"event_callback"}'
    secret = "signing-secret"
    timestamp = str(int(time.time()))
    base = f"v0:{timestamp}:".encode() + raw
    signature = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    headers = {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature}

    assert verify_webhook_signature("slack", raw, headers, secret)
    stale_headers = {**headers, "X-Slack-Request-Timestamp": str(int(time.time()) - 600)}
    assert not verify_webhook_signature("slack", raw, stale_headers, secret)
    assert not verify_webhook_signature("slack", raw, headers, "")


@override_settings()
def test_oauth_url_uses_environment_configuration(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://plane.company.example")
    monkeypatch.delenv("GITHUB_OAUTH_REDIRECT_URI", raising=False)

    url = oauth_authorize_url("github", "state-value")

    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=client-id" in url
    assert "state=state-value" in url
    assert "redirect_uri=https%3A%2F%2Fplane.company.example%2Fapi%2Fintegrations%2Fgithub%2Fcallback%2F" in url
    assert public_callback_url("github").endswith("/api/integrations/github/callback/")


def test_oauth_url_requires_client_configuration(monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    with pytest.raises(IntegrationConfigurationError):
        oauth_authorize_url("github", "state-value")


def test_safe_request_blocks_non_allowlisted_and_insecure_urls(monkeypatch):
    monkeypatch.delenv("ALLOW_INSECURE_PROVIDER_HTTP", raising=False)
    with patch("plane.utils.gmc_integrations.requests.request") as request:
        with pytest.raises(ProviderAPIError):
            safe_request("GET", "https://evil.example.com/user", ["api.github.com"])
        with pytest.raises(ProviderAPIError):
            safe_request("GET", "http://api.github.com/user", ["api.github.com"])
        request.assert_not_called()

        response = Mock(status_code=200)
        request.return_value = response
        assert safe_request("GET", "https://api.github.com/user", ["api.github.com"]) is response
        assert request.call_args.kwargs["allow_redirects"] is False


def test_jira_hosts_are_allow_listed(monkeypatch):
    monkeypatch.setenv("JIRA_ALLOWED_HOSTS", "jira.company.example, other.example")
    assert jira_allowed_hosts() == ["jira.company.example", "other.example"]

    from plane.utils.gmc_integrations import fetch_jira_issues

    with patch("plane.utils.gmc_integrations.safe_request") as request:
        request.return_value.json.return_value = {"issues": [], "total": 0}
        with pytest.raises(ProviderAPIError):
            fetch_jira_issues("https://evil.example", "user@example.com", "token", "ABC")
        request.assert_not_called()

        assert fetch_jira_issues("https://jira.company.example", "user@example.com", "token", "ABC") == []
        request.assert_called_once()
