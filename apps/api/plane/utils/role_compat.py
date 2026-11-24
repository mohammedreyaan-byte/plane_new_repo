# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Compatibility helpers between the legacy integer roles and the new roles.

The integer ``role`` column is still what most permission checks read. The new
system roles reuse spare integers (see ``Role.legacy_id``):

    Admin 20, Member 15, Developer 12, QA 11, Guest 5, Viewer 2

Old checks such as ``role__in=[ADMIN, MEMBER]`` or ``role__gte=15`` do not know
about Developer (12) and QA (11), so they would deny them everything. These
helpers widen the old checks in one place instead of rewriting every view.

This module must stay free of Django model imports so that it can be imported
from anywhere (permission classes, serializers, views) without import cycles.
"""

ADMIN = 20
MEMBER = 15
DEVELOPER = 12
QA = 11
GUEST = 5
VIEWER = 2

# Roles that behave like a project contributor: they can write work items and
# can be assigned to work items. Fine grained limits (cycles, modules, ...) are
# applied on top with capabilities, not with these integers.
CONTRIBUTOR_ROLES = (ADMIN, MEMBER, DEVELOPER, QA)

# Roles that cannot write work items or be assigned (legacy ``role < 15`` checks).
NON_CONTRIBUTOR_ROLES = (GUEST, VIEWER)

# Roles that count as Member for legacy checks.
MEMBER_ALIASES = (DEVELOPER, QA)


def expand_roles(role_values, safe=False):
    """Widen a legacy list of allowed role integers.

    * If Member is allowed, Developer and QA are allowed as well.
    * If Guest is allowed and the request is read-only (``safe=True``), Viewer
      is allowed as well. Viewer never gets write access through a Guest rule.
    """
    expanded = set(role_values)
    if MEMBER in expanded:
        expanded.update(MEMBER_ALIASES)
    if safe and GUEST in expanded:
        expanded.add(VIEWER)
    return sorted(expanded, reverse=True)


def is_contributor(role):
    """True for roles that can write work items and be assigned to them."""
    return role in CONTRIBUTOR_ROLES
