# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json

from django.core.cache import cache
from django.utils import timezone

from plane.db.models.report import REPORT_CACHE_VERSION_KEY
from plane.utils.reports.filters import parse_filters, serialize_filters
from plane.utils.reports.queries import OPEN_DEFINITION, REPORTS, ReportContext

CACHE_TTL_SECONDS = 60


def _cache_key(project, report_type, filters, user, today):
    try:
        version = cache.get(REPORT_CACHE_VERSION_KEY.format(project_id=project.id)) or 0
    except Exception:
        version = 0
    digest = hashlib.sha256(
        json.dumps(serialize_filters(filters), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    # Every project member sees the same project data, but the key still carries the user so a
    # future per-user scope (for example guests) cannot leak another user's cached response.
    return f"reports:{project.id}:{version}:{report_type}:{digest}:{user.id}:{today.isoformat()}"


def run_report(project, report_type, raw_filters, user):
    """Validate filters, compute (or fetch from cache) a report and return the response dict.

    Raises ReportFilterError for bad filters and ReportNotFound for an unknown cycle.
    """
    filters = parse_filters(raw_filters, report_type)
    ctx = ReportContext(project, filters)
    key = _cache_key(project, report_type, filters, user, ctx.today)

    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    data = REPORTS[report_type](ctx)
    meta = {"timezone": project.timezone or "UTC", "open_definition": OPEN_DEFINITION}
    meta.update(data.get("meta", {}))
    scope = meta.get("scope") or {}
    if scope.get("deprecation_note"):
        meta["deprecation_note"] = scope["deprecation_note"]
    result = {
        "report": report_type,
        "generated_at": timezone.now().isoformat(),
        "filters": serialize_filters(filters),
        "total": data["total"],
        "columns": data["columns"],
        "rows": data["rows"],
        "meta": meta,
    }
    try:
        cache.set(key, result, CACHE_TTL_SECONDS)
    except Exception:
        pass
    return result
