# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    ReportListEndpoint,
    ReportDetailEndpoint,
    ReportDataEndpoint,
    ReportExportEndpoint,
    BuiltInReportEndpoint,
    BuiltInReportExportEndpoint,
)

P = "workspaces/<str:slug>/projects/<uuid:project_id>/reports"

urlpatterns = [
    path(f"{P}/", ReportListEndpoint.as_view(), name="project-reports"),
    # Saved reports (uuid) come before the built-in slugs.
    path(f"{P}/<uuid:report_id>/", ReportDetailEndpoint.as_view(), name="project-report"),
    path(f"{P}/<uuid:report_id>/data/", ReportDataEndpoint.as_view(), name="project-report-data"),
    path(f"{P}/<uuid:report_id>/export/", ReportExportEndpoint.as_view(), name="project-report-export"),
    path(f"{P}/<slug:report_slug>/", BuiltInReportEndpoint.as_view(), name="project-report-built-in"),
    path(
        f"{P}/<slug:report_slug>/export/", BuiltInReportExportEndpoint.as_view(), name="project-report-built-in-export"
    ),
]
