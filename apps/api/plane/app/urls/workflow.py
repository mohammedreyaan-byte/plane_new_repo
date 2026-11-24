# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    ProjectWorkflowEndpoint,
    ProjectWorkflowDetailEndpoint,
    WorkflowStateEndpoint,
    ProjectWorkflowCloneEndpoint,
    WorkflowTransitionEndpoint,
    WorkflowTransitionDetailEndpoint,
    WorkflowResetEndpoint,
    WorkflowHealthEndpoint,
    WorkflowExportEndpoint,
    WorkflowImportEndpoint,
    IssueAllowedTransitionsEndpoint,
    IssueTransitionEndpoint,
    WorkflowAllowedTransitionsEndpoint,
    WorkflowAuditEndpoint,
)

P = "workspaces/<str:slug>/projects/<uuid:project_id>"

urlpatterns = [
    path(f"{P}/workflows/", ProjectWorkflowEndpoint.as_view(), name="project-workflows"),
    path(f"{P}/workflows/health/", WorkflowHealthEndpoint.as_view(), name="project-workflows-health"),
    path(f"{P}/workflows/audit/", WorkflowAuditEndpoint.as_view(), name="project-workflows-audit"),
    path(f"{P}/workflows/import/", WorkflowImportEndpoint.as_view(), name="project-workflows-import"),
    path(f"{P}/workflows/<uuid:workflow_id>/", ProjectWorkflowDetailEndpoint.as_view(), name="project-workflow"),
    path(
        f"{P}/workflows/<uuid:workflow_id>/export/",
        WorkflowExportEndpoint.as_view(),
        name="project-workflow-export",
    ),
    path(
        f"{P}/workflows/<uuid:workflow_id>/states/<uuid:pk>/",
        WorkflowStateEndpoint.as_view(),
        name="project-workflow-state",
    ),
    path(
        f"{P}/workflows/<uuid:workflow_id>/clone/",
        ProjectWorkflowCloneEndpoint.as_view(),
        name="project-workflow-clone",
    ),
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
    path(
        f"{P}/workflows/<uuid:workflow_id>/allowed-transitions/",
        WorkflowAllowedTransitionsEndpoint.as_view(),
        name="workflow-allowed-transitions",
    ),
    path(f"{P}/workflows/<uuid:workflow_id>/reset/", WorkflowResetEndpoint.as_view(), name="project-workflow-reset"),
    path(
        f"{P}/work-items/<uuid:issue_id>/allowed-transitions/",
        IssueAllowedTransitionsEndpoint.as_view(),
        name="work-item-allowed-transitions",
    ),
    path(f"{P}/work-items/<uuid:issue_id>/transition/", IssueTransitionEndpoint.as_view(), name="work-item-transition"),
]
