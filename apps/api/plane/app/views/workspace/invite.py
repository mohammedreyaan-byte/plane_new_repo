# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import datetime

import jwt

# Django imports
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

# Third party modules
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, WorkSpaceAdminPermission, allow_permission
from plane.app.serializers import (
    WorkSpaceMemberInviteSerializer,
    WorkSpaceMemberInvitePublicSerializer,
    WorkSpaceMemberSerializer,
)
from plane.app.views.base import BaseAPIView
from plane.bgtasks.event_tracking_task import track_event
from plane.bgtasks.workspace_invitation_task import workspace_invitation
from plane.db.models import RoleAuditLog, User, Workspace, WorkspaceMember, WorkspaceMemberInvite
from plane.utils.cache import invalidate_cache, invalidate_cache_directly
from plane.utils.host import base_host
from plane.utils.analytics_events import USER_JOINED_WORKSPACE, USER_INVITED_TO_WORKSPACE
from plane.utils.permissions.capabilities import (
    KEY_TO_LEGACY_ID,
    LEGACY_ID_TO_KEY,
    resolve_role_for_invite,
    role_key_for_membership,
)
from .. import BaseViewSet


def _resolve_invite_role(workspace, role_key=None, legacy_role=None):
    """Resolve an invitation role without silently falling back to Guest.

    Returns ``(role, error)``. ``error`` is a response body for the single
    invite endpoint; callers that report per-email results can turn it into a
    human readable string.
    """
    if role_key is None and legacy_role is None:
        return resolve_role_for_invite(workspace, role_key="guest"), None

    key = str(role_key).strip().lower() if role_key is not None else None
    legacy_id = None
    if legacy_role is not None:
        try:
            legacy_id = int(legacy_role)
        except (TypeError, ValueError):
            return None, {"error": "role must be an integer", "code": "invalid_role"}

    if key is not None:
        expected_legacy_id = KEY_TO_LEGACY_ID.get(key)
        if expected_legacy_id is None:
            return None, {"role_key": ["Invalid role."]}
        if legacy_id is not None and legacy_id != expected_legacy_id:
            return None, {
                "error": "role and role_key refer to different roles",
                "code": "role_key_conflict",
            }
    else:
        key = LEGACY_ID_TO_KEY.get(legacy_id)
        if key is None:
            return None, {"role_key": ["Invalid role."]}

    role = resolve_role_for_invite(workspace, role_key=key)
    if role is None:
        return None, {"role_key": ["Invalid role."]}
    return role, None


def _invite_role_error_message(error):
    if isinstance(error, dict):
        if "role_key" in error:
            return "Invalid workspace role"
        return error.get("error") or "Invalid workspace role"
    return str(error)


class WorkspaceInvitationsViewset(BaseViewSet):
    """Endpoint for creating, listing and  deleting workspaces"""

    serializer_class = WorkSpaceMemberInviteSerializer
    model = WorkspaceMemberInvite

    permission_classes = [WorkSpaceAdminPermission]

    def get_queryset(self):
        return self.filter_queryset(
            super()
            .get_queryset()
            .filter(workspace__slug=self.kwargs.get("slug"))
            .select_related("workspace", "workspace__owner", "created_by", "role_ref")
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="member.manage")
    def create(self, request, slug):
        emails = request.data.get("emails", [])
        # Check if email is provided
        if not emails:
            return Response({"error": "Emails are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Get the workspace object
        workspace = Workspace.objects.get(slug=slug)

        # check for role level of the requesting user
        requesting_user = WorkspaceMember.objects.get(workspace__slug=slug, member=request.user, is_active=True)

        # Resolve every payload to a role once, so validation and persistence
        # cannot drift apart.
        resolved_emails = []
        for email in emails:
            role, error = _resolve_invite_role(workspace, email.get("role_key"), email.get("role"))
            if error is not None:
                return Response(error, status=status.HTTP_400_BAD_REQUEST)
            resolved_emails.append((email, role))

        # Check if any invited user has an higher role
        if any(role.legacy_id > requesting_user.role for _, role in resolved_emails):
            return Response(
                {"error": "You cannot invite a user with higher role"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user is already a member of workspace
        workspace_members = WorkspaceMember.objects.filter(
            workspace_id=workspace.id,
            member__email__in=[email.get("email") for email in emails],
            is_active=True,
        ).select_related("member", "member__avatar_asset")

        if workspace_members:
            return Response(
                {
                    "error": "Some users are already member of workspace",
                    "workspace_users": WorkSpaceMemberSerializer(workspace_members, many=True).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        workspace_invitations = []
        for email, role in resolved_emails:
            try:
                validate_email(email.get("email"))
                workspace_invitations.append(
                    WorkspaceMemberInvite(
                        email=email.get("email").strip().lower(),
                        workspace_id=workspace.id,
                        token=jwt.encode(
                            {"email": email, "timestamp": datetime.now().timestamp()},
                            settings.SECRET_KEY,
                            algorithm="HS256",
                        ),
                        role=role.legacy_id if role else email.get("role", 5),
                        role_ref=role,
                        created_by=request.user,
                    )
                )
            except ValidationError:
                return Response(
                    {
                        "error": f"Invalid email - {email} provided a valid email address is required to send the invite"  # noqa: E501
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        # Create workspace member invite
        workspace_invitations = WorkspaceMemberInvite.objects.bulk_create(
            workspace_invitations, batch_size=10, ignore_conflicts=True
        )

        current_site = base_host(request=request, is_app=True)

        # Send invitations
        for invitation in workspace_invitations:
            workspace_invitation.delay(
                invitation.email,
                workspace.id,
                invitation.token,
                current_site,
                request.user.email,
            )
            track_event.delay(
                user_id=request.user.id,
                event_name=USER_INVITED_TO_WORKSPACE,
                slug=slug,
                event_properties={
                    "user_id": request.user.id,
                    "workspace_id": workspace.id,
                    "workspace_slug": workspace.slug,
                    "invitee_role": invitation.role,
                    "invited_at": str(timezone.now()),
                    "invitee_email": invitation.email,
                },
            )

        return Response({"message": "Emails sent successfully"}, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="member.manage")
    def destroy(self, request, slug, pk):
        workspace_member_invite = WorkspaceMemberInvite.objects.get(pk=pk, workspace__slug=slug)
        workspace_member_invite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="member.manage")
    @invalidate_cache(
        path="/api/workspaces/:slug/members/",
        url_params=True,
        user=False,
        multiple=True,
    )
    def partial_update(self, request, slug, pk):
        """Change the role attached to a pending invitation."""
        invitation = WorkspaceMemberInvite.objects.select_related("workspace", "role_ref").filter(
            pk=pk, workspace__slug=slug
        ).first()
        if invitation is None:
            return Response({"error": "Invitation not found"}, status=status.HTTP_404_NOT_FOUND)
        if invitation.responded_at is not None:
            return Response(
                {"error": "The invitation has already been answered"},
                status=status.HTTP_409_CONFLICT,
            )

        role, error = _resolve_invite_role(invitation.workspace, request.data.get("role_key"), request.data.get("role"))
        if error is not None:
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        requesting_member = WorkspaceMember.objects.get(workspace__slug=slug, member=request.user, is_active=True)
        if role.legacy_id > requesting_member.role:
            return Response(
                {"error": "You cannot invite a user with higher role"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_role_key = role_key_for_membership(invitation)
        invitation.role = role.legacy_id
        invitation.role_ref = role
        invitation.save(update_fields=["role", "role_ref", "updated_at"])

        if old_role_key != role.key:
            target_id = User.objects.filter(email=invitation.email).values_list("id", flat=True).first()
            RoleAuditLog.objects.create(
                workspace=invitation.workspace,
                actor=request.user,
                target_id=target_id,
                old_role=old_role_key or "",
                new_role=role.key,
            )

        return Response(WorkSpaceMemberInviteSerializer(invitation).data, status=status.HTTP_200_OK)


class WorkspaceInvitationResendEndpoint(BaseAPIView):
    """Resend an existing pending invitation without creating a second system."""

    permission_classes = [WorkSpaceAdminPermission]

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="member.manage")
    def post(self, request, slug, pk):
        invitation = WorkspaceMemberInvite.objects.select_related("workspace").filter(
            pk=pk, workspace__slug=slug
        ).first()
        if invitation is None:
            return Response({"error": "Invitation not found"}, status=status.HTTP_404_NOT_FOUND)
        if invitation.responded_at is not None:
            return Response(
                {"error": "The invitation has already been answered"},
                status=status.HTTP_409_CONFLICT,
            )

        invitation.token = jwt.encode(
            {"email": invitation.email, "timestamp": datetime.now().timestamp()},
            settings.SECRET_KEY,
            algorithm="HS256",
        )
        invitation.save(update_fields=["token", "updated_at"])
        workspace_invitation.delay(
            invitation.email,
            invitation.workspace_id,
            invitation.token,
            base_host(request=request, is_app=True),
            request.user.email,
        )
        return Response(
            {"message": "Invitation resent", "invitation_id": str(invitation.id)},
            status=status.HTTP_200_OK,
        )


class WorkspaceBulkInviteEndpoint(BaseAPIView):
    """Invite many people at once and report a result per email.

    Unlike the batch endpoint above, a single bad address does not reject the
    whole request. Each email is validated, deduplicated and persisted on its
    own so the UI can show which invites succeeded.
    """

    permission_classes = [WorkSpaceAdminPermission]

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="member.manage")
    @invalidate_cache(
        path="/api/workspaces/:slug/members/",
        url_params=True,
        user=False,
        multiple=True,
    )
    def post(self, request, slug):
        entries = request.data.get("emails", [])
        if not isinstance(entries, list) or not entries:
            return Response({"error": "Emails are required"}, status=status.HTTP_400_BAD_REQUEST)

        workspace = Workspace.objects.get(slug=slug)
        requesting_user = WorkspaceMember.objects.get(workspace__slug=slug, member=request.user, is_active=True)
        current_site = base_host(request=request, is_app=True)

        results = []
        invited = 0
        updated = 0
        failed = 0
        seen_emails = set()
        member_ids_by_email = {}

        for raw_entry in entries:
            entry = {"email": raw_entry} if isinstance(raw_entry, str) else dict(raw_entry)
            email = str(entry.get("email") or "").strip().lower()

            if not email:
                failed += 1
                results.append(
                    {"email": "", "status": "invalid", "member_id": None, "error": "Email is required"}
                )
                continue

            try:
                validate_email(email)
            except ValidationError:
                failed += 1
                results.append(
                    {
                        "email": email,
                        "status": "invalid",
                        "member_id": None,
                        "error": "Invalid email address",
                    }
                )
                continue

            if email in seen_emails:
                failed += 1
                results.append(
                    {
                        "email": email,
                        "status": "already_member",
                        "member_id": member_ids_by_email.get(email),
                        "error": "Duplicate address in this list",
                    }
                )
                continue
            seen_emails.add(email)

            existing_member = (
                WorkspaceMember.objects.filter(workspace=workspace, member__email=email, is_active=True)
                .values_list("id", flat=True)
                .first()
            )
            if existing_member is not None:
                failed += 1
                member_ids_by_email[email] = str(existing_member)
                results.append(
                    {
                        "email": email,
                        "status": "already_member",
                        "member_id": str(existing_member),
                        "error": "Already a workspace member",
                    }
                )
                continue

            role, error = _resolve_invite_role(workspace, entry.get("role_key"), entry.get("role"))
            if error is not None:
                failed += 1
                results.append(
                    {
                        "email": email,
                        "status": "invalid",
                        "member_id": None,
                        "error": _invite_role_error_message(error),
                    }
                )
                continue
            legacy_role = role.legacy_id

            if legacy_role > requesting_user.role:
                failed += 1
                results.append(
                    {
                        "email": email,
                        "status": "invalid",
                        "member_id": None,
                        "error": "Role is higher than your own",
                    }
                )
                continue

            existing_invite = WorkspaceMemberInvite.objects.filter(
                workspace=workspace, email=email, responded_at__isnull=True
            ).first()

            if existing_invite is not None:
                existing_invite.role = legacy_role
                existing_invite.role_ref = role
                existing_invite.save()
                invitation = existing_invite
                outcome = "invited"
                updated += 1
            else:
                invitation = WorkspaceMemberInvite.objects.create(
                    email=email,
                    workspace=workspace,
                    token=jwt.encode(
                        {"email": email, "timestamp": datetime.now().timestamp()},
                        settings.SECRET_KEY,
                        algorithm="HS256",
                    ),
                    role=legacy_role,
                    role_ref=role,
                    created_by=request.user,
                )
                outcome = "invited"
                invited += 1

            workspace_invitation.delay(
                invitation.email,
                workspace.id,
                invitation.token,
                current_site,
                request.user.email,
            )
            track_event.delay(
                user_id=request.user.id,
                event_name=USER_INVITED_TO_WORKSPACE,
                slug=slug,
                event_properties={
                    "user_id": request.user.id,
                    "workspace_id": workspace.id,
                    "workspace_slug": workspace.slug,
                    "invitee_role": legacy_role,
                    "invited_at": str(timezone.now()),
                    "invitee_email": email,
                },
            )

            member_ids_by_email[email] = str(invitation.id)
            results.append(
                {
                    "email": email,
                    "status": outcome,
                    "member_id": str(invitation.id),
                    "updated": outcome == "invited" and existing_invite is not None,
                    "role": legacy_role,
                    "role_key": role.key if role else LEGACY_ID_TO_KEY.get(legacy_role),
                }
            )

        return Response(
            {
                "results": results,
                "invited": invited,
                "updated": updated,
                "failed": failed,
            },
            status=status.HTTP_200_OK,
        )


class WorkspaceJoinEndpoint(BaseAPIView):
    permission_classes = [AllowAny]
    """Invitation response endpoint the user can respond to the invitation"""

    @invalidate_cache(path="/api/workspaces/", user=False)
    @invalidate_cache(path="/api/users/me/workspaces/", multiple=True)
    @invalidate_cache(
        path="/api/workspaces/:slug/members/",
        user=False,
        multiple=True,
        url_params=True,
    )
    @invalidate_cache(path="/api/users/me/settings/", multiple=True)
    def post(self, request, slug, pk):
        workspace_invite = WorkspaceMemberInvite.objects.get(pk=pk, workspace__slug=slug)

        token = request.data.get("token", "")

        # Validate the token to verify the user received the invitation email
        if not token or workspace_invite.token != token:
            return Response(
                {"error": "You do not have permission to join the workspace"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Require an authenticated session — the accepting user must be the
        # person who was invited.  Without this check an attacker who registers
        # with the invited address (email-squat) and obtains the token via the
        # GET endpoint can steal the workspace membership (GHSA-4vj8-p63v-8p24).
        if not request.user.is_authenticated:
            return Response(
                {"error": "Authentication required to accept workspace invitation"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if request.user.email.lower() != workspace_invite.email.lower():
            return Response(
                {"error": "You do not have permission to accept this invitation"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # If already responded then return error
        if workspace_invite.responded_at is None:
            workspace_invite.accepted = request.data.get("accepted", False)
            workspace_invite.responded_at = timezone.now()
            workspace_invite.save()

            if workspace_invite.accepted:
                # Check if the user created account after invitation
                user = User.objects.filter(email=workspace_invite.email).first()

                # If the user is present then create the workspace member
                if user is not None:
                    # Check if the user was already a member of workspace then activate the user
                    workspace_member = WorkspaceMember.objects.filter(
                        workspace=workspace_invite.workspace, member=user
                    ).first()
                    if workspace_member is not None:
                        workspace_member.is_active = True
                        workspace_member.role = workspace_invite.role
                        workspace_member.role_ref = workspace_invite.role_ref
                        workspace_member.save()
                    else:
                        # Create a Workspace
                        _ = WorkspaceMember.objects.create(
                            workspace=workspace_invite.workspace,
                            member=user,
                            role=workspace_invite.role,
                            role_ref=workspace_invite.role_ref,
                        )

                    # Set the user last_workspace_id to the accepted workspace
                    user.last_workspace_id = workspace_invite.workspace.id
                    user.save()
                    track_event.delay(
                        user_id=user.id,
                        event_name=USER_JOINED_WORKSPACE,
                        slug=slug,
                        event_properties={
                            "user_id": user.id,
                            "workspace_id": workspace_invite.workspace.id,
                            "workspace_slug": workspace_invite.workspace.slug,
                            "role": workspace_invite.role,
                            "joined_at": str(timezone.now()),
                        },
                    )

                    # Delete the invitation
                    workspace_invite.delete()

                return Response(
                    {"message": "Workspace Invitation Accepted"},
                    status=status.HTTP_200_OK,
                )

            # Workspace invitation rejected
            return Response(
                {"message": "Workspace Invitation was not accepted"},
                status=status.HTTP_200_OK,
            )

        return Response(
            {"error": "You have already responded to the invitation request"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def get(self, request, slug, pk):
        workspace_invitation = WorkspaceMemberInvite.objects.get(workspace__slug=slug, pk=pk)
        # Use the public serializer that omits the token and invite_link fields so
        # that an unauthenticated caller cannot retrieve the acceptance token
        # (GHSA-86mg-259g-pwgg / GHSA-gf48-p6jp-cwc4).
        serializer = WorkSpaceMemberInvitePublicSerializer(workspace_invitation)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserWorkspaceInvitationsViewSet(BaseViewSet):
    serializer_class = WorkSpaceMemberInviteSerializer
    model = WorkspaceMemberInvite

    def get_queryset(self):
        return self.filter_queryset(
            super().get_queryset().filter(email=self.request.user.email).select_related("workspace")
        )

    @invalidate_cache(path="/api/workspaces/", user=False)
    @invalidate_cache(path="/api/users/me/workspaces/", multiple=True)
    def create(self, request):
        invitations = request.data.get("invitations", [])
        workspace_invitations = WorkspaceMemberInvite.objects.filter(
            pk__in=invitations, email=request.user.email
        ).order_by("-created_at")

        # If the user is already a member of workspace and was deactivated then activate the user
        for invitation in workspace_invitations:
            invalidate_cache_directly(
                path=f"/api/workspaces/{invitation.workspace.slug}/members/",
                user=False,
                request=request,
                multiple=True,
            )
            # Update the WorkspaceMember for this specific invitation
            WorkspaceMember.objects.filter(workspace_id=invitation.workspace_id, member=request.user).update(
                is_active=True, role=invitation.role, role_ref=invitation.role_ref
            )

            # Track event
            track_event.delay(
                user_id=request.user.id,
                event_name=USER_JOINED_WORKSPACE,
                slug=invitation.workspace.slug,
                event_properties={
                    "user_id": request.user.id,
                    "workspace_id": invitation.workspace.id,
                    "workspace_slug": invitation.workspace.slug,
                    "role": invitation.role,
                    "joined_at": str(timezone.now()),
                },
            )

        # Bulk create the user for all the workspaces
        WorkspaceMember.objects.bulk_create(
            [
                WorkspaceMember(
                    workspace=invitation.workspace,
                    member=request.user,
                    role=invitation.role,
                    role_ref=invitation.role_ref,
                    created_by=request.user,
                )
                for invitation in workspace_invitations
            ],
            ignore_conflicts=True,
        )

        # Delete joined workspace invites
        workspace_invitations.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
