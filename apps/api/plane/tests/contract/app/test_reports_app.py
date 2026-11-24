# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for project reports (PLN-019)."""

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.db import connection

from plane.db.models import (
    Cycle,
    CycleIssue,
    Issue,
    IssueLabel,
    Label,
    Module,
    ModuleIssue,
    Project,
    State,
)
from plane.tests.workflow_helpers import (
    ADMIN,
    DEVELOPER,
    GUEST,
    MEMBER,
    QA,
    VIEWER,
    client_for,
    make_issue,
    make_project,
    make_user,
    state_of,
)
from plane.utils.reports.csv_export import escape_cell

pytestmark = pytest.mark.contract


def url(ws, project, tail=""):
    return f"/api/workspaces/{ws.slug}/projects/{project.id}/reports/{tail}"


def mk_state(project, name, group, sequence=1):
    return State.objects.create(name=name, project=project, workspace=project.workspace, group=group, sequence=sequence)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def project(db, workspace, create_user):
    project = make_project(workspace, create_user, governed=True)
    Project.objects.filter(pk=project.pk).update(timezone="Asia/Kolkata")
    project.refresh_from_db()
    return project


@pytest.fixture
def states(project):
    """The states seeded by the bug workflow (New, In Progress, In Testing, Closed, Rejected ...)."""
    return {
        "new": state_of(project, "New"),
        "dev": state_of(project, "In Progress"),
        "test": state_of(project, "In Testing"),
        "done": state_of(project, "Closed"),
        "rejected": state_of(project, "Rejected"),
    }


@pytest.fixture
def admin_client(create_user):
    return client_for(create_user)


def bug(project, state, priority="none", name="bug", **extra):
    issue = make_issue(project, "bug", None, name=name)
    Issue.objects.filter(pk=issue.pk).update(state=state, priority=priority, **extra)
    issue.refresh_from_db()
    return issue


@pytest.fixture
def fixture_bugs(project, states):
    """Open: 2 new, 1 dev, 1 testing. Resolved 2. Cancelled 1. Plus noise that must not count."""
    now = datetime.now(dt_timezone.utc)
    bug(project, states["new"], "high", "n1")
    bug(project, states["new"], "none", "n2")
    bug(project, states["dev"], "urgent", "d1")
    bug(project, states["test"], "low", "t1")
    bug(project, states["done"], "high", "r1", completed_at=now)
    bug(project, states["done"], "low", "r2", completed_at=now)
    bug(project, states["rejected"], "medium", "c1")
    # Noise: archived, deleted, draft, a task (not a bug)
    bug(project, states["new"], "high", "archived", archived_at=now.date())
    bug(project, states["new"], "high", "deleted", deleted_at=now)
    bug(project, states["new"], "high", "draft", is_draft=True)
    t = make_issue(project, "task", None, name="a task")
    Issue.objects.filter(pk=t.pk).update(state=states["new"])


def rows_by(result, key):
    return {r[key]: r for r in result["rows"]}


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_open_bugs_by_state_matches_a_manual_count(workspace, project, fixture_bugs, admin_client):
    response = admin_client.get(url(workspace, project, "bugs-by-state/"))
    assert response.status_code == 200, response.data
    by_state = rows_by(response.data, "state")
    assert by_state["New"]["count"] == 2
    assert by_state["In Progress"]["count"] == 1
    assert by_state["In Testing"]["count"] == 1
    assert "Closed" not in by_state and "Rejected" not in by_state
    assert response.data["total"] == 4
    # Manual count straight from the database
    manual = Issue.issue_objects.filter(
        project=project, type__key="bug", state__group__in=["backlog", "unstarted", "started"]
    ).count()
    assert manual == response.data["total"]


@pytest.mark.django_db
def test_cancelled_is_reported_separately_never_as_resolved(workspace, project, fixture_bugs, admin_client):
    response = admin_client.get(url(workspace, project, "bugs-by-state/"))
    summary = response.data["meta"]["summary"]
    assert summary == {"open": 4, "resolved": 2, "cancelled": 1}
    assert response.data["meta"]["timezone"] == "Asia/Kolkata"
    assert "open_definition" in response.data["meta"]


@pytest.mark.django_db
def test_bugs_by_priority_has_five_buckets_and_none_is_its_own(workspace, project, fixture_bugs, admin_client):
    response = admin_client.get(url(workspace, project, "bugs-by-priority/"))
    assert response.status_code == 200
    assert [r["priority"] for r in response.data["rows"]] == ["urgent", "high", "medium", "low", "none"]
    by_priority = rows_by(response.data, "priority")
    assert by_priority["urgent"]["count"] == 1
    assert by_priority["high"]["count"] == 1
    assert by_priority["medium"]["count"] == 0
    assert by_priority["low"]["count"] == 1
    assert by_priority["none"]["count"] == 1
    assert response.data["total"] == 4


@pytest.mark.django_db
def test_reopened_bug_counts_as_open_again(workspace, project, states, admin_client, create_user):
    issue = bug(project, states["new"], "none", "will close")
    issue.state = states["done"]
    issue.save()
    issue.refresh_from_db()
    assert issue.completed_at is not None
    first = admin_client.get(url(workspace, project, "bugs-by-state/")).data
    assert first["total"] == 0 and first["meta"]["summary"]["resolved"] == 1

    cache.clear()
    issue.state = states["dev"]
    issue.save()
    issue.refresh_from_db()
    assert issue.completed_at is None
    second = admin_client.get(url(workspace, project, "bugs-by-state/")).data
    assert second["total"] == 1 and second["meta"]["summary"]["resolved"] == 0


@pytest.mark.django_db
def test_moving_a_bug_to_done_removes_it_from_open_and_adds_to_resolved(workspace, project, states, admin_client):
    issue = bug(project, states["test"], "high", "ready")
    before = admin_client.get(url(workspace, project, "bugs-by-state/")).data
    assert before["total"] == 1
    issue.state = states["done"]
    issue.save()
    # Saving through the ORM bumps the cache version, so no stale numbers even inside the TTL.
    after = admin_client.get(url(workspace, project, "bugs-by-state/")).data
    assert after["total"] == 0
    assert after["meta"]["summary"]["resolved"] == 1


@pytest.mark.django_db
def test_soft_deleted_state_keeps_its_name_in_reports(workspace, project, states, admin_client):
    bug(project, states["dev"], "low", "orphan")
    State.objects.filter(pk=states["dev"].pk).update(deleted_at=datetime.now(dt_timezone.utc))
    response = admin_client.get(url(workspace, project, "bugs-by-state/"))
    assert response.status_code == 200
    assert rows_by(response.data, "state")["In Progress"]["count"] == 1


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_filters_combine(workspace, project, states, fixture_bugs, admin_client, create_user):
    target = Issue.issue_objects.get(project=project, name="d1")
    from plane.db.models import IssueAssignee

    IssueAssignee.objects.create(issue=target, assignee=create_user, project=project, workspace=workspace)
    label = Label.objects.create(name="ui", project=project, workspace=workspace)
    IssueLabel.objects.create(issue=target, label=label, project=project, workspace=workspace)
    response = admin_client.get(
        url(workspace, project, "bugs-by-state/"),
        {"assignee_id": str(create_user.id), "priority": "urgent", "label_id": str(label.id)},
    )
    assert response.status_code == 200
    assert response.data["total"] == 1
    none_match = admin_client.get(
        url(workspace, project, "bugs-by-state/"), {"assignee_id": str(create_user.id), "priority": "low"}
    )
    assert none_match.data["total"] == 0


@pytest.mark.django_db
def test_type_filter_overrides_bug_default(workspace, project, states, admin_client):
    make_issue(project, "story", None, name="s1")
    Issue.objects.filter(name="s1").update(state=states["new"])
    bug(project, states["new"], "none", "b1")
    from plane.tests.workflow_helpers import type_of

    story = type_of(workspace, "story")
    only_story = admin_client.get(url(workspace, project, "bugs-by-state/"), {"type_id": str(story.id)})
    assert only_story.data["total"] == 1
    everything = admin_client.get(url(workspace, project, "bugs-by-state/"), {"type_id": "all"})
    assert everything.data["total"] == 2


@pytest.mark.django_db
def test_invalid_filters_and_two_year_cap(workspace, project, admin_client):
    bad_uuid = admin_client.get(url(workspace, project, "bugs-by-state/"), {"assignee_id": "nope"})
    assert bad_uuid.status_code == 400 and bad_uuid.data["error"]["code"] == "invalid_filter"
    bad_priority = admin_client.get(url(workspace, project, "bugs-by-state/"), {"priority": "critical"})
    assert bad_priority.status_code == 400
    too_long = admin_client.get(
        url(workspace, project, "created-vs-resolved/"), {"date_from": "2020-01-01", "date_to": "2024-01-01"}
    )
    assert too_long.status_code == 400 and too_long.data["error"]["code"] == "date_range_too_large"
    backwards = admin_client.get(
        url(workspace, project, "created-vs-resolved/"), {"date_from": "2026-02-01", "date_to": "2026-01-01"}
    )
    assert backwards.status_code == 400


# ---------------------------------------------------------------------------
# Created vs resolved and time zones
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_created_vs_resolved_uses_project_timezone_boundary(workspace, project, states, admin_client):
    ist = ZoneInfo("Asia/Kolkata")
    # Sunday 2026-11-08 23:30 IST belongs to the week starting Monday 2026-11-02, even though
    # in UTC it is already 18:00 the same day (and a naive UTC bucket would agree) - and
    # Monday 2026-11-09 00:30 IST is 19:00 UTC on Sunday, which a UTC bucket puts in the old week.
    late_sunday = datetime(2026, 11, 8, 23, 30, tzinfo=ist)
    early_monday = datetime(2026, 11, 9, 0, 30, tzinfo=ist)
    a = bug(project, states["new"], "none", "late sunday")
    b = bug(project, states["new"], "none", "early monday")
    Issue.objects.filter(pk=a.pk).update(created_at=late_sunday)
    Issue.objects.filter(pk=b.pk).update(created_at=early_monday)
    response = admin_client.get(
        url(workspace, project, "created-vs-resolved/"), {"date_from": "2026-11-02", "date_to": "2026-11-15"}
    )
    assert response.status_code == 200, response.data
    by_period = rows_by(response.data, "period")
    assert by_period["2026-11-02"]["created"] == 1
    assert by_period["2026-11-09"]["created"] == 1


@pytest.mark.django_db
def test_created_vs_resolved_counts_resolution_by_completed_at(workspace, project, states, admin_client):
    ist = ZoneInfo("Asia/Kolkata")
    created = datetime(2026, 11, 3, 10, 0, tzinfo=ist)
    done = datetime(2026, 11, 11, 10, 0, tzinfo=ist)
    issue = bug(project, states["done"], "none", "resolved later", completed_at=done)
    Issue.objects.filter(pk=issue.pk).update(created_at=created)
    response = admin_client.get(
        url(workspace, project, "created-vs-resolved/"), {"date_from": "2026-11-02", "date_to": "2026-11-15"}
    )
    by_period = rows_by(response.data, "period")
    assert by_period["2026-11-02"]["created"] == 1 and by_period["2026-11-02"]["resolved"] == 0
    assert by_period["2026-11-09"]["resolved"] == 1


@pytest.mark.django_db
def test_created_vs_resolved_monthly_and_gap_filling(workspace, project, admin_client):
    response = admin_client.get(
        url(workspace, project, "created-vs-resolved/"),
        {"date_from": "2026-01-15", "date_to": "2026-04-02", "interval": "month"},
    )
    assert [r["period"] for r in response.data["rows"]] == ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]
    assert all(r["created"] == 0 and r["resolved"] == 0 for r in response.data["rows"])


@pytest.mark.django_db
def test_archived_resolved_bug_still_counts_as_resolved(workspace, project, states, admin_client):
    now = datetime.now(dt_timezone.utc)
    bug(project, states["done"], "none", "archived done", completed_at=now, archived_at=now.date())
    response = admin_client.get(url(workspace, project, "bugs-by-state/"))
    assert response.data["total"] == 0
    assert response.data["meta"]["summary"]["resolved"] == 1


# ---------------------------------------------------------------------------
# Legacy projects without types
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_types_disabled_project_falls_back_to_the_bug_label(workspace, create_user, admin_client):
    legacy = make_project(workspace, create_user, identifier="LG", governed=False)
    state = mk_state(legacy, "Open", "started", 1)
    label = Label.objects.create(name="type: bug", project=legacy, workspace=workspace)
    labelled = Issue.objects.create(project=legacy, workspace=workspace, name="labelled", state=state)
    IssueLabel.objects.create(issue=labelled, label=label, project=legacy, workspace=workspace)
    Issue.objects.create(project=legacy, workspace=workspace, name="plain", state=state)
    response = admin_client.get(url(workspace, legacy, "bugs-by-state/"))
    assert response.status_code == 200
    assert response.data["total"] == 1
    assert "deprecation_note" in response.data["meta"]
    assert "type: bug" in response.data["meta"]["deprecation_note"]


# ---------------------------------------------------------------------------
# Cycles and modules
# ---------------------------------------------------------------------------


def make_cycle(project, user, days=6):
    start = datetime.now(dt_timezone.utc) - timedelta(days=3)
    return Cycle.objects.create(
        name="Sprint",
        project=project,
        workspace=project.workspace,
        owned_by=user,
        start_date=start,
        end_date=start + timedelta(days=days),
    )


@pytest.mark.django_db
def test_cycle_burndown_matches_the_existing_cycle_chart(workspace, project, states, admin_client, create_user):
    from plane.utils.analytics_plot import burndown_plot
    from django.db.models import Count, Q

    cycle = make_cycle(project, create_user)
    items = [make_issue(project, "task", None, name=f"t{i}") for i in range(4)]
    for item in items:
        CycleIssue.objects.create(issue=item, cycle=cycle, project=project, workspace=workspace)
    Issue.objects.filter(pk=items[0].pk).update(state=states["done"], completed_at=datetime.now(dt_timezone.utc))
    Issue.objects.filter(pk__in=[i.pk for i in items[1:]]).update(state=states["new"])

    response = admin_client.get(url(workspace, project, "cycle-burndown/"), {"cycle_id": str(cycle.id)})
    assert response.status_code == 200, response.data

    annotated = Cycle.objects.annotate(
        total_issues=Count(
            "issue_cycle__issue__id",
            distinct=True,
            filter=Q(
                issue_cycle__issue__archived_at__isnull=True,
                issue_cycle__issue__is_draft=False,
                issue_cycle__deleted_at__isnull=True,
                issue_cycle__issue__deleted_at__isnull=True,
            ),
        )
    ).get(pk=cycle.pk)
    expected = burndown_plot(
        queryset=annotated, slug=workspace.slug, project_id=project.id, plot_type="issues", cycle_id=cycle.id
    )
    got = {row["date"]: row["remaining"] for row in response.data["rows"]}
    assert got == expected
    assert response.data["total"] == 4


@pytest.mark.django_db
def test_cycle_report_requires_a_cycle_from_this_project(workspace, project, create_user, admin_client):
    missing = admin_client.get(url(workspace, project, "cycle-burndown/"))
    assert missing.status_code == 400 and missing.data["error"]["code"] == "cycle_required"
    other = make_project(workspace, create_user, identifier="OT", governed=True)
    foreign = make_cycle(other, create_user)
    not_found = admin_client.get(url(workspace, project, "cycle-burndown/"), {"cycle_id": str(foreign.id)})
    assert not_found.status_code == 404


@pytest.mark.django_db
def test_cycle_scope_counts_added_and_removed(workspace, project, admin_client, create_user):
    cycle = make_cycle(project, create_user)
    initial = make_issue(project, "task", None, name="initial")
    late = make_issue(project, "task", None, name="late")
    removed = make_issue(project, "task", None, name="removed")
    ci_initial = CycleIssue.objects.create(issue=initial, cycle=cycle, project=project, workspace=workspace)
    ci_late = CycleIssue.objects.create(issue=late, cycle=cycle, project=project, workspace=workspace)
    ci_removed = CycleIssue.objects.create(issue=removed, cycle=cycle, project=project, workspace=workspace)
    CycleIssue.all_objects.filter(pk=ci_initial.pk).update(created_at=cycle.start_date - timedelta(days=1))
    CycleIssue.all_objects.filter(pk=ci_late.pk).update(created_at=cycle.start_date + timedelta(days=1))
    CycleIssue.all_objects.filter(pk=ci_removed.pk).update(
        created_at=cycle.start_date + timedelta(days=1), deleted_at=cycle.start_date + timedelta(days=2)
    )
    response = admin_client.get(url(workspace, project, "cycle-scope/"), {"cycle_id": str(cycle.id)})
    assert response.status_code == 200, response.data
    assert response.data["meta"]["summary"] == {"initial": 1, "added": 2, "removed": 1, "current": 2}


@pytest.mark.django_db
def test_module_progress(workspace, project, states, admin_client):
    module = Module.objects.create(name="Checkout", project=project, workspace=workspace)
    empty = Module.objects.create(name="Empty", project=project, workspace=workspace)
    done = make_issue(project, "task", None, name="done")
    open_one = make_issue(project, "task", None, name="open")
    cancelled = make_issue(project, "task", None, name="cancelled")
    Issue.objects.filter(pk=done.pk).update(state=states["done"])
    Issue.objects.filter(pk=open_one.pk).update(state=states["new"])
    Issue.objects.filter(pk=cancelled.pk).update(state=states["rejected"])
    for issue in (done, open_one, cancelled):
        ModuleIssue.objects.create(issue=issue, module=module, project=project, workspace=workspace)
    response = admin_client.get(url(workspace, project, "module-progress/"))
    assert response.status_code == 200, response.data
    by_name = rows_by(response.data, "module")
    assert by_name["Checkout"]["total"] == 3
    assert by_name["Checkout"]["completed"] == 1
    assert by_name["Checkout"]["cancelled"] == 1
    assert by_name["Checkout"]["progress"] == 33.3
    assert by_name["Empty"]["total"] == 0 and by_name["Empty"]["progress"] == 0
    assert empty.name in by_name


# ---------------------------------------------------------------------------
# Saved reports, sharing, reproducibility
# ---------------------------------------------------------------------------


def save(client, ws, project, **overrides):
    payload = {
        "name": "Open bugs",
        "report_type": "bugs_by_state",
        "filters": {"priority": "high"},
        "chart_type": "bar",
        "is_shared": False,
    }
    payload.update(overrides)
    return client.post(url(ws, project), payload, format="json")


@pytest.mark.django_db
def test_saved_report_roundtrip_and_reproducibility(workspace, project, fixture_bugs, admin_client):
    created = save(admin_client, workspace, project, is_shared=True)
    assert created.status_code == 201, created.data
    assert created.data["filters"]["schema_version"] == 1
    rid = created.data["id"]

    first = admin_client.get(url(workspace, project, f"{rid}/data/")).data
    cache.clear()
    teammate = make_user(workspace, project, MEMBER)
    second = client_for(teammate).get(url(workspace, project, f"{rid}/data/")).data
    assert first["rows"] == second["rows"] and first["total"] == second["total"]
    assert first["definition"]["name"] == "Open bugs"
    # The saved filters are applied (priority=high -> only n1 is open + high)
    assert first["total"] == 1


@pytest.mark.django_db
def test_unshared_report_is_private_to_its_owner(workspace, project, admin_client):
    created = save(admin_client, workspace, project, is_shared=False).data
    teammate = client_for(make_user(workspace, project, DEVELOPER))
    assert teammate.get(url(workspace, project, f"{created['id']}/")).status_code == 404
    listed = teammate.get(url(workspace, project))
    assert listed.status_code == 200 and listed.data == []
    admin_client.patch(url(workspace, project, f"{created['id']}/"), {"is_shared": True}, format="json")
    assert teammate.get(url(workspace, project, f"{created['id']}/")).status_code == 200


@pytest.mark.django_db
def test_only_owner_or_project_admin_can_edit_or_delete(workspace, project, admin_client):
    owner = make_user(workspace, project, DEVELOPER)
    other = make_user(workspace, project, QA)
    owner_client, other_client = client_for(owner), client_for(other)
    rid = save(owner_client, workspace, project, is_shared=True).data["id"]
    assert other_client.patch(url(workspace, project, f"{rid}/"), {"name": "Hijack"}, format="json").status_code == 403
    assert other_client.delete(url(workspace, project, f"{rid}/")).status_code == 403
    assert owner_client.patch(url(workspace, project, f"{rid}/"), {"name": "Mine"}, format="json").status_code == 200
    assert admin_client.delete(url(workspace, project, f"{rid}/")).status_code == 204
    assert owner_client.get(url(workspace, project, f"{rid}/")).status_code == 404


@pytest.mark.django_db
def test_report_names_are_unique_per_project_and_filters_validated(workspace, project, admin_client):
    assert save(admin_client, workspace, project).status_code == 201
    assert save(admin_client, workspace, project, name="open BUGS").status_code == 400
    assert save(admin_client, workspace, project, name="Bad", filters={"priority": "nope"}).status_code == 400
    assert save(admin_client, workspace, project, name="Bad2", filters={"mystery": 1}).status_code == 400
    assert (
        save(admin_client, workspace, project, name="Bad3", report_type="cycle_burndown", filters={}).status_code == 400
    )


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role,can_view,can_export",
    [
        (ADMIN, True, True),
        (MEMBER, True, True),
        (DEVELOPER, True, True),
        (QA, True, True),
        (VIEWER, True, False),
        (GUEST, False, False),
    ],
)
def test_report_permissions_by_role(workspace, project, fixture_bugs, role, can_view, can_export):
    client = client_for(make_user(workspace, project, role))
    view = client.get(url(workspace, project, "bugs-by-state/"))
    export = client.get(url(workspace, project, "bugs-by-state/export/"))
    assert (view.status_code == 200) is can_view
    assert (export.status_code == 200) is can_export
    if not can_view:
        assert view.status_code == 403


@pytest.mark.django_db
def test_viewer_cannot_create_reports(workspace, project):
    viewer = client_for(make_user(workspace, project, VIEWER))
    assert save(viewer, workspace, project).status_code == 403


@pytest.mark.django_db
def test_non_members_and_other_projects_get_404(workspace, project, create_user, admin_client):
    from plane.db.models import User, WorkspaceMember
    from uuid import uuid4

    outsider = User.objects.create(email=f"o-{uuid4().hex[:6]}@plane.so", username=f"o{uuid4().hex[:6]}")
    WorkspaceMember.objects.create(workspace=workspace, member=outsider, role=MEMBER)
    assert client_for(outsider).get(url(workspace, project, "bugs-by-state/")).status_code == 404

    other = make_project(workspace, create_user, identifier="OT", governed=True)
    rid = save(admin_client, workspace, other, name="elsewhere", is_shared=True).data["id"]
    assert admin_client.get(url(workspace, project, f"{rid}/")).status_code == 404
    assert admin_client.get(url(workspace, project, f"{rid}/data/")).status_code == 404


@pytest.mark.django_db
def test_reports_can_be_turned_off_per_project(workspace, project, admin_client):
    Project.objects.filter(pk=project.pk).update(reports_enabled=False)
    response = admin_client.get(url(workspace, project, "bugs-by-state/"))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_csv_matches_the_table_and_carries_filter_metadata(workspace, project, fixture_bugs, admin_client):
    table = admin_client.get(url(workspace, project, "bugs-by-state/"), {"priority": "high"}).data
    response = admin_client.get(url(workspace, project, "bugs-by-state/export/"), {"priority": "high"})
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    lines = response.content.decode().splitlines()
    comments = [line for line in lines if line.startswith("#")]
    assert any("filters: priority=high" in c for c in comments)
    assert any("timezone: Asia/Kolkata" in c for c in comments)
    body = [line for line in lines if not line.startswith("#")]
    assert body[0] == "State,Group,Open items"
    expected = [f"{r['state']},{r['group']},{r['count']}" for r in table["rows"]]
    assert body[1:] == expected


@pytest.mark.django_db
def test_csv_escapes_formula_injection(workspace, project, admin_client):
    evil = mk_state(project, '=HYPERLINK("http://evil")', "started", 9)
    bug(project, evil, "none", "x")
    response = admin_client.get(url(workspace, project, "bugs-by-state/export/"))
    text = response.content.decode()
    assert "'=HYPERLINK" in text
    assert "\n=HYPERLINK" not in text and ",=HYPERLINK" not in text


def test_escape_cell_unit():
    assert escape_cell("=1+1") == "'=1+1"
    assert escape_cell("+1") == "'+1"
    assert escape_cell("-1") == "'-1"
    assert escape_cell("@SUM(A1)") == "'@SUM(A1)"
    assert escape_cell("plain") == "plain"
    assert escape_cell(-5) == -5
    assert escape_cell(None) == ""


@pytest.mark.django_db
def test_saved_report_export_matches_data(workspace, project, fixture_bugs, admin_client):
    rid = save(admin_client, workspace, project, name="CSV one", filters={}).data["id"]
    data = admin_client.get(url(workspace, project, f"{rid}/data/")).data
    export = admin_client.get(url(workspace, project, f"{rid}/export/"))
    assert export.status_code == 200
    body = [line for line in export.content.decode().splitlines() if not line.startswith("#")]
    assert len(body) == len(data["rows"]) + 1


# ---------------------------------------------------------------------------
# Cross-check and performance
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_counts_match_raw_sql(workspace, project, fixture_bugs, admin_client):
    response = admin_client.get(url(workspace, project, "bugs-by-state/"))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM issues i
            JOIN states s ON s.id = i.state_id
            JOIN issue_types t ON t.id = i.type_id
            WHERE i.project_id = %s AND i.deleted_at IS NULL AND i.archived_at IS NULL
              AND i.is_draft = false AND t.key = 'bug'
              AND s."group" IN ('backlog','unstarted','started')
            """,
            [str(project.id)],
        )
        raw = cursor.fetchone()[0]
    assert raw == response.data["total"] == 4


@pytest.mark.django_db
def test_responses_are_cached_then_refreshed_on_change(workspace, project, states, admin_client):
    bug(project, states["new"], "none", "one")
    first = admin_client.get(url(workspace, project, "bugs-by-state/")).data
    again = admin_client.get(url(workspace, project, "bugs-by-state/")).data
    assert first["generated_at"] == again["generated_at"]  # served from cache
    bug(project, states["new"], "none", "two").save()
    fresh = admin_client.get(url(workspace, project, "bugs-by-state/")).data
    assert fresh["total"] == first["total"] + 1
