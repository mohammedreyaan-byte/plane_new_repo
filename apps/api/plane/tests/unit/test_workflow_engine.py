# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for the workflow transition engine (PLN-005, PLN-006, PLN-013)."""

import pytest

from plane.db.models import Issue, State, Workflow, WorkflowState, WorkflowTransition
from plane.tests.workflow_helpers import (
    ADMIN,
    DEVELOPER,
    GUEST,
    MEMBER,
    QA,
    ROLE_KEYS,
    VIEWER,
    make_issue,
    make_project,
    make_user,
    state_of,
)
from plane.utils.workflow.seeds import WORKFLOW_SEEDS
from plane.utils.workflow.service import seed_project_workflows
from plane.utils.workflow.transition import WorkflowError, validate_transition

pytestmark = pytest.mark.unit

ALL_ROLES = [ADMIN, MEMBER, DEVELOPER, QA, VIEWER, GUEST]


@pytest.fixture
def project(db, workspace, create_user):
    return make_project(workspace, create_user)


def _try(issue, to_state, user):
    try:
        validate_transition(issue, to_state, user)
        return "allowed"
    except WorkflowError as error:
        return error.code


def _expected(role, allowed_roles):
    """Oracle taken from the PLN-013 rule: viewer/guest never move items; empty list = any contributor."""
    if role in (VIEWER, GUEST):
        return "transition_forbidden"
    if not allowed_roles or ROLE_KEYS[role] in allowed_roles or role == ADMIN:
        return "allowed"
    return "transition_forbidden"


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------


def test_bug_workflow_has_the_eight_states_and_fifteen_transitions(project):
    workflow = Workflow.objects.get(project=project, issue_type__key="bug")
    names = list(
        WorkflowState.objects.filter(workflow=workflow).order_by("sequence").values_list("state__name", flat=True)
    )
    assert names == ["New", "In Progress", "Code Review", "In Testing", "Tested", "Closed", "Reopened", "Rejected"]
    assert WorkflowTransition.objects.filter(workflow=workflow).count() == 15
    assert WorkflowState.objects.get(workflow=workflow, state__name="New").is_initial
    finals = set(WorkflowState.objects.filter(workflow=workflow, is_final=True).values_list("state__name", flat=True))
    assert finals == {"Closed", "Rejected"}


@pytest.mark.parametrize("key", ["bug", "task", "story", "epic"])
def test_all_four_workflows_are_seeded_with_one_initial_state(project, key):
    workflow = Workflow.objects.get(project=project, issue_type__key=key)
    assert workflow.is_default and workflow.is_active
    assert WorkflowState.objects.filter(workflow=workflow, is_initial=True).count() == 1
    assert WorkflowTransition.objects.filter(workflow=workflow).count() == len(WORKFLOW_SEEDS[key]["transitions"])


def test_seed_is_idempotent(project):
    before = (
        Workflow.objects.count(),
        WorkflowState.objects.count(),
        WorkflowTransition.objects.count(),
        State.objects.filter(project=project).count(),
    )
    seed_project_workflows(project)
    seed_project_workflows(project)
    after = (
        Workflow.objects.count(),
        WorkflowState.objects.count(),
        WorkflowTransition.objects.count(),
        State.objects.filter(project=project).count(),
    )
    assert before == after


def test_seed_reuses_existing_states_by_name(db, workspace, create_user):
    project = make_project(workspace, create_user, identifier="RE", governed=False)
    existing = State.objects.create(
        project=project, workspace=workspace, name="In Progress", group="started", color="#fff"
    )
    seed_project_workflows(project)
    assert State.objects.filter(project=project, name="In Progress").count() == 1
    assert State.objects.get(project=project, name="In Progress").id == existing.id


# ---------------------------------------------------------------------------
# The full Bug matrix: every transition x every role
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_bug_transition_for_every_role(role, project, workspace):
    user = make_user(workspace, project, role)
    for from_name, to_name, allowed_roles in WORKFLOW_SEEDS["bug"]["transitions"]:
        issue = make_issue(project, "bug", from_name, name=f"{from_name}->{to_name}")
        result = _try(issue, state_of(project, to_name), user)
        assert result == _expected(role, allowed_roles), (ROLE_KEYS[role], from_name, to_name, result)


@pytest.mark.django_db
def test_edges_that_are_not_in_the_workflow_are_rejected_for_everyone(project, workspace):
    admin = make_user(workspace, project, ADMIN)
    issue = make_issue(project, "bug", "New")
    assert _try(issue, state_of(project, "Closed"), admin) == "transition_not_allowed"
    assert _try(issue, state_of(project, "Tested"), admin) == "transition_not_allowed"


# ---------------------------------------------------------------------------
# The rule the product owner cares about
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_developer_cannot_set_tested_but_qa_and_admin_can(project, workspace):
    developer, qa, admin = (make_user(workspace, project, r) for r in (DEVELOPER, QA, ADMIN))
    issue = make_issue(project, "bug", "In Testing")
    tested = state_of(project, "Tested")

    with pytest.raises(WorkflowError) as denied:
        validate_transition(issue, tested, developer)
    assert denied.value.code == "transition_forbidden"
    assert denied.value.status_code == 403
    assert set(denied.value.error_details["required_roles"]) == {"qa", "admin"}

    assert _try(issue, tested, qa) == "allowed"
    assert _try(issue, tested, admin) == "allowed"


@pytest.mark.django_db
def test_admin_override_can_be_switched_off_per_transition(project, workspace):
    admin = make_user(workspace, project, ADMIN)
    workflow = Workflow.objects.get(project=project, issue_type__key="bug")
    WorkflowTransition.objects.filter(workflow=workflow, from_state__name="In Testing", to_state__name="Tested").update(
        admin_override=False, allowed_roles=["qa"]
    )
    issue = make_issue(project, "bug", "In Testing")
    assert _try(issue, state_of(project, "Tested"), admin) == "transition_forbidden"


@pytest.mark.django_db
def test_denial_lists_only_what_the_user_may_do(project, workspace):
    developer = make_user(workspace, project, DEVELOPER)
    issue = make_issue(project, "bug", "In Testing")
    with pytest.raises(WorkflowError) as denied:
        validate_transition(issue, state_of(project, "Tested"), developer)
    targets = {t["to_state_name"] for t in denied.value.error_details["allowed_transitions"]}
    assert targets == {"In Progress"}


# ---------------------------------------------------------------------------
# Comment and required fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_comment_required(project, workspace):
    qa = make_user(workspace, project, QA)
    workflow = Workflow.objects.get(project=project, issue_type__key="bug")
    WorkflowTransition.objects.filter(workflow=workflow, from_state__name="Tested", to_state__name="Closed").update(
        requires_comment=True
    )
    issue = make_issue(project, "bug", "Tested")
    with pytest.raises(WorkflowError) as error:
        validate_transition(issue, state_of(project, "Closed"), qa)
    assert error.value.code == "comment_required"
    assert validate_transition(issue, state_of(project, "Closed"), qa, comment="Verified on build 42")


@pytest.mark.django_db
def test_required_fields(project, workspace):
    member = make_user(workspace, project, MEMBER)
    workflow = Workflow.objects.get(project=project, issue_type__key="bug")
    WorkflowTransition.objects.filter(workflow=workflow, from_state__name="New", to_state__name="In Progress").update(
        required_fields=["assignee"]
    )
    issue = make_issue(project, "bug", "New")
    with pytest.raises(WorkflowError) as error:
        validate_transition(issue, state_of(project, "In Progress"), member)
    assert error.value.code == "fields_required"
    assert error.value.error_details["missing_fields"] == ["assignee"]


# ---------------------------------------------------------------------------
# Governed or not
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_project_without_types_enabled_keeps_free_state_changes(workspace, create_user):
    project = make_project(workspace, create_user, identifier="FR", governed=False)
    seed_project_workflows(project)  # rows exist but the project has not enabled types
    developer = make_user(workspace, project, DEVELOPER)
    issue = make_issue(project, "bug", "In Testing")
    assert validate_transition(issue, state_of(project, "Closed"), developer) is None


@pytest.mark.django_db
def test_item_in_a_state_outside_its_workflow_can_only_return_to_the_start(project, workspace):
    member = make_user(workspace, project, MEMBER)
    issue = make_issue(project, "bug", "Todo")  # "Todo" is not a Bug workflow state
    assert _try(issue, state_of(project, "New"), member) == "allowed"
    assert _try(issue, state_of(project, "Closed"), member) == "state_not_in_workflow"


@pytest.mark.django_db
def test_state_from_another_workflow_is_rejected(project, workspace):
    member = make_user(workspace, project, MEMBER)
    issue = make_issue(project, "bug", "New")
    assert _try(issue, state_of(project, "Backlog"), member) == "state_not_in_workflow"


@pytest.mark.django_db
def test_epic_cannot_complete_with_open_children(project, workspace):
    qa = make_user(workspace, project, QA)
    epic = make_issue(project, "epic", "In Progress", name="Epic")
    child = make_issue(project, "task", "Todo", name="Child", parent=epic)
    done = state_of(project, "Done")
    with pytest.raises(WorkflowError) as error:
        validate_transition(epic, done, qa)
    assert error.value.code == "epic_has_open_children"
    assert error.value.error_details["count"] == 1

    Issue.objects.filter(pk=child.pk).update(state=done)
    assert _try(epic, done, qa) == "allowed"


@pytest.mark.django_db
def test_issue_filterset_understands_type_filters(workspace, create_user):
    from plane.db.models import Issue
    from plane.utils.filters.filterset import IssueFilterSet

    project = make_project(workspace, create_user, identifier="FS")
    bug = make_issue(project, "bug", "New", name="b")
    make_issue(project, "task", "New", name="t")
    qs = IssueFilterSet(data={"type_id__in": str(bug.type_id)}, queryset=Issue.objects.filter(project=project)).qs
    assert [i.id for i in qs] == [bug.id]
    qs = IssueFilterSet(data={"type_id": str(bug.type_id)}, queryset=Issue.objects.filter(project=project)).qs
    assert [i.id for i in qs] == [bug.id]
