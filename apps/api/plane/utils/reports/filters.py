# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Filter parsing and validation for reports.

Saved reports store their filters as JSON with a ``schema_version``. Every entry point
(query string, saved definition) goes through ``parse_filters`` so the same input always
produces the same normalised dict, which is also what the cache key is built from.
"""

from datetime import date, timedelta
from uuid import UUID

SCHEMA_VERSION = 1
MAX_RANGE_DAYS = 730
DEFAULT_RANGE_DAYS = 90

PRIORITIES = ("urgent", "high", "medium", "low", "none")
INTERVALS = ("week", "month")
PLOTS = ("issues", "points")
ALL_TYPES = "all"

UUID_FILTERS = ("cycle_id", "module_id", "assignee_id", "label_id")
DATE_FILTERS = ("date_from", "date_to")
FILTER_KEYS = UUID_FILTERS + DATE_FILTERS + ("priority", "type_id", "interval", "plot")


class ReportFilterError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _uuid(name, value):
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ReportFilterError("invalid_filter", f"{name} must be a UUID.", {"filter": name})


def _date(name, value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ReportFilterError("invalid_filter", f"{name} must be a date (YYYY-MM-DD).", {"filter": name})


def parse_filters(raw, report_type=None, today=None):
    """Validate ``raw`` and return a normalised filter dict with every key present."""
    raw = dict(raw or {})
    raw.pop("schema_version", None)

    unknown = sorted(set(raw) - set(FILTER_KEYS))
    if unknown:
        raise ReportFilterError("unknown_filter", "Unknown report filter.", {"filters": unknown})

    parsed = {key: None for key in FILTER_KEYS}

    for key in UUID_FILTERS:
        if not _blank(raw.get(key)):
            parsed[key] = _uuid(key, raw[key])

    type_id = raw.get("type_id")
    if not _blank(type_id):
        parsed["type_id"] = ALL_TYPES if str(type_id).lower() == ALL_TYPES else _uuid("type_id", type_id)

    priority = raw.get("priority")
    if not _blank(priority):
        if priority not in PRIORITIES:
            raise ReportFilterError("invalid_filter", "priority is not valid.", {"filter": "priority"})
        parsed["priority"] = priority

    for key in DATE_FILTERS:
        if not _blank(raw.get(key)):
            parsed[key] = _date(key, raw[key])

    interval = raw.get("interval")
    if not _blank(interval):
        if interval not in INTERVALS:
            raise ReportFilterError("invalid_filter", "interval must be week or month.", {"filter": "interval"})
        parsed["interval"] = interval

    plot = raw.get("plot")
    if not _blank(plot):
        if plot not in PLOTS:
            raise ReportFilterError("invalid_filter", "plot must be issues or points.", {"filter": "plot"})
        parsed["plot"] = plot

    date_from, date_to = parsed["date_from"], parsed["date_to"]
    if date_from and date_to and date_from > date_to:
        raise ReportFilterError("invalid_date_range", "date_from must not be after date_to.")
    if date_from and date_to and (date_to - date_from).days > MAX_RANGE_DAYS:
        raise ReportFilterError(
            "date_range_too_large", f"The date range may not exceed {MAX_RANGE_DAYS} days (2 years)."
        )

    if report_type == "cycle_burndown" and not parsed["cycle_id"]:
        raise ReportFilterError("cycle_required", "cycle_id is required for this report.", {"filter": "cycle_id"})
    if report_type == "cycle_scope" and not parsed["cycle_id"]:
        raise ReportFilterError("cycle_required", "cycle_id is required for this report.", {"filter": "cycle_id"})

    return parsed


def resolve_date_range(filters, today):
    """Return (date_from, date_to) with defaults, enforcing the two year cap."""
    date_to = filters.get("date_to") or today
    date_from = filters.get("date_from") or (date_to - timedelta(days=DEFAULT_RANGE_DAYS))
    if date_from > date_to:
        raise ReportFilterError("invalid_date_range", "date_from must not be after date_to.")
    if (date_to - date_from).days > MAX_RANGE_DAYS:
        raise ReportFilterError(
            "date_range_too_large", f"The date range may not exceed {MAX_RANGE_DAYS} days (2 years)."
        )
    return date_from, date_to


def serialize_filters(filters):
    """JSON friendly copy (dates as ISO strings) used in responses and cache keys."""
    out = {}
    for key, value in filters.items():
        out[key] = value.isoformat() if isinstance(value, date) else value
    return out
