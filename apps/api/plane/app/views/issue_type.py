# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work item type management (PLN-004).

Workspace level: the catalogue of types (Bug, Task, Story, Epic and any the team adds).
Project level: which types a project uses, which one is the default, and the switch that turns
types and workflows on for the project.
"""

# Django imports
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils.text import slugify

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .base import BaseAPIView
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import Issue, IssueType, Project, ProjectIssueType
from plane.utils.workflow.service import seed_project_workflows


def _error(code, message, http_status=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": {"code": code, "message": message, **extra}}, status=http_status)


def serialize_type(issue_type, projects_count=None):
    data = {
        "id": issue_type.id,
        "key": issue_type.key,
        "name": issue_type.name,
        "description": issue_type.description,
        "logo_props": issue_type.logo_props,
        "is_epic": issue_type.is_epic,
        "is_default": issue_type.is_default,
        "is_active": issue_type.is_active,
        "level": issue_type.level,
    }
    if projects_count is not None:
        data["projects_count"] = projects_count
    return data


def serialize_project_type(row, project_enabled):
    return {
        "id": row.id,
        "issue_type_id": row.issue_type_id,
        "issue_type": serialize_type(row.issue_type),
        "is_enabled": bool(row.is_enabled and project_enabled),
        "is_default": row.is_default,
        "level": row.level,
    }


class WorkspaceIssueTypeEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        types = (
            IssueType.objects.filter(workspace__slug=slug)
            .annotate(
                projects_count=Count(
                    "project_issue_types",
                    filter=Q(project_issue_types__is_enabled=True, project_issue_types__deleted_at__isnull=True),
                    distinct=True,
                )
            )
            .order_by("level", "name")
        )
        return Response([serialize_type(t, t.projects_count) for t in types], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="type.manage")
    def post(self, request, slug):
        from plane.db.models import Workspace

        workspace = Workspace.objects.get(slug=slug)
        name = (request.data.get("name") or "").strip()
        if not name:
            return _error("name_required", "A name is required.")
        key = slugify(request.data.get("key") or name)[:50]
        if not key:
            return _error("key_invalid", "The key must contain letters or numbers.")
        if IssueType.objects.filter(workspace=workspace, key=key).exists():
            return _error("key_taken", f"A work item type with the key '{key}' already exists.")

        try:
            with transaction.atomic():
                if request.data.get("is_default"):
                    IssueType.objects.filter(workspace=workspace, is_default=True).update(is_default=False)
                issue_type = IssueType.objects.create(
                    workspace=workspace,
                    key=key,
                    name=name,
                    description=request.data.get("description", "") or "",
                    logo_props=request.data.get("logo_props") or {},
                    is_epic=bool(request.data.get("is_epic", False)),
                    is_default=bool(request.data.get("is_default", False)),
                    level=request.data.get("level", 0) or 0,
                )
        except IntegrityError:
            return _error("type_invalid", "The work item type could not be created.")
        return Response(serialize_type(issue_type, 0), status=status.HTTP_201_CREATED)


class WorkspaceIssueTypeDetailEndpoint(BaseAPIView):
    def _get(self, slug, type_id):
        return IssueType.objects.filter(workspace__slug=slug, pk=type_id).first()

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug, type_id):
        issue_type = self._get(slug, type_id)
        if issue_type is None:
            return _error("not_found", "Work item type not found.", status.HTTP_404_NOT_FOUND)
        count = ProjectIssueType.objects.filter(issue_type=issue_type, is_enabled=True).count()
        return Response(serialize_type(issue_type, count), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="type.manage")
    def patch(self, request, slug, type_id):
        issue_type = self._get(slug, type_id)
        if issue_type is None:
            return _error("not_found", "Work item type not found.", status.HTTP_404_NOT_FOUND)
        if "key" in request.data and request.data["key"] != issue_type.key:
            return _error("key_immutable", "The key of a work item type cannot be changed.")

        with transaction.atomic():
            if request.data.get("is_default") is True:
                IssueType.objects.filter(workspace=issue_type.workspace, is_default=True).exclude(
                    pk=issue_type.pk
                ).update(is_default=False)
            for field in ("name", "description", "logo_props", "is_epic", "is_default", "is_active", "level"):
                if field in request.data:
                    setattr(issue_type, field, request.data[field])
            if issue_type.is_default and not issue_type.is_active:
                return _error(
                    "default_type_protected", "The default type cannot be deactivated.", status.HTTP_409_CONFLICT
                )
            issue_type.save()
        return Response(serialize_type(issue_type), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="type.manage")
    def delete(self, request, slug, type_id):
        issue_type = self._get(slug, type_id)
        if issue_type is None:
            return _error("not_found", "Work item type not found.", status.HTTP_404_NOT_FOUND)
        if issue_type.is_default:
            return _error("default_type_protected", "The default type cannot be deleted.", status.HTTP_409_CONFLICT)

        issues = Issue.objects.filter(type=issue_type)
        count = issues.count()
        force = str(request.query_params.get("force", "")).lower() == "true"
        if count and not force:
            return _error(
                "type_in_use",
                f"{count} work items use this type. Pass force=true to move them to the project default.",
                status.HTTP_409_CONFLICT,
                count=count,
            )

        with transaction.atomic():
            if count:
                for project_id in issues.values_list("project_id", flat=True).distinct():
                    default_row = ProjectIssueType.objects.filter(
                        project_id=project_id, is_default=True, is_enabled=True
                    ).first()
                    issues.filter(project_id=project_id).update(
                        type_id=default_row.issue_type_id if default_row else None
                    )
            ProjectIssueType.objects.filter(issue_type=issue_type).delete()
            issue_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceIssueTypeReorderEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="type.manage")
    def post(self, request, slug):
        ids = request.data.get("ids") or []
        types = {str(t.id): t for t in IssueType.objects.filter(workspace__slug=slug, pk__in=ids)}
        if len(types) != len(ids):
            return _error("type_invalid", "One or more ids are not work item types of this workspace.")
        with transaction.atomic():
            for position, type_id in enumerate(ids):
                types[str(type_id)].level = position
                types[str(type_id)].save(update_fields=["level", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Project level
# ---------------------------------------------------------------------------


class ProjectIssueTypeEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        rows = (
            ProjectIssueType.objects.filter(project=project)
            .select_related("issue_type")
            .order_by("level", "issue_type__name")
        )
        return Response(
            [serialize_project_type(r, project.is_issue_type_enabled) for r in rows], status=status.HTTP_200_OK
        )

    @allow_permission([ROLE.ADMIN], capability="type.manage")
    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        if not project.is_issue_type_enabled:
            return _error("types_disabled", "Work item types are not enabled in this project.")
        issue_type = IssueType.objects.filter(
            workspace=project.workspace, pk=request.data.get("issue_type_id"), is_active=True
        ).first()
        if issue_type is None:
            return _error("type_invalid", "That work item type does not exist in this workspace.")

        is_enabled = request.data.get("is_enabled", True)
        is_default = bool(request.data.get("is_default", False))
        if is_default and not is_enabled:
            return _error("type_invalid", "The default type must be enabled.")

        with transaction.atomic():
            row, _ = ProjectIssueType.objects.get_or_create(
                project=project, issue_type=issue_type, defaults={"level": issue_type.level}
            )
            row.is_enabled = bool(is_enabled)
            if is_default:
                ProjectIssueType.objects.filter(project=project, is_default=True).exclude(pk=row.pk).update(
                    is_default=False
                )
                row.is_default = True
            row.save()
        return Response(serialize_project_type(row, True), status=status.HTTP_200_OK)


class ProjectIssueTypeDetailEndpoint(BaseAPIView):
    def _row(self, slug, project_id, row_id):
        return (
            ProjectIssueType.objects.filter(pk=row_id, project_id=project_id, project__workspace__slug=slug)
            .select_related("issue_type", "project")
            .first()
        )

    @allow_permission([ROLE.ADMIN], capability="type.manage")
    def patch(self, request, slug, project_id, pk):
        row = self._row(slug, project_id, pk)
        if row is None:
            return _error("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
        if not row.project.is_issue_type_enabled:
            return _error("types_disabled", "Work item types are not enabled in this project.")

        with transaction.atomic():
            if "is_enabled" in request.data:
                if not request.data["is_enabled"] and row.is_default:
                    return _error(
                        "default_type_protected",
                        "Make another type the default before disabling this one.",
                        status.HTTP_409_CONFLICT,
                    )
                row.is_enabled = bool(request.data["is_enabled"])
            if request.data.get("is_default") is True:
                if not row.is_enabled:
                    return _error("type_invalid", "The default type must be enabled.")
                ProjectIssueType.objects.filter(project_id=project_id, is_default=True).exclude(pk=row.pk).update(
                    is_default=False
                )
                row.is_default = True
            if "level" in request.data:
                row.level = request.data["level"]
            row.save()
        return Response(serialize_project_type(row, True), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], capability="type.manage")
    def delete(self, request, slug, project_id, pk):
        """Disable the type in this project. Work items keep their type value; it is just hidden."""
        row = self._row(slug, project_id, pk)
        if row is None:
            return _error("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
        if not row.project.is_issue_type_enabled:
            return _error("types_disabled", "Work item types are not enabled in this project.")
        if row.is_default:
            return _error(
                "default_type_protected",
                "Make another type the default before disabling this one.",
                status.HTTP_409_CONFLICT,
            )
        row.is_enabled = False
        row.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectIssueTypeReorderEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], capability="type.manage")
    def post(self, request, slug, project_id):
        ids = request.data.get("ids") or []
        rows = {str(r.id): r for r in ProjectIssueType.objects.filter(project_id=project_id, pk__in=ids)}
        if len(rows) != len(ids):
            return _error("type_invalid", "One or more ids are not types of this project.")
        with transaction.atomic():
            for position, row_id in enumerate(ids):
                rows[str(row_id)].level = position
                rows[str(row_id)].save(update_fields=["level", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectIssueTypeToggleEndpoint(BaseAPIView):
    """Turn work item types and workflows on (``enable``) or off (``disable``) for a project."""

    @allow_permission([ROLE.ADMIN], capability="type.manage")
    def post(self, request, slug, project_id, action):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        if action == "enable":
            summary = seed_project_workflows(project)
            Project.objects.filter(pk=project.pk).update(is_issue_type_enabled=True)
            return Response({"is_issue_type_enabled": True, "workflows": summary}, status=status.HTTP_200_OK)
        # Disabling hides types and lifts workflow enforcement. Nothing is deleted.
        Project.objects.filter(pk=project.pk).update(is_issue_type_enabled=False)
        return Response({"is_issue_type_enabled": False}, status=status.HTTP_200_OK)
