# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Dependency-free PLN-027 go-live readiness gate.

The gate reads a declarative manifest and refuses to declare readiness unless
every required criterion has real, verifiable evidence. Human criteria can only
pass when a separate evidence register contains a completed record with a named
owner, an ISO-8601 date and evidence files that actually exist on disk.

Design rules:

* standard library only -- no Django, Docker or network access;
* the gate never writes to the manifest or the evidence register;
* Markdown prose is never treated as evidence;
* a missing, blank or placeholder record is a blocking failure, not a pass;
* exit codes: 0 = ready, 1 = not ready, 2 = invalid manifest/evidence document.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

GATE_SCHEMA = "pln027.readiness.v1"
TICKET = "PLN-027"
PASS_STATUS = "pass"
PLACEHOLDERS = frozenset(
    {
        "",
        "-",
        "n/a",
        "na",
        "none",
        "not recorded",
        "pending",
        "tbd",
        "to do",
        "unassigned",
    }
)
CHECK_TYPES = frozenset({"all", "json_value", "file_nonempty", "manual"})
UAT_SCENARIOS = tuple(f"UAT-{index:02d}" for index in range(1, 13))
DEFAULT_MANIFEST = Path("plane-ce-project/docs/go-live/readiness-manifest.json")


class GateError(RuntimeError):
    """The manifest or one of its evidence documents is invalid."""


def load_json(path: Path) -> Any:
    """Load a JSON document without leaking file contents into errors."""
    try:
        # utf-8-sig tolerates evidence files written by PowerShell with a BOM.
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"cannot read or parse {Path(path).name}") from error


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve a minimal RFC 6901 JSON pointer."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise GateError("JSON pointer must start with '/'")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise GateError(f"pointer not found: {pointer}")
            current = current[token]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            try:
                index = int(token)
            except ValueError as error:
                raise GateError(f"invalid array index in pointer: {pointer}") from error
            if index < 0 or index >= len(current):
                raise GateError(f"pointer index out of range: {pointer}")
            current = current[index]
        else:
            raise GateError(f"pointer traverses a scalar: {pointer}")
    return current


def is_placeholder(value: Any) -> bool:
    """Return True for blank, unassigned or unrecorded evidence values."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in PLACEHOLDERS
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def resolve_path(root: Path, raw: str) -> Path:
    """Resolve a workspace-relative evidence path, rejecting escapes."""
    if not isinstance(raw, str) or not raw.strip():
        raise GateError("evidence path is empty")
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise GateError("evidence paths must stay inside the workspace root")
    base = Path(root).resolve()
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base):
        raise GateError("evidence path escapes the workspace root")
    return resolved


def _check_json_value(root: Path, spec: Mapping[str, Any]) -> tuple[bool, str]:
    try:
        document = load_json(resolve_path(root, str(spec["path"])))
        actual = resolve_pointer(document, str(spec["pointer"]))
    except (GateError, KeyError) as error:
        return False, f"evidence unreadable: {error}"

    label = str(spec.get("label", spec["pointer"]))
    if "equals" in spec:
        if actual == spec["equals"]:
            return True, f"{label} matches the expected value"
        return False, f"{label} does not match the expected value"
    if "contains" in spec:
        needle = str(spec["contains"])
        haystack = (
            actual if isinstance(actual, str) else json.dumps(actual, sort_keys=True)
        )
        if needle in haystack:
            return True, f"{label} contains the expected evidence"
        return False, f"{label} does not contain the expected evidence"
    if spec.get("not_placeholder") is True:
        if not is_placeholder(actual):
            return True, f"{label} is recorded"
        return False, f"{label} is blank or a placeholder"
    raise GateError("json_value check has no comparison operator")


def _check_file_nonempty(root: Path, spec: Mapping[str, Any]) -> tuple[bool, str]:
    try:
        path = resolve_path(root, str(spec["path"]))
    except GateError as error:
        return False, str(error)
    label = str(spec.get("path"))
    if not path.is_file():
        return False, f"evidence file missing: {label}"
    if path.stat().st_size == 0:
        return False, f"evidence file is empty: {label}"
    return True, f"evidence file present: {label}"


def _check_manual(root: Path, spec: Mapping[str, Any]) -> tuple[bool, str]:
    key = str(spec.get("key", "unknown"))
    try:
        register = load_json(resolve_path(root, str(spec["path"])))
        record = register["manual_records"][key]
    except (GateError, KeyError, TypeError):
        return False, f"no recorded manual evidence for {key}"
    if not isinstance(record, Mapping):
        return False, f"manual record for {key} is not an object"

    problems: list[str] = []
    if str(record.get("status", "")).strip().lower() != PASS_STATUS:
        problems.append("status is not pass")
    if is_placeholder(record.get("owner")):
        problems.append("owner is not named")
    recorded_date = record.get("date")
    try:
        if not isinstance(recorded_date, str):
            raise ValueError
        date.fromisoformat(recorded_date)
    except ValueError:
        problems.append("date is not ISO-8601")

    evidence = record.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        problems.append("no evidence files recorded")
    else:
        for item in evidence:
            ok, reason = _check_file_nonempty(root, {"path": str(item)})
            if not ok:
                problems.append(reason)

    if problems:
        return False, "; ".join(problems)
    return True, f"recorded evidence for {key} is complete"


def check(root: Path, spec: Mapping[str, Any]) -> tuple[bool, str]:
    """Run one declarative evidence check."""
    kind = spec.get("type")
    if kind == "all":
        children = spec.get("checks")
        if not isinstance(children, list) or not children:
            raise GateError("all check has no child checks")
        failures = []
        for child in children:
            if not isinstance(child, Mapping):
                raise GateError("all check child is not an object")
            ok, reason = check(root, child)
            if not ok:
                failures.append(reason)
        if failures:
            return False, "; ".join(failures)
        return True, f"{len(children)} evidence checks passed"
    if kind == "json_value":
        return _check_json_value(root, spec)
    if kind == "file_nonempty":
        return _check_file_nonempty(root, spec)
    if kind == "manual":
        return _check_manual(root, spec)
    raise GateError(f"unsupported check type: {kind}")


def validate_manifest(manifest: Any) -> None:
    """Reject structurally incomplete or tampered manifests."""
    if not isinstance(manifest, Mapping):
        raise GateError("manifest is not a JSON object")
    if manifest.get("schema") != GATE_SCHEMA:
        raise GateError("unsupported readiness manifest schema")
    if manifest.get("ticket") != TICKET:
        raise GateError("manifest ticket is not PLN-027")

    criteria = manifest.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise GateError("manifest has no criteria")
    if not all(isinstance(criterion, Mapping) for criterion in criteria):
        raise GateError("criterion is not an object")
    identifiers = [str(criterion.get("id", "")) for criterion in criteria]
    if any(not value for value in identifiers) or len(set(identifiers)) != len(
        identifiers
    ):
        raise GateError("criteria ids must be present and unique")

    expected_count = manifest.get("expected_criteria_count")
    if isinstance(expected_count, int) and expected_count != len(criteria):
        raise GateError("criteria count does not match the declared count")
    for scenario in UAT_SCENARIOS:
        if scenario not in identifiers:
            raise GateError(f"manifest is missing {scenario}")

    for criterion in criteria:
        criterion_id = criterion.get("id")
        if not isinstance(criterion.get("required"), bool):
            raise GateError(f"{criterion_id}: required must be a boolean")
        verification = criterion.get("verification")
        if not isinstance(verification, Mapping) or verification.get("type") not in CHECK_TYPES:
            raise GateError(f"{criterion_id}: invalid verification type")


def evaluate(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate every criterion and return a deterministic report."""
    results: list[dict[str, Any]] = []
    for criterion in manifest["criteria"]:
        criterion_id = str(criterion.get("id", "unknown"))
        try:
            passed, reason = check(root, criterion["verification"])
        except (GateError, KeyError, TypeError) as error:
            passed, reason = False, f"invalid verification: {error}"
        results.append(
            {
                "id": criterion_id,
                "category": criterion.get("category", "unspecified"),
                "description": criterion.get("description", ""),
                "owner": criterion.get("owner", ""),
                "required": bool(criterion.get("required", True)),
                "passed": passed,
                "reason": reason,
            }
        )

    blocking = [item for item in results if item["required"] and not item["passed"]]
    return {
        "ticket": TICKET,
        "schema": GATE_SCHEMA,
        "criteria": results,
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "blocking_failures": len(blocking),
        "ready": not blocking,
    }


def render_text(report: Mapping[str, Any]) -> str:
    """Render a compact human-readable gate report."""
    verdict = "READY" if report["ready"] else "NOT READY"
    lines = [
        f"PLN-027 readiness gate: {verdict}",
        f"criteria: {report['passed']}/{report['total']} passed; "
        f"blocking failures: {report['blocking_failures']}",
        "",
    ]
    for item in report["criteria"]:
        mark = "PASS" if item["passed"] else ("BLOCK" if item["required"] else "INFO")
        lines.append(f"[{mark}] {item['id']}: {item['reason']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Workspace root used to resolve relative evidence paths.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=f"Manifest path (default: <root>/{DEFAULT_MANIFEST.as_posix()}).",
    )
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = parser.parse_args(argv)

    root = Path(args.root)
    manifest_path = args.manifest or root / DEFAULT_MANIFEST
    try:
        manifest = load_json(manifest_path)
        validate_manifest(manifest)
        report = evaluate(root, manifest)
    except GateError as error:
        print(f"PLN-027 readiness gate error: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
