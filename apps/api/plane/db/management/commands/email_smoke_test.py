# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Send the PLN-017 cases 1-4 and print a compact pass/fail table.

The command never prints credentials or message bodies. Invitation rows created
for the smoke run are always removed, including when a case fails.
"""

# Python imports
from datetime import datetime
from uuid import uuid4

# Django imports
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError
from django.core.validators import validate_email

# Third party imports
import jwt

# Module imports
from plane.bgtasks.project_invitation_task import project_invitation
from plane.bgtasks.workspace_invitation_task import workspace_invitation
from plane.db.models import (
    Project,
    ProjectMemberInvite,
    User,
    Workspace,
    WorkspaceMemberInvite,
)
from plane.utils.smtp import (
    SMTPConfigurationError,
    describe_smtp_error,
    email_test_mode_enabled,
    send_email_message,
)


class Command(BaseCommand):
    """Exercise the admin test and invitation paths through shared helpers."""

    help = "Send PLN-017 cases 1-4 (admin test, workspace invites, project invite)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            action="append",
            default=[],
            dest="recipients",
            help="Recipient address; repeat for multiple mailboxes.",
        )
        parser.add_argument("--workspace-slug", type=str, default="", help="Workspace used for invitation cases.")
        parser.add_argument("--project-id", type=str, default="", help="Project used for case 4.")
        parser.add_argument("--skip-project", action="store_true", help="Skip the project invitation case.")
        parser.add_argument("--dry-run", action="store_true", help="Print the plan without sending or writing rows.")

    def handle(self, *args, **options):
        recipients = [str(value).strip() for value in (options.get("recipients") or []) if str(value).strip()]
        dry_run = bool(options.get("dry_run"))
        results = []

        if not recipients and not dry_run:
            raise CommandError("At least one --to recipient is required (or use --dry-run).")
        for recipient in recipients:
            try:
                validate_email(recipient)
            except ValidationError:
                raise CommandError("Every --to value must be a valid email address.") from None

        current_site = str(getattr(settings, "WEB_URL", "http://localhost") or "http://localhost").rstrip("/")
        workspace = None
        if options.get("workspace_slug"):
            workspace = Workspace.objects.filter(slug=options["workspace_slug"]).first()
            if workspace is None:
                raise CommandError("The supplied --workspace-slug does not exist.")
        else:
            workspace = Workspace.objects.order_by("created_at").first()

        project = None
        if options.get("project_id") and workspace is not None:
            project = Project.objects.filter(pk=options["project_id"], workspace=workspace).first()
            if project is None:
                raise CommandError("The supplied --project-id does not exist in the workspace.")
        elif workspace is not None:
            project = Project.objects.filter(workspace=workspace).order_by("created_at").first()

        def recipient_for(index):
            return recipients[index % len(recipients)] if recipients else "recipient@example.invalid"

        def record(case, recipient, passed, detail="", skipped=False):
            state = "SKIP" if skipped else ("PASS" if passed else "FAIL")
            results.append(state)
            shown = "test inbox" if email_test_mode_enabled() else recipient
            self.stdout.write(f"{case:<42} {state:<5} {shown:<40} {detail[:80]}")

        self.stdout.write("PLN-017 email smoke test")
        if email_test_mode_enabled():
            self.stdout.write("EMAIL_TEST_MODE is on: all messages are redirected to the configured test inbox.")
        self.stdout.write(f"{'CASE':<42} {'STATE':<5} {'RECIPIENT':<40} DETAIL")

        if dry_run:
            for case in (
                "1. Admin send test email",
                "2. Workspace invitation",
                "3. Existing user added to second workspace",
                "4. Project invitation",
            ):
                record(case, recipient_for(0), True, "dry run, nothing sent")
            self.stdout.write("Dry run complete; no messages sent and no invitations created.")
            return

        if workspace is None:
            record("1. Admin send test email", recipient_for(0), False, "No workspace available")
            for case in (
                "2. Workspace invitation",
                "3. Existing user added to second workspace",
                "4. Project invitation",
            ):
                record(case, recipient_for(0), False, "No workspace available")
            raise CommandError("Create a workspace before running the smoke test.")

        # Case 1: the same sender path used by the admin test endpoint.
        try:
            send_email_message(
                subject="Email Notification from Plane",
                body="This is a sample email notification sent from Plane application.",
                recipients=[recipient_for(0)],
            )
            record("1. Admin send test email", recipient_for(0), True)
        except SMTPConfigurationError as error:
            record("1. Admin send test email", recipient_for(0), False, str(error))

        # Case 2: invitation to a new address in the chosen workspace.
        invite_email = recipient_for(1)
        invite = None
        try:
            invite = WorkspaceMemberInvite.objects.create(
                email=invite_email,
                workspace=workspace,
                token=jwt.encode(
                    {"email": invite_email, "timestamp": datetime.now().timestamp(), "smoke": uuid4().hex},
                    settings.SECRET_KEY,
                    algorithm="HS256",
                ),
                role=5,
                created_by=workspace.owner,
            )
            workspace_invitation(
                invite_email,
                str(workspace.pk),
                invite.token,
                current_site,
                workspace.owner.email,
            )
            record("2. Workspace invitation", invite_email, True)
        except Exception as error:  # noqa: BLE001 - smoke command reports all case failures
            record("2. Workspace invitation", invite_email, False, describe_smtp_error(error))
        finally:
            if invite is not None:
                WorkspaceMemberInvite.objects.filter(pk=invite.pk).delete()

        # Case 3: an existing user is invited to a second workspace.
        second_workspace = (
            Workspace.objects.exclude(pk=workspace.pk).exclude(owner=workspace.owner).order_by("created_at").first()
        )
        existing_user = (
            User.objects.filter(is_active=True).exclude(pk=workspace.owner_id).order_by("created_at").first()
        )
        if second_workspace is None or existing_user is None:
            record("3. Existing user added to second workspace", "", True, "no second workspace/user", skipped=True)
        else:
            second_invite = None
            try:
                second_invite = WorkspaceMemberInvite.objects.create(
                    email=existing_user.email,
                    workspace=second_workspace,
                    token=jwt.encode(
                        {"email": existing_user.email, "timestamp": datetime.now().timestamp(), "smoke": uuid4().hex},
                        settings.SECRET_KEY,
                        algorithm="HS256",
                    ),
                    role=5,
                    created_by=second_workspace.owner,
                )
                workspace_invitation(
                    existing_user.email,
                    str(second_workspace.pk),
                    second_invite.token,
                    current_site,
                    second_workspace.owner.email,
                )
                record("3. Existing user added to second workspace", existing_user.email, True)
            except Exception as error:  # noqa: BLE001
                record(
                    "3. Existing user added to second workspace",
                    existing_user.email,
                    False,
                    describe_smtp_error(error),
                )
            finally:
                if second_invite is not None:
                    WorkspaceMemberInvite.objects.filter(pk=second_invite.pk).delete()

        # Case 4: project invitation, unless explicitly skipped.
        if options.get("skip_project"):
            record("4. Project invitation", "", True, "--skip-project", skipped=True)
        elif project is None:
            record("4. Project invitation", "", True, "no project available", skipped=True)
        else:
            project_invite = None
            project_email = recipient_for(2)
            try:
                project_invite = ProjectMemberInvite.objects.create(
                    email=project_email,
                    project=project,
                    workspace=workspace,
                    token=jwt.encode(
                        {"email": project_email, "timestamp": datetime.now().timestamp(), "smoke": uuid4().hex},
                        settings.SECRET_KEY,
                        algorithm="HS256",
                    ),
                    role=5,
                    created_by=workspace.owner,
                )
                project_invitation(
                    project_email,
                    str(project.pk),
                    project_invite.token,
                    current_site,
                    workspace.owner.email,
                )
                record("4. Project invitation", project_email, True)
            except Exception as error:  # noqa: BLE001
                record("4. Project invitation", project_email, False, describe_smtp_error(error))
            finally:
                if project_invite is not None:
                    ProjectMemberInvite.objects.filter(pk=project_invite.pk).delete()

        failed = results.count("FAIL")
        self.stdout.write(f"Summary: {results.count('PASS')} passed, {failed} failed, {results.count('SKIP')} skipped")
        if failed:
            raise CommandError(f"{failed} smoke case(s) failed")
