# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json
from datetime import timedelta

# Third party imports
from celery import shared_task
from django.db.models import Q

# Django imports
from django.utils import timezone

# Module imports
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue, Project, State, WorkflowState
from plane.utils.exception_logger import log_exception
from plane.utils.workflow.transition import WorkflowError, get_workflow_for_issue, transition_issue


@shared_task
def archive_and_close_old_issues():
    archive_old_issues()
    close_old_issues()


def archive_old_issues():
    try:
        # Get all the projects whose archive_in is greater than 0
        projects = Project.objects.filter(archive_in__gt=0)

        for project in projects:
            project_id = project.id
            archive_in = project.archive_in

            # Get all the issues whose updated_at in less that the archive_in month
            issues = Issue.issue_objects.filter(
                Q(
                    project=project_id,
                    archived_at__isnull=True,
                    updated_at__lte=(timezone.now() - timedelta(days=archive_in * 30)),
                    state__group__in=["completed", "cancelled"],
                ),
                Q(issue_cycle__isnull=True)
                | (Q(issue_cycle__cycle__end_date__lt=timezone.now()) & Q(issue_cycle__isnull=False)),
                Q(issue_module__isnull=True)
                | (Q(issue_module__module__target_date__lt=timezone.now()) & Q(issue_module__isnull=False)),
            ).filter(
                Q(issue_intake__status=1)
                | Q(issue_intake__status=-1)
                | Q(issue_intake__status=2)
                | Q(issue_intake__isnull=True)
            )

            # Check if Issues
            if issues:
                # Set the archive time to current time
                archive_at = timezone.now().date()

                issues_to_update = []
                for issue in issues:
                    issue.archived_at = archive_at
                    issues_to_update.append(issue)

                # Bulk Update the issues and log the activity
                if issues_to_update:
                    Issue.objects.bulk_update(issues_to_update, ["archived_at"], batch_size=100)
                    _ = [
                        issue_activity.delay(
                            type="issue.activity.updated",
                            requested_data=json.dumps({"archived_at": str(archive_at), "automation": True}),
                            actor_id=str(project.created_by_id),
                            issue_id=issue.id,
                            project_id=project_id,
                            current_instance=json.dumps({"archived_at": None}),
                            subscriber=False,
                            epoch=int(timezone.now().timestamp()),
                            notification=True,
                        )
                        for issue in issues_to_update
                    ]
        return
    except Exception as e:
        log_exception(e)
        return


def close_old_issues():
    try:
        # Get all the projects whose close_in is greater than 0
        projects = Project.objects.filter(close_in__gt=0).select_related("default_state", "created_by", "workspace__owner")

        for project in projects:
            project_id = project.id
            close_in = project.close_in

            # Get all the issues whose updated_at in less that the close_in month
            issues = Issue.issue_objects.filter(
                Q(
                    project=project_id,
                    archived_at__isnull=True,
                    updated_at__lte=(timezone.now() - timedelta(days=close_in * 30)),
                    state__group__in=["backlog", "unstarted", "started"],
                ),
                Q(issue_cycle__isnull=True)
                | (Q(issue_cycle__cycle__end_date__lt=timezone.now()) & Q(issue_cycle__isnull=False)),
                Q(issue_module__isnull=True)
                | (Q(issue_module__module__target_date__lt=timezone.now()) & Q(issue_module__isnull=False)),
            ).filter(
                Q(issue_intake__status=1)
                | Q(issue_intake__status=-1)
                | Q(issue_intake__status=2)
                | Q(issue_intake__isnull=True)
            )

            # Check if Issues
            if issues:
                actor = project.created_by or project.workspace.owner
                # Resolve the project default as the legacy destination. For governed
                # projects, close through a final state in the item's own workflow.
                fallback_close_state = project.default_state or State.objects.filter(
                    project=project, group="cancelled"
                ).first()
                closed_items = []
                for issue in issues:
                    workflow = get_workflow_for_issue(issue)
                    close_state = fallback_close_state
                    if workflow is not None:
                        final_mapping = (
                            WorkflowState.objects.filter(workflow=workflow, is_final=True)
                            .select_related("state")
                            .order_by("sequence")
                            .first()
                        )
                        close_state = final_mapping.state if final_mapping else None
                    if close_state is None or actor is None:
                        continue
                    try:
                        updated_issue, old_state_id = transition_issue(
                            issue.id, close_state.id, actor, source="automation"
                        )
                    except WorkflowError:
                        # Keep the item unchanged if the configured workflow has no
                        # valid route to a final state or the project creator cannot
                        # perform that transition.
                        continue
                    if old_state_id != updated_issue.state_id:
                        closed_items.append((updated_issue, old_state_id))

                # Record the same activity/notification event as the other workflow
                # transition entry points, but only for moves accepted by the engine.
                for issue, old_state_id in closed_items:
                    issue_activity.delay(
                        type="issue.activity.updated",
                        requested_data=json.dumps({"state_id": str(issue.state_id), "automation": True}),
                        actor_id=str(actor.id),
                        issue_id=issue.id,
                        project_id=project_id,
                        current_instance=json.dumps({"state_id": str(old_state_id)}),
                        subscriber=False,
                        epoch=int(timezone.now().timestamp()),
                        notification=True,
                    )
        return
    except Exception as e:
        log_exception(e)
        return
