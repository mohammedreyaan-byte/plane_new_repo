# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Authorization contract tests for PLN-015 project isolation."""

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import ExternalAccountIntegration, WorkspaceMemberInvite
from plane.db.models.api import APIToken

pytestmark = pytest.mark.contract


def _issue_list_url(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/"


def _issue_detail_url(workspace, project, issue):
    return f"{_issue_list_url(workspace, project)}{issue.id}/"


def _v1_issue_list_url(workspace, project):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/issues/"


def test_workspace_member_without_project_membership_is_denied(isolation_context):
    response = isolation_context["outsider_client"].get(
        _issue_list_url(isolation_context["workspace"], isolation_context["project_a"])
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_issue_from_another_project_is_hidden(isolation_context):
    response = isolation_context["member_client"].get(
        _issue_detail_url(
            isolation_context["workspace"],
            isolation_context["project_a"],
            isolation_context["issue_b"],
        )
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_cross_workspace_project_id_is_hidden(isolation_context):
    response = isolation_context["owner_client"].get(
        _issue_list_url(isolation_context["workspace"], isolation_context["foreign_project"])
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_body_project_id_must_match_url(isolation_context):
    response = isolation_context["member_client"].post(
        _issue_list_url(isolation_context["workspace"], isolation_context["project_a"]),
        {"name": "Mismatched issue", "project_id": str(isolation_context["project_b"].id)},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "project_mismatch"


def test_restricted_guest_only_sees_own_issues(isolation_context):
    url = "/api/workspaces/{slug}/projects/{project_id}/issues/list/".format(
        slug=isolation_context["workspace"].slug,
        project_id=isolation_context["project_a"].id,
    )
    response = isolation_context["guest_client"].get(
        url,
        {
            "issues": ",".join(
                str(issue.id)
                for issue in (
                    isolation_context["guest_issue"],
                    isolation_context["issue_a"],
                )
            )
        },
    )
    assert response.status_code == status.HTTP_200_OK
    returned_ids = {str(row["id"]) for row in response.data}
    assert str(isolation_context["guest_issue"].id) in returned_ids
    assert str(isolation_context["issue_a"].id) not in returned_ids


def test_project_member_can_read_own_project_issue(isolation_context):
    response = isolation_context["member_client"].get(
        _issue_detail_url(
            isolation_context["workspace"],
            isolation_context["project_a"],
            isolation_context["issue_a"],
        )
    )
    assert response.status_code == status.HTTP_200_OK, getattr(response, "data", None)


def test_service_token_cannot_cross_project_or_workspace_boundaries(isolation_context):
    token = APIToken.objects.create(
        user=isolation_context["service_user"],
        workspace=isolation_context["workspace"],
        is_service=True,
        projects=[isolation_context["project_a"].id],
    )
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token._plaintext_token)

    allowed = client.get(_v1_issue_list_url(isolation_context["workspace"], isolation_context["project_a"]))
    assert allowed.status_code == status.HTTP_200_OK, getattr(allowed, "data", None)

    other_project = client.get(_v1_issue_list_url(isolation_context["workspace"], isolation_context["project_b"]))
    assert other_project.status_code == status.HTTP_403_FORBIDDEN

    other_workspace = client.get(
        _v1_issue_list_url(isolation_context["other_workspace"], isolation_context["foreign_project"])
    )
    assert other_workspace.status_code == status.HTTP_401_UNAUTHORIZED


def test_webhook_rejections_are_indistinguishable(isolation_context):
    cache.clear()
    integration = ExternalAccountIntegration.objects.create(
        workspace=isolation_context["workspace"],
        provider="github",
        provider_account_id="918273",
        account_name="isolation-github",
    )
    integration.set_webhook_secret("webhook-secret")
    integration.save()

    url = reverse("provider-webhook", kwargs={"provider": "github"})
    payload = {"action": "opened", "number": 7}
    unknown = APIClient().post(
        f"{url}?workspace=missing-workspace.example",
        payload,
        format="json",
    )
    bad_signature = APIClient().post(
        f"{url}?workspace={isolation_context['workspace'].slug}",
        payload,
        format="json",
        HTTP_X_HUB_SIGNATURE_256="sha256=invalid",
    )

    expected = {
        "error": {
            "code": "webhook_rejected",
            "message": "The webhook was not accepted.",
        }
    }
    assert unknown.status_code == status.HTTP_401_UNAUTHORIZED
    assert bad_signature.status_code == status.HTTP_401_UNAUTHORIZED
    assert unknown.json() == expected
    assert bad_signature.json() == expected


def test_webhook_receiver_is_rate_limited(isolation_context, monkeypatch):
    cache.clear()
    monkeypatch.setattr("plane.api.rate_limit.WEBHOOK_RECEIVER_LIMIT", 2)
    url = reverse("provider-webhook", kwargs={"provider": "github"}) + "?workspace=missing-workspace.example"
    client = APIClient()

    responses = [client.post(url, {"n": index}, format="json") for index in range(3)]

    assert [response.status_code for response in responses] == [401, 401, 429]


def test_invitation_accept_is_rate_limited(isolation_context, monkeypatch):
    cache.clear()
    monkeypatch.setattr("plane.api.rate_limit.INVITATION_ACCEPT_LIMIT", 2)
    invite = WorkspaceMemberInvite.objects.create(
        workspace=isolation_context["workspace"],
        email="invitee@example.com",
        token="invitation-token",
    )
    url = reverse(
        "workspace-join",
        kwargs={"slug": isolation_context["workspace"].slug, "pk": invite.id},
    )
    client = APIClient()

    responses = [client.post(url, {"token": "wrong-token", "accepted": True}, format="json") for _ in range(3)]

    assert [response.status_code for response in responses] == [403, 403, 429]
