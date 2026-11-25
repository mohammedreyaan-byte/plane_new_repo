# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    AppIntegrationListEndpoint,
    AutomationOptionsEndpoint,
    AutomationRuleDetailEndpoint,
    AutomationRuleEndpoint,
    AutomationRuleTestEndpoint,
    AutomationRunEndpoint,
    ImportDetailEndpoint,
    ImportEndpoint,
    ImportErrorsEndpoint,
    InitiativeDetailEndpoint,
    InitiativeEndpoint,
    InitiativeOptionsEndpoint,
    ProviderOAuthAuthorizeEndpoint,
    ProviderOAuthCallbackEndpoint,
    ProviderWebhookEndpoint,
    RepositoryDetailEndpoint,
    RepositoryListEndpoint,
    SlackChannelsEndpoint,
    SlackEndpoint,
    SlackTestEndpoint,
    WebhookEventListEndpoint,
    WorkspaceIntegrationDetailEndpoint,
    WorkspaceIntegrationListEndpoint,
)

W = "workspaces/<str:slug>"
P = f"{W}/projects/<uuid:project_id>"

urlpatterns = [
    path(f"{W}/integrations/", AppIntegrationListEndpoint.as_view(), name="app-integrations"),
    path(f"{W}/workspace-integrations/", WorkspaceIntegrationListEndpoint.as_view(), name="workspace-integrations"),
    path(
        f"{W}/workspace-integrations/<str:provider>/",
        WorkspaceIntegrationDetailEndpoint.as_view(),
        name="workspace-integration-detail",
    ),
    path(
        f"{W}/integrations/<str:provider>/oauth-authorize/",
        ProviderOAuthAuthorizeEndpoint.as_view(),
        name="integration-oauth-authorize",
    ),
    path(
        "integrations/<str:provider>/callback/",
        ProviderOAuthCallbackEndpoint.as_view(),
        name="integration-oauth-callback",
    ),
    path(
        f"{W}/workspace-integrations/<str:provider>/repositories/",
        RepositoryListEndpoint.as_view(),
        name="integration-repositories",
    ),
    path(
        f"{W}/workspace-integrations/<str:provider>/repositories/<uuid:repository_id>/",
        RepositoryDetailEndpoint.as_view(),
        name="integration-repository-detail",
    ),
    path(
        f"{W}/workspace-integrations/<str:provider>/webhook-events/",
        WebhookEventListEndpoint.as_view(),
        name="integration-webhook-events",
    ),
    path("webhooks/<str:provider>/", ProviderWebhookEndpoint.as_view(), name="provider-webhook"),
    path(f"{P}/initiatives/", InitiativeEndpoint.as_view(), name="initiatives"),
    path(f"{P}/initiatives/options/", InitiativeOptionsEndpoint.as_view(), name="initiative-options"),
    path(f"{P}/initiatives/<uuid:pk>/", InitiativeDetailEndpoint.as_view(), name="initiative-detail"),
    path(f"{P}/automation-rules/", AutomationRuleEndpoint.as_view(), name="automation-rules"),
    path(f"{P}/automation-runs/", AutomationRunEndpoint.as_view(), name="automation-runs"),
    path(f"{P}/automation-options/", AutomationOptionsEndpoint.as_view(), name="automation-options"),
    path(f"{P}/automation-rules/<uuid:pk>/", AutomationRuleDetailEndpoint.as_view(), name="automation-rule-detail"),
    path(f"{P}/automation-rules/<uuid:pk>/test/", AutomationRuleTestEndpoint.as_view(), name="automation-rule-test"),
    path(f"{P}/imports/", ImportEndpoint.as_view(), name="imports"),
    path(f"{P}/imports/<uuid:pk>/", ImportDetailEndpoint.as_view(), name="import-detail"),
    path(f"{P}/imports/<uuid:pk>/errors/", ImportErrorsEndpoint.as_view(), name="import-errors"),
    path(f"{W}/slack/", SlackEndpoint.as_view(), name="slack-integration"),
    path(f"{W}/slack/channels/", SlackChannelsEndpoint.as_view(), name="slack-channels"),
    path(f"{W}/slack/test/", SlackTestEndpoint.as_view(), name="slack-test"),
]
