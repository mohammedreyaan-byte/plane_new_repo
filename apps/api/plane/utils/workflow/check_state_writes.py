# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""CI guard for PLN-013: no direct workflow state writes outside the allowlist.

Existing work items may only change state through
``plane.utils.workflow.transition.transition_issue``. This scan fails when
runtime code assigns ``.state`` directly or calls ``.update(state=...)``
outside the narrow allowlist documented in ``README.md``.

Run locally with::

    python apps/api/plane/utils/workflow/check_state_writes.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Instance assignment: obj dot state = <state>. The lookahead avoids matching ==.
STATE_ASSIGNMENT = re.compile(r"\.\s*state\s*=(?!=)")
# Bulk queryset update: .update(state=<state>, ...). `state_id=` is not matched.
STATE_UPDATE = re.compile(r"\.update\s*\([^)]*\bstate\s*=(?!=)")

# Paths are relative to the ``plane`` package directory and mirror README.md.
ALLOWED_FILES = {
    "utils/workflow/check_state_writes.py",
    "utils/workflow/transition.py",
    "db/models/issue.py",
    "db/models/draft.py",
    "app/serializers/intake.py",
    "api/serializers/intake.py",
    "db/management/commands/repair_states.py",
}
# Migrations arrange historical data and tests arrange fixtures; both may set
# state directly without going through the runtime transition service.
ALLOWED_PATH_PARTS = {"migrations", "tests"}


def find_violations(root: Path) -> list[str]:
    """Return formatted violations for every disallowed direct state write."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        parts = set(relative.split("/"))
        if relative in ALLOWED_FILES or parts & ALLOWED_PATH_PARTS:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if STATE_ASSIGNMENT.search(line) or STATE_UPDATE.search(line):
                violations.append(f"{relative}:{line_number}: {stripped}")
    return violations


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=default_root,
        help="Python source root to scan (defaults to the plane package).",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    violations = find_violations(root)
    if violations:
        print("Direct workflow state writes are only allowed through transition_issue.", file=sys.stderr)
        print("The allowlist is documented in apps/api/plane/utils/workflow/README.md.", file=sys.stderr)
        print("Offending writes:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    print(f"No disallowed direct state writes found under {root}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
