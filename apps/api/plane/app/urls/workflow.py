# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    ProjectWorkflowEndpoint,
    ProjectWorkflowDetailEndpoint,
    WorkflowTransitionEndpoint,
    WorkflowTransitionDetailEndpoint,
    WorkflowResetEndpoint,
    WorkflowHealthEndpoint,
    IssueAllowedTransitionsEndpoint,
    IssueTransitionEndpoint,
)

P = "workspaces/<str:slug>/projects/<uuid:project_id>"

urlpatterns = [
    path(f"{P}/workflows/", ProjectWorkflowEndpoint.as_view(), name="project-workflows"),
    path(f"{P}/workflows/health/", WorkflowHealthEndpoint.as_view(), name="project-workflows-health"),
    path(f"{P}/workflows/<uuid:workflow_id>/", ProjectWorkflowDetailEndpoint.as_view(), name="project-workflow"),
    path(
        f"{P}/workflows/<uuid:workflow_id>/transitions/",
        WorkflowTransitionEndpoint.as_view(),
        name="project-workflow-transitions",
    ),
    path(
        f"{P}/workflows/<uuid:workflow_id>/transitions/<uuid:pk>/",
        WorkflowTransitionDetailEndpoint.as_view(),
        name="project-workflow-transition",
    ),
    path(f"{P}/workflows/<uuid:workflow_id>/reset/", WorkflowResetEndpoint.as_view(), name="project-workflow-reset"),
    path(
        f"{P}/work-items/<uuid:issue_id>/allowed-transitions/",
        IssueAllowedTransitionsEndpoint.as_view(),
        name="work-item-allowed-transitions",
    ),
    path(f"{P}/work-items/<uuid:issue_id>/transition/", IssueTransitionEndpoint.as_view(), name="work-item-transition"),
]
