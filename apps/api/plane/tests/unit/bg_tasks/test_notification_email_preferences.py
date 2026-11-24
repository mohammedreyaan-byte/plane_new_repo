# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import SimpleNamespace

import pytest

from plane.bgtasks.notification_task import should_send_issue_email


def make_preference(**overrides):
    """A preference with every email switch OFF unless overridden."""
    values = {
        "property_change": False,
        "assignment": False,
        "state_change": False,
        "issue_completed": False,
        "comment": False,
        "mention": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.unit
class TestShouldSendIssueEmail:
    """Each kind of activity must be controlled only by its own switch."""

    # --- the bug that was fixed: one switch must never override another ---

    def test_comment_off_but_property_change_on_sends_nothing(self):
        pref = make_preference(comment=False, property_change=True)
        assert should_send_issue_email(pref, "comment") is False

    def test_state_off_but_property_change_on_sends_nothing(self):
        pref = make_preference(state_change=False, issue_completed=False, property_change=True)
        assert should_send_issue_email(pref, "state") is False

    def test_assignment_off_but_property_change_on_sends_nothing(self):
        pref = make_preference(assignment=False, property_change=True)
        assert should_send_issue_email(pref, "assignees") is False

    # --- each switch turns on its own event ---

    def test_comment_on_sends_comment_email(self):
        assert should_send_issue_email(make_preference(comment=True), "comment") is True

    def test_state_change_on_sends_state_email(self):
        assert should_send_issue_email(make_preference(state_change=True), "state") is True

    def test_assignment_on_sends_assignment_email(self):
        assert should_send_issue_email(make_preference(assignment=True), "assignees") is True

    def test_property_change_on_sends_other_property_emails(self):
        pref = make_preference(property_change=True)
        for field in ("priority", "labels", "target_date", "estimate_point"):
            assert should_send_issue_email(pref, field) is True

    # --- completed state ---

    def test_issue_completed_sends_email_only_when_moved_to_completed_state(self):
        pref = make_preference(issue_completed=True)
        assert should_send_issue_email(pref, "state", moved_to_completed=True) is True
        assert should_send_issue_email(pref, "state", moved_to_completed=False) is False

    # --- everything off ---

    @pytest.mark.parametrize("field", ["state", "comment", "assignees", "priority", "labels"])
    def test_all_off_sends_nothing(self, field):
        assert should_send_issue_email(make_preference(), field, moved_to_completed=True) is False

    # --- other events do not leak into the property_change switch ---

    @pytest.mark.parametrize("field", ["state", "comment", "assignees"])
    def test_property_change_off_does_not_block_own_event(self, field):
        pref = make_preference(
            property_change=False,
            state_change=True,
            comment=True,
            assignment=True,
        )
        assert should_send_issue_email(pref, field) is True
