# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Central project-isolation helpers (PLN-015).

Every project-scoped lookup, collection and mutation should go through these
helpers.  Membership is always checked with an **active ProjectMember** row;
``get_user_project_role`` deliberately returns a workspace-admin role without
project membership and must never be used as evidence of membership.

Error contract:
    * object lookups -> Http404 (the object is treated as non-existent)
    * collections/mutations -> PermissionDenied (generic message)
    * body/URL project mismatch -> ProjectMismatch (400, ``project_mismatch``)
"""

import logging
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Q
from django.http import Http404

from rest_framework.exceptions import APIException, AuthenticationFailed, PermissionDenied
from rest_framework.permissions import SAFE_METHODS

from plane.db.models import Project, ProjectMember, WorkspaceMember
from plane.utils.role_compat import NON_CONTRIBUTOR_ROLES

logger = logging.getLogger("plane.security.isolation")

GUEST_ROLES = NON_CONTRIBUTOR_ROLES


class ProjectMismatch(APIException):
    """Body project_id disagrees with the project resolved from the URL."""

    status_code = 400
    default_detail = {"error": {"code": "project_mismatch", "message": "The project does not match the request."}}
    default_code = "project_mismatch"


def _as_id(value):
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def log_project_admin_override(user, *, project_id=None, slug=None, request=None):
    """Safe, identifier-only audit record for workspace-admin overrides."""
    logger.warning(
        "project_scope.workspace_admin_override",
        extra={
            "user_id": str(getattr(user, "id", "")),
            "project_id": str(project_id or ""),
            "workspace_slug": str(slug or ""),
            "method": getattr(request, "method", ""),
            "path": getattr(request, "path", ""),
        },
    )


def _log_admin_override(user, project, *, slug=None, request=None):
    """Log workspace-admin access to a project they are not a member of.

    Only identifiers are logged: never names, emails, tokens or payloads.
    """
    log_project_admin_override(
        user,
        project_id=getattr(project, "id", None),
        slug=slug or getattr(getattr(project, "workspace", None), "slug", None),
        request=request,
    )


def resolve_request_project(request, kwargs=None, *, allow_body=False):
    """Resolve the project from URL kwargs (or, explicitly, the request body).

    Returns ``None`` when the request is not project-scoped.  An unknown or
    cross-workspace project raises Http404 so object endpoints do not disclose
    the existence of projects in other tenants.
    """
    cached = getattr(request, "project_scope", None)
    if cached is not None:
        return cached

    kwargs = kwargs or {}
    slug = kwargs.get("slug") or getattr(request, "workspace_slug", None)
    project_id = kwargs.get("project_id")
    identifier = kwargs.get("project_identifier")

    if not project_id and not identifier and allow_body:
        project_id = (getattr(request, "data", None) or {}).get("project_id")

    if not project_id and not identifier:
        return None

    queryset = Project.objects.all()
    if slug:
        queryset = queryset.filter(workspace__slug=slug)

    if identifier:
        project = queryset.filter(identifier__iexact=str(identifier)).first()
    else:
        project_uuid = _as_id(project_id)
        if project_uuid is None:
            raise Http404
        project = queryset.filter(pk=project_uuid).first()

    if project is None:
        raise Http404
    return project


def is_active_project_member(user, project):
    """True only for an active ProjectMember row (never a workspace role)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return ProjectMember.objects.filter(project_id=project.id, member_id=user.id, is_active=True).exists()


def active_project_membership(user, *, project_id=None, workspace_slug=None, project_identifier=None, roles=None):
    """Single source of truth for active ProjectMember permission checks."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    queryset = ProjectMember.objects.filter(member_id=user.id, is_active=True)
    if project_id:
        queryset = queryset.filter(project_id=project_id)
    if workspace_slug:
        queryset = queryset.filter(workspace__slug=workspace_slug)
    if project_identifier:
        queryset = queryset.filter(project__identifier=project_identifier)
    if roles:
        queryset = queryset.filter(role__in=roles)
    return queryset.exists()


def active_workspace_membership(user, workspace_slug, *, roles=None):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    queryset = WorkspaceMember.objects.filter(member_id=user.id, workspace__slug=workspace_slug, is_active=True)
    if roles:
        queryset = queryset.filter(role__in=roles)
    return queryset.exists()


def workspace_admin(user, slug=None, project=None):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    workspace_id = getattr(getattr(project, "workspace", None), "id", None)
    queryset = WorkspaceMember.objects.filter(member_id=user.id, role=20, is_active=True)
    if workspace_id:
        return queryset.filter(workspace_id=workspace_id).exists()
    if slug:
        return queryset.filter(workspace__slug=slug).exists()
    return False


def require_project_membership(user, project, *, slug=None, request=None, allow_admin_override=True):
    """Return the active ProjectMember or raise PermissionDenied.

    The workspace-admin override is retained for backwards compatibility but
    is always logged.  It is not inferred from ``get_user_project_role``.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDenied()

    membership = ProjectMember.objects.filter(project_id=project.id, member_id=user.id, is_active=True).first()
    if membership:
        # A token scoped to a different project must not benefit from membership.
        return membership

    if allow_admin_override and workspace_admin(user, slug=slug, project=project):
        _log_admin_override(user, project, slug=slug, request=request)
        return None

    raise PermissionDenied()


def assert_body_project_matches(body_project_id, project, *, key="project_id"):
    """Reject a body project_id that disagrees with the URL project."""
    if body_project_id in (None, ""):
        return
    body_uuid = _as_id(body_project_id)
    if body_uuid is None or project is None or body_uuid != project.id:
        raise ProjectMismatch()


def token_scope_violation(request, project=None, *, slug=None):
    """Check a service token's workspace/project scope.

    Raises AuthenticationFailed for a workspace mismatch and PermissionDenied
    for a project that is outside the token's explicit scope.
    """
    token = getattr(request, "auth", None)
    if token is None or not getattr(token, "is_service", False):
        return

    if token.revoked_at is not None or not token.is_active:
        raise AuthenticationFailed("Given API token is not valid")

    token_workspace_id = getattr(token, "workspace_id", None)
    expected_workspace_id = getattr(getattr(project, "workspace", None), "id", None)

    # The token's workspace is authoritative. Resolving the URL slug must not
    # replace it: doing so masked cross-workspace tokens whenever the slug and
    # project agreed with each other but not with the token.
    if token_workspace_id and slug:
        from plane.db.models import Workspace

        slug_workspace_id = Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()
        if slug_workspace_id and str(token_workspace_id) != str(slug_workspace_id):
            raise AuthenticationFailed("Given API token is not valid")

    if token_workspace_id and expected_workspace_id and str(token_workspace_id) != str(expected_workspace_id):
        raise AuthenticationFailed("Given API token is not valid")

    scoped_projects = getattr(token, "projects", None)
    if project is not None and scoped_projects:
        if str(project.id) not in {str(value) for value in scoped_projects}:
            raise PermissionDenied()


OBJECT_ID_KWARGS = frozenset(
    {
        "pk",
        "issue_id",
        "issue_identifier",
        "work_item_id",
        "comment_id",
        "asset_id",
        "draft_id",
        "favorite_id",
        "cycle_id",
        "module_id",
        "page_id",
        "relation_id",
        "intake_id",
        "state_id",
        "label_id",
        "template_id",
        "entity_id",
    }
)


def check_project_scope(request, kwargs, *, hide_membership=False):
    """Enforce project membership/token scope for a DRF request.

    Called from ``initial()`` for both the app and external API base views,
    before any view body runs.  Object-id lookups return 404; collections and
    mutations return 403.  Endpoints that historically hide a project from
    non-members can set ``hide_membership=True`` to keep that 404 contract.
    Returns the resolved project (or ``None``).
    """
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return None

    project = resolve_request_project(request, kwargs)
    request.project_scope = project
    if project is None:
        token_scope_violation(request, None, slug=kwargs.get("slug"))
        return None

    is_detail = bool(OBJECT_ID_KWARGS.intersection(kwargs))
    has_membership = is_active_project_member(user, project)
    is_admin_override = not has_membership and workspace_admin(user, slug=kwargs.get("slug"), project=project)
    if (is_detail or hide_membership) and not has_membership and not is_admin_override:
        raise Http404

    require_project_membership(user, project, slug=kwargs.get("slug"), request=request)
    token_scope_violation(request, project, slug=kwargs.get("slug"))

    if request.method not in SAFE_METHODS:
        body = getattr(request, "data", None)
        if isinstance(body, dict) and "project_id" in body:
            assert_body_project_matches(body.get("project_id"), project)
    return project


def is_guest_restricted(user, project):
    """Guests and viewers only see their own items unless the project opts in."""
    if not user or not getattr(user, "is_authenticated", False) or project is None:
        return False
    if getattr(project, "guest_view_all_features", False):
        return False
    return ProjectMember.objects.filter(
        project_id=project.id,
        member_id=user.id,
        is_active=True,
        role__in=GUEST_ROLES,
    ).exists()


def membership_q(user, *, project_field="project"):
    """Q object restricting a queryset to active project members."""
    if not user or not getattr(user, "is_authenticated", False):
        return Q(pk__in=[])
    return Q(
        **{
            f"{project_field}__project_projectmember__member_id": user.id,
            f"{project_field}__project_projectmember__is_active": True,
        }
    )


def guest_visibility_q(user, *, project_field="project", role_field=None, created_by_field="created_by_id"):
    """Q object applying the guest own-only rule across many projects.

    Use for workspace-wide searches/counts.  Non-guests see all objects in the
    projects they belong to; restricted guests only see objects they created.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return Q(pk__in=[])
    role_field = role_field or f"{project_field}__project_projectmember__role"
    return (
        Q(created_by_id=user.id)
        | Q(**{f"{project_field}__guest_view_all_features": True})
        | Q(**{f"{role_field}__gt": 5})
    )


def visible_objects(user, project, queryset, *, created_by_field="created_by_id"):
    """Filter an already project-scoped queryset by membership and guest rule."""
    if not user or not getattr(user, "is_authenticated", False):
        return queryset.none()
    queryset = queryset.filter(membership_q(user))
    if is_guest_restricted(user, project):
        queryset = queryset.filter(**{created_by_field: user.id})
    return queryset.distinct()


def visible_issues(user, project, queryset=None, *, include_archived=False):
    """Project issues visible to ``user``; use this for lists, counts and exports."""
    from plane.db.models import Issue

    queryset = queryset if queryset is not None else Issue.issue_objects.all()
    queryset = queryset.filter(project_id=project.id)
    if not include_archived:
        queryset = queryset.filter(state__deleted_at__isnull=True)
    return visible_objects(user, project, queryset)


def project_queryset(user, workspace_slug, *, include_archived=False):
    """Projects visible to ``user`` inside a workspace (for aggregates/search)."""
    if not user or not getattr(user, "is_authenticated", False):
        return Project.objects.none()

    queryset = Project.objects.filter(
        workspace__slug=workspace_slug,
        project_projectmember__member_id=user.id,
        project_projectmember__is_active=True,
    ).distinct()
    if not include_archived:
        queryset = queryset.filter(archived_at__isnull=True)

    if workspace_admin(user, slug=workspace_slug):
        _log_admin_override(user, None, slug=workspace_slug)
        all_projects = Project.objects.filter(workspace__slug=workspace_slug)
        if not include_archived:
            all_projects = all_projects.filter(archived_at__isnull=True)
        return all_projects
    return queryset


def scoped_get_or_404(queryset, *args, **lookups):
    """Fetch one object from an already scoped queryset or raise Http404."""
    try:
        return queryset.get(*args, **lookups)
    except (ObjectDoesNotExist, ValidationError, ValueError, TypeError):
        raise Http404
    except queryset.model.MultipleObjectsReturned:
        raise Http404


def has_project_asset_access(user, asset, *, project=None):
    """Whether ``user`` may see/download a FileAsset.

    Workspace-level assets (logos, avatars) require workspace membership;
    project assets require active project membership and, for restricted
    guests, ownership of the asset.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    project = project or getattr(asset, "project", None)
    if project is None and getattr(asset, "project_id", None):
        from plane.db.models import Project as ProjectModel

        project = ProjectModel.objects.filter(pk=asset.project_id).first()

    if project is None:
        return WorkspaceMember.objects.filter(
            workspace_id=getattr(asset, "workspace_id", None), member_id=user.id, is_active=True
        ).exists()

    if not is_active_project_member(user, project):
        return workspace_admin(user, project=project)
    if is_guest_restricted(user, project) and getattr(asset, "created_by_id", None) != user.id:
        return False
    return True
