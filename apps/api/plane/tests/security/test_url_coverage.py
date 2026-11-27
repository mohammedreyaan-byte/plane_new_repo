# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Fail-closed coverage guards for project-scoped API routes (PLN-015)."""

import pytest

from plane.api.views.base import ProjectScopeMixin as ApiProjectScopeMixin
from plane.app.views.base import ProjectScopeMixin as AppProjectScopeMixin

from .allowlist import PUBLIC_ROUTES
from .matrix import COVERED_ROUTES
from .url_inventory import iter_url_patterns, project_scoped_routes

pytestmark = pytest.mark.contract

SCOPE_MIXINS = (AppProjectScopeMixin, ApiProjectScopeMixin)


def test_committed_matrix_matches_urlconf():
    """Adding or removing a project-scoped route must update the manifest."""
    assert project_scoped_routes() == COVERED_ROUTES


def test_every_project_scoped_callback_enforces_central_scope():
    """A route with a project identifier must use the central scope mixin."""
    exemptions = {route for route in PUBLIC_ROUTES if route in COVERED_ROUTES}
    assert exemptions <= project_scoped_routes()

    for route, pattern in iter_url_patterns():
        if route not in COVERED_ROUTES or route in exemptions:
            continue
        callback_class = getattr(pattern.callback, "cls", None)
        assert callback_class is not None, f"{route} is not a DRF class-based view"
        assert issubclass(callback_class, SCOPE_MIXINS), (
            f"{route} uses {callback_class.__name__}, which does not enforce project scope"
        )
        assert not getattr(callback_class, "skip_project_scope", False), (
            f"{route} opts out of project scope without an allowlist entry"
        )


def test_allowlist_entries_are_explained():
    assert PUBLIC_ROUTES
    assert all(isinstance(reason, str) and reason.strip() for reason in PUBLIC_ROUTES.values())
