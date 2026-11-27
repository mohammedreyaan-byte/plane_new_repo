# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""URL-conf inventory helpers used by the isolation coverage guard."""

from django.urls import get_resolver
from django.urls.resolvers import URLResolver

PROJECT_MARKERS = ("project_id", "project_identifier")


def iter_url_patterns(patterns=None, prefix=""):
    """Yield ``(route, pattern)`` for every concrete URL pattern."""
    if patterns is None:
        patterns = get_resolver().url_patterns
    for pattern in patterns:
        route = f"{prefix}{pattern.pattern}".lstrip("^")
        if isinstance(pattern, URLResolver):
            yield from iter_url_patterns(pattern.url_patterns, route)
        else:
            yield route, pattern


def project_scoped_routes():
    """Routes whose path carries a project identifier (the isolation boundary)."""
    return {route for route, _ in iter_url_patterns() if any(marker in route for marker in PROJECT_MARKERS)}


def public_route_reasons():
    """Routes intentionally reachable without project membership."""
    from .allowlist import PUBLIC_ROUTES

    return PUBLIC_ROUTES
