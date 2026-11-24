# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third Party imports
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Min

# Module imports
from .base import BaseViewSet, BaseAPIView
from plane.app.serializers import (
    ProjectMemberSerializer,
    ProjectMemberAdminSerializer,
    ProjectMemberRoleSerializer,
    ProjectMemberPreferenceSerializer,
)

from plane.app.permissions import WorkspaceUserPermission

from plane.db.models import Project, ProjectMember, ProjectUserProperty, RoleAuditLog, WorkspaceMember
from plane.bgtasks.project_add_user_email_task import project_add_user_email
from plane.utils.host import base_host
from plane.app.permissions.base import allow_permission, ROLE
from plane.utils.permissions.capabilities import (
    KEY_TO_LEGACY_ID,
    LEGACY_ID_TO_KEY,
    resolve_role,
    role_key_for_membership,
)


def _role_level(role=None, role_ref=None, legacy_id=None):
    """Return the integer level used by legacy role comparisons."""
    key = None
    if role_ref is not None:
        key = role_ref.key
    elif role is not None:
        key = role_key_for_membership(role)
    elif legacy_id is not None:
        key = LEGACY_ID_TO_KEY.get(legacy_id)
    return KEY_TO_LEGACY_ID.get(key, 0)


def _resolve_member_role(workspace, role_key=None, legacy_role=None):
    """Resolve a project membership role, rejecting conflicting identifiers."""
    key = str(role_key).strip().lower() if role_key is not None else None
    legacy_id = None
    if legacy_role is not None:
        try:
            legacy_id = int(legacy_role)
        except (TypeError, ValueError):
            return None, "role must be an integer"
    if key is not None:
        expected = KEY_TO_LEGACY_ID.get(key)
        if expected is None:
            return None, "Invalid role."
        if legacy_id is not None and legacy_id != expected:
            return None, "role and role_key refer to different roles"
    else:
        key = LEGACY_ID_TO_KEY.get(legacy_id)
        if key is None:
            return None, "Invalid role."
    role = resolve_role(workspace, key)
    if role is None:
        return None, "Invalid role."
    return role, None


class ProjectMemberViewSet(BaseViewSet):
    serializer_class = ProjectMemberAdminSerializer
    model = ProjectMember

    search_fields = ["member__display_name", "member__first_name"]

    def get_queryset(self):
        return self.filter_queryset(
            super()
            .get_queryset()
            .filter(workspace__slug=self.kwargs.get("slug"))
            .filter(project_id=self.kwargs.get("project_id"))
            .filter(member__is_bot=False)
            .filter()
            .select_related("project")
            .select_related("member")
            .select_related("workspace", "workspace__owner")
        )

    @allow_permission([ROLE.ADMIN])
    def create(self, request, slug, project_id):
        # Get the list of members to be added to the project and their roles i.e. the user_id and the role
        members = request.data.get("members", [])

        # get the project
        project = Project.objects.get(pk=project_id, workspace__slug=slug)

        # Check if the members array is empty
        if not len(members):
            return Response(
                {"error": "At least one member is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Initialize the bulk arrays
        bulk_project_members = []
        bulk_issue_props = []

        # Resolve every requested member to a Role once. The legacy integer
        # column stays in sync with the role reference.
        member_roles = {}
        member_role_refs = {}
        for member in members:
            member_id = str(member.get("member_id"))
            role, error = _resolve_member_role(project.workspace, member.get("role_key"), member.get("role"))
            if error is not None:
                return Response(
                    {"role_key": ["Invalid role."]} if error == "Invalid role." else {"error": error},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            member_roles[member_id] = role.legacy_id
            member_role_refs[member_id] = role

        # check the workspace role of the new user
        for member_id in member_roles:
            workspace_member = WorkspaceMember.objects.select_related("role_ref").get(
                workspace__slug=slug, member=member_id, is_active=True
            )
            workspace_level = _role_level(workspace_member)
            project_level = _role_level(role_ref=member_role_refs[member_id])

            if workspace_level == KEY_TO_LEGACY_ID["admin"] and project_level < workspace_level:
                return Response(
                    {"error": "You cannot add a user with role lower than the workspace role"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if project_level > workspace_level:
                return Response(
                    {"error": "You cannot add a user with role higher than the workspace role"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Update roles in the members array based on the member_roles dictionary and set is_active to True
        existing_member_ids = set()
        for project_member in ProjectMember.objects.filter(
            project_id=project_id,
            member_id__in=[member.get("member_id") for member in members],
        ):
            member_id = str(project_member.member_id)
            existing_member_ids.add(member_id)
            old_role_key = role_key_for_membership(project_member)
            project_member.role = member_roles[member_id]
            project_member.role_ref = member_role_refs.get(member_id)
            project_member.is_active = True
            if old_role_key != role_key_for_membership(project_member):
                RoleAuditLog.objects.create(
                    workspace=project.workspace,
                    project=project,
                    scope=RoleAuditLog.SCOPE_PROJECT,
                    actor=request.user,
                    target_id=project_member.member_id,
                    old_role=old_role_key or "",
                    new_role=role_key_for_membership(project_member) or "",
                )
            bulk_project_members.append(project_member)

        # Update the roles of the existing members
        ProjectMember.objects.bulk_update(bulk_project_members, ["is_active", "role", "role_ref"], batch_size=100)

        # Get the minimum sort_order for each member in the workspace
        member_sort_orders = (
            ProjectUserProperty.objects.filter(
                workspace__slug=slug,
                user_id__in=[member.get("member_id") for member in members],
            )
            .values("user_id")
            .annotate(min_sort_order=Min("sort_order"))
        )
        # Convert to dictionary for easy lookup: {user_id: min_sort_order}
        sort_order_map = {str(item["user_id"]): item["min_sort_order"] for item in member_sort_orders}

        # Loop through requested members
        for member in members:
            member_id = str(member.get("member_id"))
            # Get the minimum sort_order for this member, or use default
            min_sort_order = sort_order_map.get(member_id)
            # Create a new project member
            bulk_project_members.append(
                ProjectMember(
                    member_id=member.get("member_id"),
                    role=member_roles.get(str(member.get("member_id")), 5),
                    role_ref=member_role_refs.get(str(member.get("member_id"))),
                    project_id=project_id,
                    workspace_id=project.workspace_id,
                )
            )
            # Create a new issue property
            bulk_issue_props.append(
                ProjectUserProperty(
                    user_id=member.get("member_id"),
                    project_id=project_id,
                    workspace_id=project.workspace_id,
                    sort_order=(min_sort_order - 10000 if min_sort_order is not None else 65535),
                )
            )

        # Bulk create the project members and issue properties
        project_members = ProjectMember.objects.bulk_create(bulk_project_members, batch_size=10, ignore_conflicts=True)

        for member in members:
            member_id = str(member.get("member_id"))
            if member_id in existing_member_ids:
                continue
            role_ref = member_role_refs[member_id]
            RoleAuditLog.objects.create(
                workspace=project.workspace,
                project=project,
                scope=RoleAuditLog.SCOPE_PROJECT,
                actor=request.user,
                target_id=member_id,
                old_role="",
                new_role=role_ref.key if role_ref else LEGACY_ID_TO_KEY.get(member_roles[member_id], ""),
            )

        _ = ProjectUserProperty.objects.bulk_create(bulk_issue_props, batch_size=10, ignore_conflicts=True)

        project_members = ProjectMember.objects.filter(
            project_id=project_id,
            member_id__in=[member.get("member_id") for member in members],
        )
        # Send emails to notify the users
        [
            project_add_user_email.delay(
                base_host(request=request, is_app=True),
                project_member.id,
                request.user.id,
            )
            for project_member in project_members
        ]
        # Serialize the project members
        serializer = ProjectMemberRoleSerializer(project_members, many=True)
        # Return the serialized data
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def list(self, request, slug, project_id):
        # Get the list of project members for the project
        project_members = ProjectMember.objects.filter(
            project_id=project_id,
            workspace__slug=slug,
            member__is_bot=False,
            is_active=True,
            member__member_workspace__workspace__slug=slug,
            member__member_workspace__is_active=True,
        ).select_related("project", "member", "workspace")

        serializer = ProjectMemberRoleSerializer(project_members, fields=("id", "member", "role", "role_ref", "role_key"), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def retrieve(self, request, slug, project_id, pk):
        requesting_project_member = ProjectMember.objects.get(
            project_id=project_id,
            workspace__slug=slug,
            member=request.user,
            is_active=True,
        )

        project_member = (
            ProjectMember.objects.filter(
                pk=pk,
                project_id=project_id,
                workspace__slug=slug,
                member__is_bot=False,
                is_active=True,
            )
            .select_related("project", "member", "workspace")
            .first()
        )

        if not project_member:
            return Response(
                {"error": "Project member not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if requesting_project_member.role > ROLE.GUEST.value:
            serializer = ProjectMemberAdminSerializer(project_member)
        else:
            serializer = ProjectMemberRoleSerializer(project_member, fields=("id", "member", "role"))

        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def partial_update(self, request, slug, project_id, pk):
        project_member = ProjectMember.objects.get(pk=pk, workspace__slug=slug, project_id=project_id, is_active=True)

        # Fetch the target's workspace role (used to cap the new project role)
        target_workspace_role = WorkspaceMember.objects.get(
            workspace__slug=slug, member=project_member.member, is_active=True
        ).role
        # Fetch the requester's workspace role to decide if they may bypass project-role checks
        requester_workspace_role = WorkspaceMember.objects.get(
            workspace__slug=slug, member=request.user, is_active=True
        ).role
        is_workspace_admin = requester_workspace_role == ROLE.ADMIN.value

        # Check if the user is not editing their own role if they are not an admin
        if request.user.id == project_member.member_id and not is_workspace_admin:
            return Response(
                {"error": "You cannot update your own role"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Check while updating user roles
        requested_project_member = ProjectMember.objects.get(
            project_id=project_id,
            workspace__slug=slug,
            member=request.user,
            is_active=True,
        )

        new_role = None
        new_role_ref = None
        old_role_key = role_key_for_membership(project_member)
        role_key = request.data.get("role_key")
        legacy_role = request.data.get("role")

        if role_key is not None or legacy_role is not None:
            if role_key is not None:
                role_key = str(role_key).strip().lower()
                new_role_ref = resolve_role(project_member.workspace, role_key)
                if new_role_ref is None:
                    return Response({"role_key": ["Invalid role."]}, status=status.HTTP_400_BAD_REQUEST)
                new_role = new_role_ref.legacy_id

            if legacy_role is not None:
                try:
                    legacy_role = int(legacy_role)
                except (TypeError, ValueError):
                    return Response(
                        {"error": "role must be an integer", "code": "invalid_role"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if new_role is not None and new_role != legacy_role:
                    return Response(
                        {"error": "role and role_key refer to different roles", "code": "role_key_conflict"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if new_role is None:
                    new_role = legacy_role
                    new_role_ref = resolve_role(project_member.workspace, LEGACY_ID_TO_KEY.get(new_role))

            # Only Admins can modify roles
            if requested_project_member.role < ROLE.ADMIN.value and not is_workspace_admin:
                return Response(
                    {"error": "You do not have permission to update roles"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Cannot modify a member whose role is equal to or higher than your own
            if project_member.role >= requested_project_member.role and not is_workspace_admin:
                return Response(
                    {"error": "You cannot update the role of a member with a role equal to or higher than your own"},
                    status=status.HTTP_403_FORBIDDEN,
                )


            # Cannot assign a role equal to or higher than your own
            if new_role >= requested_project_member.role and not is_workspace_admin:
                return Response(
                    {"error": "You cannot assign a role equal to or higher than your own"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Cannot assign a role higher than the target's workspace role
            workspace_role_level = _role_level(legacy_id=target_workspace_role)
            if _role_level(legacy_id=new_role) > workspace_role_level:
                return Response(
                    {"error": "You cannot add a user with role higher than the workspace role"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Never leave the project without an admin.
            if new_role != ROLE.ADMIN.value:
                other_admins = (
                    ProjectMember.objects.filter(
                        project_id=project_id,
                        workspace__slug=slug,
                        role=ROLE.ADMIN.value,
                        is_active=True,
                    )
                    .exclude(pk=project_member.pk)
                    .count()
                )
                if other_admins == 0:
                    return Response(
                        {"error": "The project must have at least one admin.", "code": "last_admin_protected"},
                        status=status.HTTP_409_CONFLICT,
                    )

        # Guard privileged `is_active` mutations (member (de)activation). These are NOT
        # covered by the role block above, so without this check a GUEST could PATCH
        # {"is_active": false} while omitting "role" to deactivate any member — including
        # admins — and take over the project. Mirror the role block and destroy(): only a
        # project admin (or workspace admin) may (de)activate a member, and never one whose
        # role is equal to or higher than the requester's own.
        if "is_active" in request.data:
            if requested_project_member.role < ROLE.ADMIN.value and not is_workspace_admin:
                return Response(
                    {"error": "You do not have permission to update member status"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if project_member.role >= requested_project_member.role and not is_workspace_admin:
                return Response(
                    {"error": "You cannot update the status of a member with a role equal to or higher than your own"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        payload = {key: value for key, value in request.data.items()}
        if new_role is not None:
            payload["role"] = new_role

        serializer = ProjectMemberSerializer(project_member, data=payload, partial=True)

        if serializer.is_valid():
            member = serializer.save()
            if new_role_ref is not None:
                member.role_ref = new_role_ref
                member.save(update_fields=["role_ref", "role"])
                if role_key_for_membership(member) != old_role_key:
                    RoleAuditLog.objects.create(
                        workspace=member.workspace,
                        project=member.project,
                        scope=RoleAuditLog.SCOPE_PROJECT,
                        actor=request.user,
                        target_id=member.member_id,
                        old_role=old_role_key or "",
                        new_role=role_key_for_membership(member) or "",
                    )
            return Response(ProjectMemberRoleSerializer(member).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_permission([ROLE.ADMIN])
    def destroy(self, request, slug, project_id, pk):
        project_member = ProjectMember.objects.get(
            workspace__slug=slug,
            project_id=project_id,
            pk=pk,
            member__is_bot=False,
            is_active=True,
        )
        # check requesting user role
        requesting_project_member = ProjectMember.objects.get(
            workspace__slug=slug,
            member=request.user,
            project_id=project_id,
            is_active=True,
        )
        # User cannot remove himself
        if str(project_member.id) == str(requesting_project_member.id):
            return Response(
                {"error": "You cannot remove yourself from the workspace. Please use leave workspace"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # User cannot deactivate higher role
        if requesting_project_member.role < project_member.role:
            return Response(
                {"error": "You cannot remove a user having role higher than you"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Never remove the last project admin.
        if role_key_for_membership(project_member) == "admin":
            other_admins = (
                ProjectMember.objects.filter(
                    project_id=project_id,
                    workspace__slug=slug,
                    role=ROLE.ADMIN.value,
                    is_active=True,
                )
                .exclude(pk=project_member.pk)
                .count()
            )
            if other_admins == 0:
                return Response(
                    {"error": "The project must have at least one admin.", "code": "last_admin_protected"},
                    status=status.HTTP_409_CONFLICT,
                )

        RoleAuditLog.objects.create(
            workspace=project_member.workspace,
            project=project_member.project,
            scope=RoleAuditLog.SCOPE_PROJECT,
            actor=request.user,
            target_id=project_member.member_id,
            old_role=role_key_for_membership(project_member) or "",
            new_role="",
        )
        project_member.is_active = False
        project_member.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def leave(self, request, slug, project_id):
        project_member = ProjectMember.objects.get(
            workspace__slug=slug,
            project_id=project_id,
            member=request.user,
            is_active=True,
        )

        # Check if the leaving user is the only admin of the project
        if (
            project_member.role == 20
            and not ProjectMember.objects.filter(
                workspace__slug=slug, project_id=project_id, role=20, is_active=True
            ).count()
            > 1
        ):
            return Response(
                {
                    "error": "You cannot leave the project as your the only admin of the project you will have to either delete the project or create an another admin"  # noqa: E501
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        RoleAuditLog.objects.create(
            workspace=project_member.workspace,
            project=project_member.project,
            scope=RoleAuditLog.SCOPE_PROJECT,
            actor=request.user,
            target_id=request.user.id,
            old_role=role_key_for_membership(project_member) or "",
            new_role="",
        )
        # Deactivate the user
        project_member.is_active = False
        project_member.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectMemberUserEndpoint(BaseAPIView):
    def get(self, request, slug, project_id):
        project_member = ProjectMember.objects.get(
            project_id=project_id,
            workspace__slug=slug,
            member=request.user,
            is_active=True,
        )
        serializer = ProjectMemberSerializer(project_member)

        return Response(serializer.data, status=status.HTTP_200_OK)


class UserProjectRolesEndpoint(BaseAPIView):
    permission_classes = [WorkspaceUserPermission]
    use_read_replica = True

    def get(self, request, slug):
        project_members = ProjectMember.objects.filter(
            workspace__slug=slug,
            member_id=request.user.id,
            is_active=True,
            member__member_workspace__workspace__slug=slug,
            member__member_workspace__is_active=True,
        ).values("project_id", "role")

        project_members = {str(member["project_id"]): member["role"] for member in project_members}
        return Response(project_members, status=status.HTTP_200_OK)


class ProjectMemberPreferenceEndpoint(BaseAPIView):
    def get_queryset(self, slug, project_id, member_id):
        return ProjectMember.objects.get(
            project_id=project_id,
            member_id=member_id,
            workspace__slug=slug,
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def patch(self, request, slug, project_id, member_id):
        project_member = self.get_queryset(slug, project_id, member_id)

        serializer = ProjectMemberPreferenceSerializer(project_member, {"preferences": request.data}, partial=True)

        if serializer.is_valid():
            serializer.save()

            return Response({"preferences": serializer.data["preferences"]}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, member_id):
        project_member = self.get_queryset(slug, project_id, member_id)

        serializer = ProjectMemberPreferenceSerializer(project_member)

        return Response(serializer.data, status=status.HTTP_200_OK)
