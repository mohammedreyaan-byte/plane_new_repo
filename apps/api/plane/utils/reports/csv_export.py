# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import csv
import io

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape_cell(value):
    """Neutralise spreadsheet formulas (CSV injection). Numbers are written as they are."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def _comment(text):
    return "# " + " ".join(str(text).split())


def build_csv(result, title=None):
    """CSV text for a report result.

    Starts with comment lines that carry the report name, generation time, time zone and the
    exact filters, then a header row and one row per table row. The columns are the same
    ``columns`` the on-screen table shows, in the same order.
    """
    out = io.StringIO()
    out.write(_comment(f"report: {title or result['report']}") + "\r\n")
    out.write(_comment(f"generated_at: {result['generated_at']}") + "\r\n")
    out.write(_comment(f"timezone: {result['meta'].get('timezone', '')}") + "\r\n")
    filters = "; ".join(f"{k}={v}" for k, v in result["filters"].items() if v not in (None, ""))
    out.write(_comment(f"filters: {filters or 'none'}") + "\r\n")

    writer = csv.writer(out, lineterminator="\r\n")
    columns = result["columns"]
    writer.writerow([escape_cell(c["label"]) for c in columns])
    for row in result["rows"]:
        writer.writerow([escape_cell(row.get(c["key"])) for c in columns])
    return out.getvalue()
