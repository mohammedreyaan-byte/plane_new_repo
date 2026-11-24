# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Focused PLN-013 tests for durable denial and admin-override audit."""

import pytest
from rest_framework.test import APIClient

from plane.db.models import APIToken, IssueActivity, WorkflowTransition
from plane.tests.workflow_helpers import (
    DEVELOPER,
    QA,
    client_for,
    make_issue,
    make_project,
    make_user,
    state_of,
)
from plane.utils.workflow.transition import WORKFLOW_DENIED_FIELD, WORKFLOW_OVERRIDE_FIELD

pytestmark = pytest.mark.contract


def base(ws, project):
    return f"/api/workspaces/{ws.slug}/projects/{project.id}"


@pytest.fixture
def project(db, workspace, create_user):
    return make_project(workspace, create_user, governed=True)


def patch_state(client, ws, project, issue, name):
    return client.patch(
        f"{base(ws, project)}/issues/{issue.id}/",
        {"state_id": str(state_of(project, name).id)},
        format="json",
    )


@pytest.mark.django_db
def test_denial_is_audited_and_hidden_from_non_admins(workspace, project, create_user):
    bug = make_issue(project, "bug", "In Testing")
    dev = make_user(workspace, project, DEVELOPER)
    dev_client = client_for(dev)

    denied = patch_state(dev_client, workspace, project, bug, "Tested")
    assert denied.status_code == 403
    assert denied.data["error"]["code"] == "transition_forbidden"
    bug.refresh_from_db()
    assert bug.state.name == "In Testing"

    row = IssueActivity.objects.filter(issue=bug, field=WORKFLOW_DENIED_FIELD).first()
    assert row is not None
    assert row.actor_id == dev.id
    assert "transition_forbidden" in row.comment

    history = dev_client.get(f"{base(workspace, project)}/issues/{bug.id}/history/")
    assert history.status_code == 200, history.data
    assert WORKFLOW_DENIED_FIELD not in {item.get("field") for item in history.data}

    audit_url = f"{base(workspace, project)}/workflows/audit/"
    assert dev_client.get(audit_url).status_code == 403
    admin_rows = client_for(create_user).get(audit_url)
    assert admin_rows.status_code == 200, admin_rows.data
    assert [row["field"] for row in admin_rows.data] == [WORKFLOW_DENIED_FIELD]


@pytest.mark.django_db
def test_admin_override_writes_durable_audit(workspace, project, create_user):
    edge = WorkflowTransition.objects.get(
        workflow__project=project,
        workflow__issue_type__key="bug",
        from_state__name="In Testing",
        to_state__name="Tested",
    )
    edge.admin_override = True
    edge.allowed_roles = ["qa"]
    edge.save(update_fields=["admin_override", "allowed_roles"])

    bug = make_issue(project, "bug", "In Testing")
    response = patch_state(client_for(create_user), workspace, project, bug, "Tested")
    assert response.status_code == 204

    row = IssueActivity.objects.filter(issue=bug, field=WORKFLOW_OVERRIDE_FIELD).first()
    assert row is not None
    assert str(edge.id) in row.comment
    assert "admin_override" in row.comment

    audit_rows = client_for(create_user).get(f"{base(workspace, project)}/workflows/audit/")
    assert audit_rows.status_code == 200, audit_rows.data
    assert WORKFLOW_OVERRIDE_FIELD in {row["field"] for row in audit_rows.data}


@pytest.mark.django_db
def test_service_token_developer_denied_and_qa_allowed_via_v1(workspace, project):
    bug = make_issue(project, "bug", "In Testing")
    # API keys are accepted by the v1 surface; the app surface is session-only.
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/issues/{bug.id}/"
    payload = {"state_id": str(state_of(project, "Tested").id)}

    def api_key_client(user, token_value):
        APIToken.objects.create(user=user, label="transition-test", token=token_value)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=token_value)
        return client

    dev_client = api_key_client(make_user(workspace, project, DEVELOPER), "pln013-dev-token")
    denied = dev_client.patch(url, payload, format="json")
    assert denied.status_code == 403
    assert denied.data["error"]["code"] == "transition_forbidden"
    assert IssueActivity.objects.filter(issue=bug, field=WORKFLOW_DENIED_FIELD).exists()

    qa_client = api_key_client(make_user(workspace, project, QA), "pln013-qa-token")
    allowed = qa_client.patch(url, payload, format="json")
    assert allowed.status_code == 200
    bug.refresh_from_db()
    assert bug.state.name == "Tested"


@pytest.mark.django_db
def test_bulk_denial_is_audited_after_rollback(workspace, project):
    bug = make_issue(project, "bug", "In Testing")
    dev_client = client_for(make_user(workspace, project, DEVELOPER))

    response = dev_client.post(
        f"{base(workspace, project)}/bulk-operation-issues/",
        {
            "issue_ids": [str(bug.id)],
            "properties": {"state_id": str(state_of(project, "Tested").id)},
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["failed"][0]["code"] == "transition_forbidden"
    assert IssueActivity.objects.filter(
        issue=bug,
        field=WORKFLOW_DENIED_FIELD,
        comment__contains="source=bulk",
    ).exists()
    bug.refresh_from_db()
    assert bug.state.name == "In Testing"
