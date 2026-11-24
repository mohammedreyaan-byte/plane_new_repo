# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Capability based permission helpers.

The legacy integer role column remains the source of truth for existing checks.
These helpers add a capability layer on top and resolve a user's effective role
from the role reference when one is present.
"""

from functools import wraps
from uuid import UUID, uuid4

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from plane.db.models import ProjectMember, Role, Workspace, WorkspaceMember

# ---------------------------------------------------------------------------
# Fallback capability matrix
# ---------------------------------------------------------------------------
# These constants are used when a workspace has not been migrated yet, or when
# a membership still only carries a legacy integer. The seed migration writes
# the same lists into the Role table.

ADMIN_CAPABILITIES = [
    "workspace.manage",
    "member.manage",
    "project.manage",
    "project.create",
    "type.manage",
    "workflow.manage",
    "integration.manage",
    "service_token.manage",
    "report.manage",
    "report.view",
    "report.export",
    "work_item.view",
    "work_item.create",
    "work_item.edit",
    "work_item.delete",
    "work_item.assign",
    "work_item.transition",
    "comment.create",
    "comment.delete",
    "attachment.create",
    "view.manage",
    "cycle.manage",
    "module.manage",
    "notification.manage",
    "webhook.manage",
]

MEMBER_CAPABILITIES = [
    capability
    for capability in ADMIN_CAPABILITIES
    if capability
    not in [
        "member.manage",
        "type.manage",
        "workflow.manage",
        "integration.manage",
        "service_token.manage",
        "notification.manage",
    ]
]

DEVELOPER_CAPABILITIES = [
    "work_item.view",
    "work_item.create",
    "work_item.edit",
    "work_item.assign",
    "work_item.transition",
    "comment.create",
    "attachment.create",
    "view.manage",
    "report.view",
    "report.export",
]

QA_CAPABILITIES = list(DEVELOPER_CAPABILITIES)

VIEWER_CAPABILITIES = [
    "work_item.view",
    "comment.read",
    "report.view",
]

GUEST_CAPABILITIES = [
    "work_item.view",
    "work_item.edit",
    "comment.create",
]

SYSTEM_ROLE_CAPABILITIES = {
    "admin": ADMIN_CAPABILITIES,
    "member": MEMBER_CAPABILITIES,
    "developer": DEVELOPER_CAPABILITIES,
    "qa": QA_CAPABILITIES,
    "viewer": VIEWER_CAPABILITIES,
    "guest": GUEST_CAPABILITIES,
}

LEGACY_ID_TO_KEY = {
    20: "admin",
    15: "member",
    12: "developer",
    11: "qa",
    2: "viewer",
    5: "guest",
}

KEY_TO_LEGACY_ID = {value: key for key, value in LEGACY_ID_TO_KEY.items()}

LEGACY_CAPABILITIES = {
    legacy_id: SYSTEM_ROLE_CAPABILITIES[key] for legacy_id, key in LEGACY_ID_TO_KEY.items()
}


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------


def get_role_capabilities(role, workspace=None):
    """Return the capability set for a Role instance or a legacy integer."""
    if role is None:
        return set()

    if isinstance(role, Role):
        capabilities = role.capabilities
        if not capabilities:
            capabilities = SYSTEM_ROLE_CAPABILITIES.get(role.key, [])
        return set(capabilities)

    # Legacy integer or string key.
    try:
        legacy_id = int(role)
    except (TypeError, ValueError):
        return set(SYSTEM_ROLE_CAPABILITIES.get(str(role), []))

    return set(LEGACY_CAPABILITIES.get(legacy_id, []))


def _workspace_id(workspace):
    """Accept a Workspace instance, a UUID, or a workspace slug."""
    if workspace is None:
        return None
    if hasattr(workspace, "id"):
        return workspace.id
    try:
        return UUID(str(workspace))
    except (TypeError, ValueError):
        # Unresolved slug: use a non-matching UUID so every lookup stays empty
        # instead of raising a UUID ValidationError.
        return (
            Workspace.objects.filter(slug=str(workspace)).values_list("id", flat=True).first()
            or uuid4()
        )


def get_user_workspace_role(user, workspace):
    """Return the effective workspace Role for a user, or None."""
    if not user or not user.is_authenticated:
        return None

    workspace_id = _workspace_id(workspace)
    membership = (
        WorkspaceMember.objects.filter(
            workspace_id=workspace_id,
            member=user,
            is_active=True,
        )
        .select_related("role_ref")
        .first()
    )
    if not membership:
        return None

    return _resolve_role(membership.role_ref, membership.role, workspace_id)


def get_user_project_role(user, workspace, project):
    """Return the effective project Role for a user, or None.

    Project membership is authoritative for project scoped capabilities,
    except that a workspace admin always resolves to admin.
    """
    if not user or not user.is_authenticated:
        return None

    workspace_id = _workspace_id(workspace)
    workspace_role = get_user_workspace_role(user, workspace_id)
    if workspace_role and workspace_role.key == "admin":
        return workspace_role

    project_id = getattr(project, "id", project)
    membership = (
        ProjectMember.objects.filter(
            project_id=project_id,
            workspace_id=workspace_id,
            member=user,
            is_active=True,
        )
        .select_related("role_ref")
        .first()
    )
    if not membership:
        return workspace_role

    return _resolve_role(membership.role_ref, membership.role, workspace_id)


def _resolve_role(role_ref, legacy_id, workspace_id):
    if role_ref:
        return role_ref

    key = LEGACY_ID_TO_KEY.get(legacy_id)
    if not key:
        return None

    # Prefer a workspace specific override, then the system role.
    role = (
        Role.objects.filter(workspace_id=workspace_id, key=key, is_active=True)
        .select_related("workspace")
        .first()
    )
    role = role or Role.objects.filter(workspace__isnull=True, key=key, is_active=True).first()
    if role is None:
        # Roles not seeded yet (fresh or unmigrated database): fall back to the built-in matrix
        # with an unsaved Role, so the user keeps the capabilities their integer role implies.
        role = Role(
            key=key,
            name=key.title(),
            legacy_id=legacy_id,
            capabilities=list(SYSTEM_ROLE_CAPABILITIES[key]),
            is_system=True,
        )
    return role


def get_effective_capabilities(user, workspace, project=None):
    if project is not None:
        role = get_user_project_role(user, workspace, project)
    else:
        role = get_user_workspace_role(user, workspace)
    return get_role_capabilities(role)


def has_capability(user, workspace, capability, project=None):
    if get_user_workspace_role(user, workspace) is None:
        return False
    return capability in get_effective_capabilities(user, workspace, project)


def has_capability_for_slug(user, slug, capability, project_id=None):
    """Same as has_capability but for views that only have the workspace slug."""
    workspace_id = Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()
    if workspace_id is None:
        return False
    return has_capability(user, workspace_id, capability, project=project_id)


def require_capability(user, workspace, capability, project=None):
    if not has_capability(user, workspace, capability, project=project):
        raise PermissionDenied(
            detail=f"Missing required capability: {capability}",
            code="missing_capability",
        )
    return True


def role_key_for_membership(membership):
    if membership is None:
        return None
    if getattr(membership, "role_ref_id", None) and membership.role_ref:
        return membership.role_ref.key
    return LEGACY_ID_TO_KEY.get(membership.role)


def resolve_role(workspace, role_key):
    """Resolve a role key to a workspace role, falling back to the system role."""
    if not role_key:
        return None

    key = str(role_key).strip().lower()
    workspace_id = getattr(workspace, "id", workspace)
    role = Role.objects.filter(workspace_id=workspace_id, key=key, is_active=True).first()
    return role or Role.objects.filter(workspace__isnull=True, key=key, is_active=True).first()


def resolve_role_for_invite(workspace, role_key=None, legacy_id=None):
    """Resolve the Role for an invite payload, accepting either identifier."""
    if role_key is None and legacy_id is not None:
        try:
            role_key = LEGACY_ID_TO_KEY.get(int(legacy_id))
        except (TypeError, ValueError):
            role_key = None
    return resolve_role(workspace, role_key)


# ---------------------------------------------------------------------------
# DRF integration
# ---------------------------------------------------------------------------


class ProjectCapabilityPermission(BasePermission):
    """DRF permission driven by view attributes.

    Set `required_capability` on the view and optionally
    `required_project_kwarg` (defaults to "project_id").
    """

    def has_permission(self, request, view):
        capability = getattr(view, "required_capability", None)
        if not capability:
            return True

        workspace_slug = view.kwargs.get("slug") or view.kwargs.get("workspace_slug")
        if not workspace_slug:
            return False

        project_kwarg = getattr(view, "required_project_kwarg", "project_id")
        project_id = view.kwargs.get(project_kwarg)

        from plane.db.models import Workspace

        workspace = Workspace.objects.filter(slug=workspace_slug).only("id").first()
        if not workspace:
            return False

        return has_capability(request.user, workspace, capability, project=project_id)


def capability_required(capability, project_kwarg="project_id"):
    """Decorator for function based DRF views."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(instance, request, *args, **kwargs):
            workspace_slug = kwargs.get("slug") or kwargs.get("workspace_slug")
            if not workspace_slug:
                raise PermissionDenied(detail="Workspace is required.", code="workspace_required")

            from plane.db.models import Workspace

            workspace = Workspace.objects.filter(slug=workspace_slug).only("id").first()
            if not workspace:
                raise PermissionDenied(detail="Workspace not found.", code="workspace_not_found")

            project_id = kwargs.get(project_kwarg) if project_kwarg else None
            require_capability(request.user, workspace, capability, project=project_id)
            return view_func(instance, request, *args, **kwargs)

        return _wrapped

    return decorator


__all__ = [
    "SYSTEM_ROLE_CAPABILITIES",
    "LEGACY_ID_TO_KEY",
    "KEY_TO_LEGACY_ID",
    "get_role_capabilities",
    "get_user_workspace_role",
    "get_user_project_role",
    "get_effective_capabilities",
    "has_capability",
    "require_capability",
    "role_key_for_membership",
    "resolve_role",
    "resolve_role_for_invite",
    "ProjectCapabilityPermission",
    "capability_required",
]
