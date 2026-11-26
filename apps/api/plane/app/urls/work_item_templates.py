# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    ProjectWorkItemTemplateDetailEndpoint,
    ProjectWorkItemTemplateEndpoint,
    WorkspaceWorkItemTemplateDetailEndpoint,
    WorkspaceWorkItemTemplateEndpoint,
    WorkspaceWorkItemTemplateOptionsEndpoint,
)

W = "workspaces/<str:slug>"
P = f"{W}/projects/<uuid:project_id>"

urlpatterns = [
    path(
        f"{W}/template-options/",
        WorkspaceWorkItemTemplateOptionsEndpoint.as_view(),
        name="workspace-work-item-template-options",
    ),
    path(f"{W}/templates/", WorkspaceWorkItemTemplateEndpoint.as_view(), name="workspace-work-item-templates"),
    path(
        f"{W}/templates/<uuid:pk>/",
        WorkspaceWorkItemTemplateDetailEndpoint.as_view(),
        name="workspace-work-item-template-detail",
    ),
    path(f"{P}/templates/", ProjectWorkItemTemplateEndpoint.as_view(), name="project-work-item-templates"),
    path(
        f"{P}/templates/<uuid:pk>/",
        ProjectWorkItemTemplateDetailEndpoint.as_view(),
        name="project-work-item-template-detail",
    ),
]
