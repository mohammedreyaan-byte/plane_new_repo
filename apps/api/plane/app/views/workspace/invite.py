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
from plane.app.permissions import WorkSpaceAdminPermission
from plane.app.serializers import (
    WorkSpaceMemberInviteSerializer,
    WorkSpaceMemberInvitePublicSerializer,
    WorkSpaceMemberSerializer,
)
from plane.app.views.base import BaseAPIView
from plane.bgtasks.event_tracking_task import track_event
from plane.bgtasks.workspace_invitation_task import workspace_invitation
from plane.db.models import User, Workspace, WorkspaceMember, WorkspaceMemberInvite
from plane.utils.cache import invalidate_cache, invalidate_cache_directly
from plane.utils.host import base_host
from plane.utils.analytics_events import USER_JOINED_WORKSPACE, USER_INVITED_TO_WORKSPACE
from plane.utils.permissions.capabilities import (
    LEGACY_ID_TO_KEY,
    resolve_role_for_invite,
)
from .. import BaseViewSet


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
            .select_related("workspace", "workspace__owner", "created_by")
        )

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
            role_key = email.get("role_key")
            legacy_role = email.get("role")
            role = resolve_role_for_invite(workspace, role_key=role_key, legacy_id=legacy_role)
            if role is None:
                role = resolve_role_for_invite(workspace, role_key="guest")
            resolved_emails.append((email, role))

        # Check if any invited user has an higher role
        if len(
            [
                email
                for email, role in resolved_emails
                if (role.legacy_id if role else int(email.get("role", 5))) > requesting_user.role
            ]
        ):
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

    def destroy(self, request, slug, pk):
        workspace_member_invite = WorkspaceMemberInvite.objects.get(pk=pk, workspace__slug=slug)
        workspace_member_invite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceBulkInviteEndpoint(BaseAPIView):
    """Invite many people at once and report a result per email.

    Unlike the batch endpoint above, a single bad address does not reject the
    whole request. Each email is validated, deduplicated and persisted on its
    own so the UI can show which invites succeeded.
    """

    permission_classes = [WorkSpaceAdminPermission]

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

        for raw_entry in entries:
            entry = {"email": raw_entry} if isinstance(raw_entry, str) else dict(raw_entry)
            email = str(entry.get("email") or "").strip().lower()

            if not email:
                failed += 1
                results.append({"email": "", "status": "failed", "error": "Email is required"})
                continue

            try:
                validate_email(email)
            except ValidationError:
                failed += 1
                results.append({"email": email, "status": "failed", "error": "Invalid email address"})
                continue

            if WorkspaceMember.objects.filter(workspace=workspace, member__email=email, is_active=True).exists():
                failed += 1
                results.append({"email": email, "status": "failed", "error": "Already a workspace member"})
                continue

            role = resolve_role_for_invite(
                workspace,
                role_key=entry.get("role_key"),
                legacy_id=entry.get("role"),
            ) or resolve_role_for_invite(workspace, role_key="guest")
            legacy_role = role.legacy_id if role else 5

            if legacy_role > requesting_user.role:
                failed += 1
                results.append({"email": email, "status": "failed", "error": "Role is higher than your own"})
                continue

            existing_invite = WorkspaceMemberInvite.objects.filter(
                workspace=workspace, email=email, responded_at__isnull=True
            ).first()

            if existing_invite is not None:
                existing_invite.role = legacy_role
                existing_invite.role_ref = role
                existing_invite.save()
                invitation = existing_invite
                outcome = "updated"
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

            results.append(
                {
                    "email": email,
                    "status": outcome,
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
