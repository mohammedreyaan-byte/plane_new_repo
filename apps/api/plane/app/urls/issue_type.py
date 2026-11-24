# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    WorkspaceIssueTypeEndpoint,
    WorkspaceIssueTypeDetailEndpoint,
    WorkspaceIssueTypeReorderEndpoint,
    ProjectIssueTypeEndpoint,
    ProjectIssueTypeDetailEndpoint,
    ProjectIssueTypeReorderEndpoint,
    ProjectIssueTypeToggleEndpoint,
)

urlpatterns = [
    path("workspaces/<str:slug>/work-item-types/", WorkspaceIssueTypeEndpoint.as_view(), name="workspace-work-item-types"),
    path(
        "workspaces/<str:slug>/work-item-types/reorder/",
        WorkspaceIssueTypeReorderEndpoint.as_view(),
        name="workspace-work-item-types-reorder",
    ),
    path(
        "workspaces/<str:slug>/work-item-types/<uuid:type_id>/",
        WorkspaceIssueTypeDetailEndpoint.as_view(),
        name="workspace-work-item-type",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-types/",
        ProjectIssueTypeEndpoint.as_view(),
        name="project-work-item-types",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-types/reorder/",
        ProjectIssueTypeReorderEndpoint.as_view(),
        name="project-work-item-types-reorder",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-types/<uuid:pk>/",
        ProjectIssueTypeDetailEndpoint.as_view(),
        name="project-work-item-type",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-types/<str:action>/",
        ProjectIssueTypeToggleEndpoint.as_view(),
        name="project-work-item-types-toggle",
    ),
]
