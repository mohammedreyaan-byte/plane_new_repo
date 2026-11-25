# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for the production GMC feature APIs."""

import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from plane.db.models import (
    AutomationRule,
    ExternalAccountIntegration,
    ExternalRepository,
    ExternalWebhookEvent,
    Importer,
    Initiative,
    OAuthAuthorizationRequest,
    SlackChannelSubscription,
    State,
    User,
)
from plane.license.utils.encryption import encrypt_data

pytestmark = pytest.mark.contract

ADMIN, MEMBER = 20, 15


@pytest.fixture
def gmc_context(db, workspace, create_user):
    from plane.db.models import Project, ProjectMember

    project = Project.objects.create(
        name="GMC Review", identifier="GMC", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(workspace=workspace, project=project, member=create_user, role=ADMIN)
    State.objects.create(
        name="Todo",
        project=project,
        workspace=workspace,
        group="unstarted",
        color="#000000",
        default=True,
    )
    member_suffix = uuid4().hex[:8]
    member = User.objects.create(
        email=f"member-{member_suffix}@plane.so",
        username=f"member_{member_suffix}",
        first_name="Project",
        last_name="Member",
    )
    from plane.db.models import WorkspaceMember

    WorkspaceMember.objects.create(workspace=workspace, member=member, role=MEMBER)
    ProjectMember.objects.create(workspace=workspace, project=project, member=member, role=MEMBER)
    admin_client = APIClient()
    admin_client.force_authenticate(user=create_user)
    member_client = APIClient()
    member_client.force_authenticate(user=member)
    return {
        "workspace": workspace,
        "project": project,
        "admin": create_user,
        "member": member,
        "admin_client": admin_client,
        "member_client": member_client,
    }


def _url(name, **kwargs):
    return reverse(name, kwargs=kwargs)


def test_provider_list_and_integration_management_permissions(gmc_context):
    workspace = gmc_context["workspace"]
    admin_client = gmc_context["admin_client"]
    member_client = gmc_context["member_client"]

    response = admin_client.get(_url("app-integrations", slug=workspace.slug))
    assert response.status_code == 200
    assert {item["provider"] for item in response.data} == {"github", "gitlab", "slack"}
    assert all("client_secret" not in item for item in response.data)

    list_url = _url("workspace-integrations", slug=workspace.slug)
    assert admin_client.get(list_url).status_code == 200
    assert member_client.get(list_url).status_code == 403


def test_initiative_crud_uses_real_project_records(gmc_context):
    client = gmc_context["admin_client"]
    kwargs = {"slug": gmc_context["workspace"].slug, "project_id": gmc_context["project"].id}
    list_url = _url("initiatives", **kwargs)

    created = client.post(
        list_url,
        {"name": "Q4 Delivery", "description": "Production rollout", "status": "active", "owner": gmc_context["admin"].id},
        format="json",
    )
    assert created.status_code == 201, created.data
    initiative_id = created.data["id"]

    listed = client.get(list_url)
    assert listed.status_code == 200
    assert [item["name"] for item in listed.data] == ["Q4 Delivery"]

    detail_url = _url("initiative-detail", **kwargs, pk=initiative_id)
    updated = client.patch(detail_url, {"status": "completed"}, format="json")
    assert updated.status_code == 200
    assert updated.data["progress"] == 100
    assert client.delete(detail_url).status_code == 204
    assert Initiative.objects.count() == 0


def test_automation_rule_validation_and_crud(gmc_context):
    client = gmc_context["admin_client"]
    kwargs = {"slug": gmc_context["workspace"].slug, "project_id": gmc_context["project"].id}
    list_url = _url("automation-rules", **kwargs)

    invalid = client.post(
        list_url,
        {
            "name": "Broken rule",
            "trigger": "created",
            "conditions": [],
            "actions": [{"type": "drop_database", "value": "all"}],
        },
        format="json",
    )
    assert invalid.status_code == 400

    created = client.post(
        list_url,
        {
            "name": "Label new work",
            "trigger": "created",
            "conditions": [{"field": "priority", "operator": "is", "value": "high"}],
            "actions": [{"type": "add_comment", "value": "Thanks, this is high priority."}],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    assert AutomationRule.objects.filter(project=gmc_context["project"]).count() == 1

    detail_url = _url("automation-rule-detail", **kwargs, pk=created.data["id"])
    patched = client.patch(detail_url, {"is_active": False}, format="json")
    assert patched.status_code == 200
    assert patched.data["is_active"] is False

    assert gmc_context["member_client"].post(
        list_url,
        {"name": "Not allowed", "trigger": "created", "conditions": [], "actions": []},
        format="json",
    ).status_code == 403

    options = client.get(_url("automation-options", **kwargs))
    assert options.status_code == 200
    assert {"value": "high", "label": "High"} in options.data["priorities"]
    assert isinstance(options.data["types"], list)


def test_csv_import_creates_encrypted_job_and_hides_secrets(gmc_context):
    client = gmc_context["admin_client"]
    url = _url("imports", slug=gmc_context["workspace"].slug, project_id=gmc_context["project"].id)
    upload = SimpleUploadedFile("work-items.csv", b"Title,Description\nCSV item,From real upload\n", content_type="text/csv")

    with patch("plane.app.views.gmc_features.process_import_job.delay") as delay:
        response = client.post(url, {"service": "csv", "file": upload}, format="multipart")

    assert response.status_code == 202, response.data
    delay.assert_called_once()
    importer = Importer.objects.get(pk=response.data["id"])
    assert importer.status == "queued"
    assert importer.file_name == "work-items.csv"
    assert importer.config["csv_content"] != "Title,Description\nCSV item,From real upload\n"
    assert response.data["config"]["csv_content"] == "********"
    assert client.get(url).status_code == 200
    assert client.get(_url("import-detail", slug=gmc_context["workspace"].slug, project_id=gmc_context["project"].id, pk=importer.id)).status_code == 200


def test_slack_settings_endpoint_reads_and_persists_real_channels(gmc_context):
    client = gmc_context["admin_client"]
    workspace = gmc_context["workspace"]
    integration = ExternalAccountIntegration.objects.create(
        workspace=workspace,
        provider="slack",
        provider_account_id="T-REAL",
        account_name="Company Slack",
    )
    integration.set_access_token("xoxb-real-token")
    integration.save()
    SlackChannelSubscription.objects.create(
        workspace=workspace,
        integration=integration,
        channel_id="C-REAL",
        channel_name="engineering",
        member_count=12,
        events={"work_item.created": True},
        is_default=True,
    )

    url = _url("slack-integration", slug=workspace.slug)
    response = client.get(url)
    assert response.status_code == 200
    assert response.data["connected"] is True
    assert response.data["team_name"] == "Company Slack"
    assert response.data["channels"][0]["channel_name"] == "engineering"
    assert "xoxb-real-token" not in json.dumps(response.data, default=str)

    patched = client.patch(
        url,
        {"default_channel_id": "C-REAL", "events": {"work_item.created": True, "work_item.state_changed": True}},
        format="json",
    )
    assert patched.status_code == 200
    subscription = SlackChannelSubscription.objects.get(integration=integration)
    assert subscription.events["work_item.state_changed"] is True

    assert gmc_context["member_client"].get(url).status_code == 403


def test_oauth_callback_creates_encrypted_integration_and_repositories(gmc_context, monkeypatch):
    workspace = gmc_context["workspace"]
    authorization = OAuthAuthorizationRequest.objects.create(
        workspace=workspace,
        user=gmc_context["admin"],
        provider="github",
        scopes=["repo", "read:user"],
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://plane.company.example")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")

    authorize = gmc_context["admin_client"].post(
        _url("integration-oauth-authorize", slug=workspace.slug, provider="github"), {}
    )
    assert authorize.status_code == 200
    assert "github.com/login/oauth/authorize" in authorize.data["authorize_url"]
    OAuthAuthorizationRequest.objects.filter(pk=authorization.pk).delete()

    state = authorize.data["state"]
    with patch(
        "plane.app.views.gmc_features.exchange_code_for_token",
        return_value={"access_token": "gh-real-token", "scope": "repo,read:user"},
    ), patch(
        "plane.app.views.gmc_features.fetch_provider_account",
        return_value={"id": "918273", "name": "company-github"},
    ), patch(
        "plane.app.views.gmc_features.fetch_repositories",
        return_value=[
            {
                "external_id": "42",
                "full_name": "company/private-repo",
                "url": "https://github.com/company/private-repo",
                "metadata": {"private": True},
            }
        ],
    ):
        callback = APIClient().get(
            _url("integration-oauth-callback", provider="github"), {"code": "real-code", "state": state}
        )

    assert callback.status_code == 200
    integration = ExternalAccountIntegration.objects.get(workspace=workspace, provider="github")
    assert integration.get_access_token() == "gh-real-token"
    assert integration.access_token != "gh-real-token"
    assert ExternalRepository.objects.filter(integration=integration, full_name="company/private-repo").exists()
    assert OAuthAuthorizationRequest.objects.get(state=state).used_at is not None


def test_webhook_rejects_bad_signatures_and_links_verified_events(gmc_context):
    workspace = gmc_context["workspace"]
    integration = ExternalAccountIntegration.objects.create(
        workspace=workspace,
        provider="github",
        provider_account_id="918273",
        account_name="company-github",
    )
    integration.set_webhook_secret("webhook-secret")
    integration.save()
    url = _url("provider-webhook", provider="github") + f"?workspace={workspace.slug}"
    payload = {"action": "closed", "body": "Fixes GMC-7", "html_url": "https://github.com/company/repo/pull/7"}
    raw = json.dumps(payload)
    signature = "sha256=" + hmac.new(b"webhook-secret", raw.encode(), hashlib.sha256).hexdigest()

    bad = APIClient().post(
        url,
        data=raw,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=bad",
        HTTP_X_GITHUB_EVENT="issues",
        HTTP_X_GITHUB_DELIVERY="delivery-bad",
    )
    assert bad.status_code == 401

    with patch("plane.app.views.gmc_features.process_webhook_event.delay") as delay:
        accepted = APIClient().post(
            url,
            data=raw,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
            HTTP_X_GITHUB_EVENT="issues",
            HTTP_X_GITHUB_DELIVERY="delivery-valid",
        )
    assert accepted.status_code == 202, accepted.data
    delay.assert_called_once()
    event = ExternalWebhookEvent.objects.get(delivery_id="delivery-valid")
    assert event.signature_verified is True
    assert event.payload == payload

    events_url = _url("integration-webhook-events", slug=workspace.slug, provider="github")
    assert gmc_context["admin_client"].get(events_url).status_code == 200
    assert gmc_context["member_client"].get(events_url).status_code == 403


def test_repository_sync_and_toggle_are_admin_only(gmc_context):
    workspace = gmc_context["workspace"]
    integration = ExternalAccountIntegration.objects.create(
        workspace=workspace,
        provider="gitlab",
        provider_account_id="55",
        account_name="company-gitlab",
    )
    integration.set_access_token("glpat-real-token")
    integration.save()
    repository = ExternalRepository.objects.create(
        workspace=workspace,
        integration=integration,
        provider="gitlab",
        external_id="99",
        full_name="company/project",
        url="https://gitlab.com/company/project",
    )
    list_url = _url("integration-repositories", slug=workspace.slug, provider="gitlab")

    assert gmc_context["member_client"].get(list_url).status_code == 403
    with patch("plane.app.views.gmc_features.fetch_repositories", return_value=[]) as fetch:
        assert gmc_context["admin_client"].post(list_url, {}, format="json").status_code == 200
        fetch.assert_called_once_with("gitlab", "glpat-real-token")

    detail_url = _url(
        "integration-repository-detail", slug=workspace.slug, provider="gitlab", repository_id=repository.id
    )
    patched = gmc_context["admin_client"].patch(detail_url, {"is_sync_enabled": False}, format="json")
    assert patched.status_code == 200
    repository.refresh_from_db()
    assert repository.is_sync_enabled is False


def test_integration_secret_helpers_round_trip_without_plaintext_storage(gmc_context):
    integration = ExternalAccountIntegration.objects.create(
        workspace=gmc_context["workspace"],
        provider="slack",
        provider_account_id="T-ROUNDTRIP",
        account_name="Roundtrip",
    )
    integration.set_access_token("xoxb-roundtrip")
    integration.set_webhook_secret("signing-roundtrip")
    integration.save()
    raw = integration.__dict__
    assert "xoxb-roundtrip" not in str(raw)
    assert "signing-roundtrip" not in str(raw)
    assert integration.get_access_token() == "xoxb-roundtrip"
    assert integration.get_webhook_secret() == "signing-roundtrip"
    assert encrypt_data("") == ""
