# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for the central project-isolation helpers (PLN-015)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.http import Http404
from django.test import RequestFactory
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.test import APIRequestFactory

from plane.api.middleware.api_authentication import APIKeyAuthentication as ApiAuth
from plane.app.middleware.api_authentication import APIKeyAuthentication as AppAuth
from plane.app.serializers.api import APITokenSerializer
from plane.db.models import APIToken, Issue, WorkspaceMember
from plane.db.models.api import hash_api_token
from plane.utils.permissions.project_scope import (
    ProjectMismatch,
    assert_body_project_matches,
    check_project_scope,
    is_guest_restricted,
    require_project_membership,
    resolve_request_project,
    token_scope_violation,
    visible_objects,
)

from ...security.fixtures import ADMIN, make_user

pytestmark = pytest.mark.unit


def test_resolve_project_rejects_cross_workspace_id(isolation_context):
    request = RequestFactory().get("/")
    with pytest.raises(Http404):
        resolve_request_project(
            request,
            {
                "slug": isolation_context["workspace"].slug,
                "project_id": isolation_context["foreign_project"].id,
            },
        )


def test_membership_never_infers_permission_from_workspace_role(isolation_context, caplog):
    factory = RequestFactory()
    outsider = isolation_context["outsider"]
    project = isolation_context["project_a"]

    with pytest.raises(PermissionDenied):
        require_project_membership(outsider, project, slug=isolation_context["workspace"].slug)

    # Workspace-admin overrides are retained but must leave an identifier-only audit trail.
    override_admin = make_user("override")
    WorkspaceMember.objects.create(workspace=isolation_context["other_workspace"], member=override_admin, role=ADMIN)
    assert (
        require_project_membership(
            override_admin,
            isolation_context["foreign_project"],
            slug=isolation_context["other_workspace"].slug,
            request=factory.get("/secret/path"),
        )
        is None
    )
    assert "project_scope.workspace_admin_override" in caplog.text
    assert override_admin.email not in caplog.text


def test_detail_lookup_hides_and_collection_denies(isolation_context):
    factory = APIRequestFactory()
    request = factory.get("/")
    request.user = isolation_context["outsider"]
    kwargs = {
        "slug": isolation_context["workspace"].slug,
        "project_id": isolation_context["project_a"].id,
    }

    with pytest.raises(Http404):
        check_project_scope(request, {**kwargs, "pk": isolation_context["issue_a"].id})

    request = factory.get("/")
    request.user = isolation_context["outsider"]
    with pytest.raises(PermissionDenied):
        check_project_scope(request, kwargs)


def test_hide_membership_keeps_collection_404_contract(isolation_context):
    factory = APIRequestFactory()
    request = factory.get("/")
    request.user = isolation_context["outsider"]
    kwargs = {
        "slug": isolation_context["workspace"].slug,
        "project_id": isolation_context["project_a"].id,
    }

    with pytest.raises(Http404):
        check_project_scope(request, kwargs, hide_membership=True)


def test_body_project_mismatch_raises_400(isolation_context):
    request = APIRequestFactory().post(
        "/",
        {"project_id": str(isolation_context["project_b"].id)},
        format="json",
    )
    # APIRequestFactory returns a Django request; set DRF's parsed body shape
    # explicitly so the helper exercises the body/URL mismatch contract.
    request.data = {"project_id": str(isolation_context["project_b"].id)}
    request.user = isolation_context["member"]

    with pytest.raises(ProjectMismatch):
        check_project_scope(
            request,
            {
                "slug": isolation_context["workspace"].slug,
                "project_id": isolation_context["project_a"].id,
            },
        )

    assert_body_project_matches(None, isolation_context["project_a"])
    with pytest.raises(ProjectMismatch):
        assert_body_project_matches(uuid4(), isolation_context["project_a"])


def test_guest_sees_only_own_issues(isolation_context):
    guest = isolation_context["guest"]
    project = isolation_context["project_a"]
    queryset = Issue.objects.filter(project=project)

    assert is_guest_restricted(guest, project)
    visible = set(visible_objects(guest, project, queryset).values_list("id", flat=True))
    assert visible == {isolation_context["guest_issue"].id}

    member_visible = set(visible_objects(isolation_context["member"], project, queryset).values_list("id", flat=True))
    assert {isolation_context["issue_a"].id, isolation_context["guest_issue"].id} <= member_visible


def test_service_token_scope_enforces_workspace_and_project(isolation_context):
    token = APIToken.objects.create(
        user=isolation_context["service_user"],
        workspace=isolation_context["workspace"],
        is_service=True,
        projects=[isolation_context["project_a"].id],
    )
    request = SimpleNamespace(auth=token, method="GET", data=None)

    token_scope_violation(
        request,
        isolation_context["project_a"],
        slug=isolation_context["workspace"].slug,
    )

    with pytest.raises(PermissionDenied):
        token_scope_violation(
            request,
            isolation_context["project_b"],
            slug=isolation_context["workspace"].slug,
        )

    with pytest.raises(AuthenticationFailed):
        token_scope_violation(
            request,
            isolation_context["foreign_project"],
            slug=isolation_context["other_workspace"].slug,
        )


def test_api_tokens_are_hashed_and_plaintext_only_once(isolation_context):
    token = APIToken.objects.create(
        user=isolation_context["service_user"],
        workspace=isolation_context["workspace"],
    )
    plaintext = token._plaintext_token

    assert token.token != plaintext
    assert token.token_hash == hash_api_token(plaintext)
    assert APITokenSerializer(token).data["token"] == plaintext

    reloaded = APIToken.objects.get(pk=token.pk)
    assert APITokenSerializer(reloaded).data["token"] == token.token_prefix

    for authenticator in (ApiAuth(), AppAuth()):
        assert authenticator.resolve_api_token(plaintext).pk == token.pk

    with pytest.raises(AuthenticationFailed):
        ApiAuth().resolve_api_token("plane_api_invalid")
