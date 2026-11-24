# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project reports (PLN-019).

* ``report.view``   - every project role that can see work items except Guest (so Viewer can).
* ``report.export`` - Admin, Member, Developer, QA. Viewer can look but not export.
* Edit/delete a saved report - its owner or a project admin.
* Anyone who is not a member of the project gets a 404, as do reports of another project.
"""

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers.report import ReportDefinitionSerializer
from plane.db.models import Project, ProjectMember, ReportDefinition, WorkspaceMember
from plane.utils.reports.csv_export import build_csv
from plane.utils.reports.filters import FILTER_KEYS, ReportFilterError
from plane.utils.reports.queries import BUILT_IN_SLUGS, REPORT_TITLES, ReportNotFound
from plane.utils.reports.service import run_report

from .base import BaseAPIView


def _err(code, message, http_status=status.HTTP_400_BAD_REQUEST, **details):
    return Response({"error": {"code": code, "message": message, "details": details}}, status=http_status)


def _filters_from_query(params):
    return {key: params.get(key) for key in FILTER_KEYS if params.get(key) not in (None, "")}


class ReportBaseEndpoint(BaseAPIView):
    """Resolves the project, hides it from non-members and honours ``reports_enabled``."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        project = Project.objects.filter(pk=kwargs["project_id"], workspace__slug=kwargs["slug"]).first()
        if (
            not project
            or not ProjectMember.objects.filter(project=project, member=request.user, is_active=True).exists()
        ):
            raise NotFound()
        if not project.reports_enabled:
            raise NotFound(detail={"error": {"code": "reports_disabled", "message": "Reports are turned off."}})
        self.project = project

    # -- helpers -----------------------------------------------------------------------------
    def _run(self, report_type, raw_filters):
        try:
            return run_report(self.project, report_type, raw_filters, self.request.user), None
        except ReportFilterError as exc:
            return None, _err(exc.code, exc.message, **exc.details)
        except ReportNotFound as exc:
            return None, _err("not_found", f"{exc} not found in this project.", status.HTTP_404_NOT_FOUND)

    def _is_project_admin(self, user):
        return (
            ProjectMember.objects.filter(
                project=self.project, member=user, is_active=True, role=ROLE.ADMIN.value
            ).exists()
            or WorkspaceMember.objects.filter(
                workspace=self.project.workspace, member=user, is_active=True, role=ROLE.ADMIN.value
            ).exists()
        )

    def _csv_response(self, result, title, filename_key):
        response = HttpResponse(build_csv(result, title), content_type="text/csv; charset=utf-8")
        stamp = timezone.now().strftime("%Y%m%d")
        response["Content-Disposition"] = f'attachment; filename="report-{filename_key}-{stamp}.csv"'
        return response


class ReportListEndpoint(ReportBaseEndpoint):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], capability="report.view")
    def get(self, request, slug, project_id):
        reports = ReportDefinition.objects.filter(project=self.project).filter(
            Q(is_shared=True) | Q(owned_by=request.user)
        )
        data = ReportDefinitionSerializer(
            reports, many=True, context={"request": request, "project_id": self.project.id}
        ).data
        return Response(data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], capability="report.view")
    def post(self, request, slug, project_id):
        serializer = ReportDefinitionSerializer(
            data=request.data, context={"request": request, "project_id": self.project.id}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(project=self.project, workspace=self.project.workspace, owned_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ReportDetailEndpoint(ReportBaseEndpoint):
    def _get_report(self, request, report_id):
        report = ReportDefinition.objects.filter(pk=report_id, project=self.project).first()
        if not report or not (report.is_shared or report.owned_by_id == request.user.id):
            raise NotFound()
        return report

    def _serializer_context(self, request):
        return {"request": request, "project_id": self.project.id}

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], capability="report.view")
    def get(self, request, slug, project_id, report_id):
        report = self._get_report(request, report_id)
        return Response(ReportDefinitionSerializer(report, context=self._serializer_context(request)).data)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], capability="report.view")
    def patch(self, request, slug, project_id, report_id):
        report = self._get_report(request, report_id)
        if report.owned_by_id != request.user.id and not self._is_project_admin(request.user):
            return _err(
                "forbidden", "Only the owner or a project admin can edit this report.", status.HTTP_403_FORBIDDEN
            )
        serializer = ReportDefinitionSerializer(
            report, data=request.data, partial=True, context=self._serializer_context(request)
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], capability="report.view")
    def delete(self, request, slug, project_id, report_id):
        report = self._get_report(request, report_id)
        if report.owned_by_id != request.user.id and not self._is_project_admin(request.user):
            return _err(
                "forbidden", "Only the owner or a project admin can delete this report.", status.HTTP_403_FORBIDDEN
            )
        report.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReportDataEndpoint(ReportBaseEndpoint):
    """Computed numbers of a saved report. Same URL, same numbers for every member."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], capability="report.view")
    def get(self, request, slug, project_id, report_id):
        report = ReportDetailEndpoint._get_report(self, request, report_id)
        result, error = self._run(report.report_type, report.filters)
        if error:
            return error
        result = {
            **result,
            "definition": {
                "id": str(report.id),
                "name": report.name,
                "chart_type": report.chart_type,
                "group_by": report.group_by,
            },
        }
        return Response(result)


class ReportExportEndpoint(ReportBaseEndpoint):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], capability="report.export")
    def get(self, request, slug, project_id, report_id):
        report = ReportDetailEndpoint._get_report(self, request, report_id)
        result, error = self._run(report.report_type, report.filters)
        if error:
            return error
        return self._csv_response(result, report.name, report.report_type)


class BuiltInReportEndpoint(ReportBaseEndpoint):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], capability="report.view")
    def get(self, request, slug, project_id, report_slug):
        report_type = BUILT_IN_SLUGS.get(report_slug)
        if not report_type:
            raise NotFound()
        result, error = self._run(report_type, _filters_from_query(request.query_params))
        if error:
            return error
        return Response({**result, "title": REPORT_TITLES[report_type]})


class BuiltInReportExportEndpoint(ReportBaseEndpoint):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], capability="report.export")
    def get(self, request, slug, project_id, report_slug):
        report_type = BUILT_IN_SLUGS.get(report_slug)
        if not report_type:
            raise NotFound()
        result, error = self._run(report_type, _filters_from_query(request.query_params))
        if error:
            return error
        return self._csv_response(result, REPORT_TITLES[report_type], report_type)
