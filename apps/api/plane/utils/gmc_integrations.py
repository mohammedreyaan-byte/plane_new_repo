# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Configuration, signature verification and provider API helpers for GMC integrations.

All credentials are read from environment variables/instance configuration.  No
account, repository, channel or webhook payload is hardcoded.  Network calls use
an explicit host allow-list and never follow redirects.
"""

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode, urlparse

import requests

GITHUB_API = "https://api.github.com"
GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
SLACK_AUTHORIZE = "https://slack.com/oauth/v2/authorize"
SLACK_API = "https://slack.com/api"
DEFAULT_GITLAB_HOST = "https://gitlab.com"

GITHUB_SCOPES = ["repo", "read:user", "read:org"]
GITLAB_SCOPES = ["read_api", "read_user"]
SLACK_SCOPES = [
    "channels:read",
    "groups:read",
    "chat:write",
    "users:read",
    "links:read",
]


class IntegrationConfigurationError(Exception):
    """Raised when a provider is not configured with environment credentials."""


class ProviderAPIError(Exception):
    """Raised when a provider API rejects a request."""


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


def gitlab_host() -> str:
    return _env("GITLAB_HOST", DEFAULT_GITLAB_HOST).rstrip("/")


def jira_allowed_hosts() -> List[str]:
    return [host.strip().lower() for host in _env("JIRA_ALLOWED_HOSTS").split(",") if host.strip()]


def public_callback_url(provider: str) -> str:
    configured = _env(f"{provider.upper()}_OAUTH_REDIRECT_URI") or _env("GMC_OAUTH_REDIRECT_URI")
    if configured:
        return configured
    base = _env("PUBLIC_BASE_URL").rstrip("/")
    if not base:
        raise IntegrationConfigurationError("PUBLIC_BASE_URL is not configured")
    return f"{base}/api/integrations/{provider}/callback/"


def provider_config(provider: str) -> Dict[str, Any]:
    provider = provider.lower()
    if provider == "github":
        config = {
            "client_id": _env("GITHUB_CLIENT_ID"),
            "client_secret": _env("GITHUB_CLIENT_SECRET"),
            "webhook_secret": _env("GITHUB_WEBHOOK_SECRET"),
            "app_name": _env("GITHUB_APP_NAME", "plane"),
            "authorize_url": GITHUB_AUTHORIZE,
            "token_url": GITHUB_TOKEN,
            "api_url": GITHUB_API,
            "scopes": GITHUB_SCOPES,
        }
    elif provider == "gitlab":
        config = {
            "client_id": _env("GITLAB_CLIENT_ID"),
            "client_secret": _env("GITLAB_CLIENT_SECRET"),
            "webhook_secret": _env("GITLAB_WEBHOOK_SECRET"),
            "authorize_url": f"{gitlab_host()}/oauth/authorize",
            "token_url": f"{gitlab_host()}/oauth/token",
            "api_url": f"{gitlab_host()}/api/v4",
            "host": gitlab_host(),
            "scopes": GITLAB_SCOPES,
        }
    elif provider == "slack":
        config = {
            "client_id": _env("SLACK_CLIENT_ID"),
            "client_secret": _env("SLACK_CLIENT_SECRET"),
            "webhook_secret": _env("SLACK_SIGNING_SECRET"),
            "authorize_url": SLACK_AUTHORIZE,
            "token_url": f"{SLACK_API}/oauth.v2.access",
            "api_url": SLACK_API,
            "app_id": _env("SLACK_APP_ID"),
            "scopes": SLACK_SCOPES,
        }
    else:
        raise IntegrationConfigurationError("Unknown integration provider")
    return config


def is_provider_configured(provider: str) -> bool:
    try:
        config = provider_config(provider)
    except IntegrationConfigurationError:
        return False
    return bool(config.get("client_id") and config.get("client_secret"))


def oauth_authorize_url(provider: str, state: str) -> str:
    config = provider_config(provider)
    if not config.get("client_id"):
        raise IntegrationConfigurationError(f"{provider} OAuth is not configured")
    params = {
        "client_id": config["client_id"],
        "redirect_uri": public_callback_url(provider),
        "response_type": "code",
        "state": state,
    }
    if provider == "slack":
        params["scope"] = ",".join(SLACK_SCOPES)
    elif provider == "github":
        params["scope"] = " ".join(GITHUB_SCOPES)
    else:
        params["scope"] = " ".join(GITLAB_SCOPES)
    return f"{config['authorize_url']}?{urlencode(params)}"


def _validate_url(url: str, allowed_hosts: Iterable[str]) -> None:
    parsed = urlparse(url)
    allowed = {host.lower() for host in allowed_hosts if host}
    if parsed.scheme not in ("https", "http") or parsed.hostname is None:
        raise ProviderAPIError("Provider URL is not valid")
    if parsed.hostname.lower() not in allowed:
        raise ProviderAPIError("Provider host is not allow-listed")
    if parsed.scheme == "http" and _env("ALLOW_INSECURE_PROVIDER_HTTP", "false").lower() != "true":
        raise ProviderAPIError("Provider URL must use HTTPS")


def safe_request(method: str, url: str, allowed_hosts: Iterable[str], **kwargs: Any) -> requests.Response:
    """Perform a provider request without redirects against an allow-listed host."""

    _validate_url(url, allowed_hosts)
    kwargs.setdefault("timeout", 20)
    kwargs["allow_redirects"] = False
    response = requests.request(method, url, **kwargs)
    if response.status_code >= 400:
        raise ProviderAPIError(f"Provider request failed with status {response.status_code}")
    return response


def exchange_code_for_token(provider: str, code: str) -> Dict[str, Any]:
    config = provider_config(provider)
    if not config.get("client_id") or not config.get("client_secret"):
        raise IntegrationConfigurationError(f"{provider} OAuth is not configured")
    host = urlparse(config["token_url"]).hostname
    if not host:
        raise IntegrationConfigurationError("Provider token URL is not valid")
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "code": code,
        "redirect_uri": public_callback_url(provider),
    }
    headers = {"Accept": "application/json"}
    response = safe_request("POST", config["token_url"], [host], data=data, headers=headers)
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderAPIError("Provider returned an invalid token response") from exc
    if provider == "slack" and not payload.get("ok"):
        raise ProviderAPIError("Slack authorization failed")
    if payload.get("error"):
        raise ProviderAPIError("Provider authorization failed")
    return payload


def fetch_provider_account(provider: str, token: str) -> Dict[str, str]:
    if provider == "github":
        response = safe_request(
            "GET",
            f"{GITHUB_API}/user",
            [urlparse(GITHUB_API).hostname],
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        data = response.json()
        return {"id": str(data["id"]), "name": data.get("login") or data.get("name") or str(data["id"])}
    if provider == "gitlab":
        api_url = f"{gitlab_host()}/api/v4"
        response = safe_request(
            "GET",
            f"{api_url}/user",
            [urlparse(gitlab_host()).hostname],
            headers={"Authorization": f"Bearer {token}"},
        )
        data = response.json()
        return {"id": str(data["id"]), "name": data.get("username") or data.get("name") or str(data["id"])}
    if provider == "slack":
        # Account details are supplied by the OAuth response and stored by the callback view.
        return {}
    raise IntegrationConfigurationError("Unknown integration provider")


def fetch_repositories(provider: str, token: str) -> List[Dict[str, Any]]:
    """Return repository metadata from the provider API."""

    if provider == "github":
        response = safe_request(
            "GET",
            f"{GITHUB_API}/user/repos",
            [urlparse(GITHUB_API).hostname],
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            params={"per_page": 100, "affiliation": "owner,collaborator,organization_member"},
        )
        return [
            {
                "external_id": str(repo["id"]),
                "full_name": repo["full_name"],
                "url": repo.get("html_url", ""),
                "metadata": {"private": repo.get("private", False), "default_branch": repo.get("default_branch", "")},
            }
            for repo in response.json()
        ]
    if provider == "gitlab":
        api_url = f"{gitlab_host()}/api/v4"
        response = safe_request(
            "GET",
            f"{api_url}/projects",
            [urlparse(gitlab_host()).hostname],
            headers={"Authorization": f"Bearer {token}"},
            params={"membership": "true", "per_page": 100, "simple": "true"},
        )
        return [
            {
                "external_id": str(project["id"]),
                "full_name": project.get("path_with_namespace") or project.get("name"),
                "url": project.get("web_url", ""),
                "metadata": {"visibility": project.get("visibility", "")},
            }
            for project in response.json()
        ]
    raise IntegrationConfigurationError("Repository listing is only available for GitHub and GitLab")


def fetch_slack_channels(token: str) -> List[Dict[str, Any]]:
    response = safe_request(
        "GET",
        f"{SLACK_API}/conversations.list",
        [urlparse(SLACK_API).hostname],
        headers={"Authorization": f"Bearer {token}"},
        params={"types": "public_channel,private_channel", "limit": 200, "exclude_archived": "true"},
    )
    payload = response.json()
    if not payload.get("ok"):
        raise ProviderAPIError("Slack channel listing failed")
    return [
        {
            "channel_id": channel["id"],
            "channel_name": channel.get("name", channel["id"]),
            "member_count": int(channel.get("num_members") or 0),
        }
        for channel in payload.get("channels", [])
    ]


def post_slack_message(token: str, channel: str, text: str, blocks: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"channel": channel, "text": text}
    if blocks:
        body["blocks"] = blocks
    response = safe_request(
        "POST",
        f"{SLACK_API}/chat.postMessage",
        [urlparse(SLACK_API).hostname],
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        data=json.dumps(body),
    )
    payload = response.json()
    if not payload.get("ok"):
        raise ProviderAPIError(payload.get("error", "Slack message failed"))
    return payload


def verify_webhook_signature(provider: str, raw_body: bytes, headers: Dict[str, str], secret: str) -> bool:
    """Verify provider webhook signatures with constant-time comparison."""

    provider = provider.lower()
    headers = {key.lower(): value for key, value in headers.items()}
    if not secret:
        return False
    if provider == "github":
        signature = headers.get("x-hub-signature-256", "")
        if not signature.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    if provider == "gitlab":
        token = headers.get("x-gitlab-token", "")
        return bool(token) and hmac.compare_digest(token, secret)
    if provider == "slack":
        timestamp = headers.get("x-slack-request-timestamp", "")
        signature = headers.get("x-slack-signature", "")
        if not timestamp or not signature:
            return False
        try:
            if abs(time.time() - int(timestamp)) > 300:
                return False
        except ValueError:
            return False
        base = f"v0:{timestamp}:".encode() + raw_body
        expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    return False


def fetch_jira_issues(site_url: str, email: str, api_token: str, project_key: str) -> List[Dict[str, Any]]:
    allowed_hosts = jira_allowed_hosts()
    host = urlparse(site_url).hostname
    if not host or host.lower() not in allowed_hosts:
        raise ProviderAPIError("Jira host is not allow-listed")
    issues: List[Dict[str, Any]] = []
    start_at = 0
    max_results = 100
    while True:
        response = safe_request(
            "GET",
            f"{site_url.rstrip('/')}/rest/api/3/search",
            [host],
            auth=(email, api_token),
            params={
                "jql": f"project = {project_key} ORDER BY created ASC",
                "startAt": start_at,
                "maxResults": max_results,
                "fields": "summary,description,status,priority,assignee,labels",
            },
        )
        payload = response.json()
        issues.extend(payload.get("issues", []))
        total = int(payload.get("total", 0))
        start_at += len(payload.get("issues", []))
        if start_at >= total or not payload.get("issues"):
            break
    return issues


def fetch_github_issues(token: str, owner: str, repo: str, include_issues: bool, include_prs: bool) -> List[Dict[str, Any]]:
    host = urlparse(GITHUB_API).hostname
    assert host is not None
    records: List[Dict[str, Any]] = []
    for state in ("open", "closed"):
        response = safe_request(
            "GET",
            f"{GITHUB_API}/repos/{owner}/{repo}/issues",
            [host],
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            params={"state": state, "per_page": 100, "sort": "created", "direction": "asc"},
        )
        for item in response.json():
            is_pr = "pull_request" in item
            if (is_pr and not include_prs) or (not is_pr and not include_issues):
                continue
            records.append(item)
    return records
