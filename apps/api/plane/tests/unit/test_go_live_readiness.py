# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for the dependency-free PLN-027 go-live readiness gate."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _gate_dir() -> Path:
    configured = os.environ.get("PLN027_GATE_DIR")
    if configured:
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / "go-live" / "readiness_gate.py"
        if candidate.is_file():
            return parent / "scripts" / "go-live"
    raise FileNotFoundError("Could not locate scripts/go-live/readiness_gate.py")


def _load_gate():
    directory = _gate_dir()
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    name = "pln027_readiness_gate"
    spec = importlib.util.spec_from_file_location(name, directory / "readiness_gate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def _workspace_root() -> Path:
    configured = os.environ.get("PLN027_WORKSPACE_ROOT")
    if configured:
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        if (parent / ".playwright-mcp" / "pln027-uat-go-live-result.json").is_file():
            return parent
    raise FileNotFoundError("Could not locate the PLN-027 evidence register")


def test_real_manifest_is_valid_and_refuses_readiness():
    root = _workspace_root()
    manifest = gate.load_json(root / gate.DEFAULT_MANIFEST)

    gate.validate_manifest(manifest)
    report = gate.evaluate(root, manifest)

    assert report["ticket"] == "PLN-027"
    assert report["total"] == manifest["expected_criteria_count"]
    assert report["ready"] is False
    assert report["blocking_failures"] > 0

    automated_ids = {
        "ENTRY-02A",
        "ENTRY-03",
        "ENTRY-05",
        "EVID-PLN017",
        "EVID-STACK",
        "EVID-SHEET",
    }
    for item in report["criteria"]:
        if item["id"] in automated_ids:
            assert item["passed"] is True, item["reason"]

    uat_results = [item for item in report["criteria"] if item["id"].startswith("UAT-")]
    assert len(uat_results) == 12
    assert all(item["passed"] is False for item in uat_results)


def test_json_value_checks_are_exact_and_fail_closed(tmp_path):
    payload = tmp_path / "evidence.json"
    payload.write_text(
        json.dumps({"verify": "PASS", "count": 0, "owner": ""}), encoding="utf-8"
    )

    assert gate.check(
        tmp_path,
        {
            "type": "json_value",
            "path": "evidence.json",
            "pointer": "/verify",
            "equals": "PASS",
        },
    )[0]
    assert not gate.check(
        tmp_path,
        {
            "type": "json_value",
            "path": "evidence.json",
            "pointer": "/count",
            "equals": 1,
        },
    )[0]
    assert not gate.check(
        tmp_path,
        {
            "type": "json_value",
            "path": "evidence.json",
            "pointer": "/owner",
            "not_placeholder": True,
        },
    )[0]
    assert gate.check(
        tmp_path,
        {
            "type": "json_value",
            "path": "evidence.json",
            "pointer": "/verify",
            "contains": "ASS",
        },
    )[0]


def test_manual_record_requires_owner_date_and_real_evidence(tmp_path):
    evidence = tmp_path / "proof.txt"
    evidence.write_text("recorded sign-off", encoding="utf-8")
    register_path = tmp_path / "register.json"
    register = {
        "manual_records": {
            "X-1": {
                "status": "pass",
                "owner": "",
                "date": "2026-11-27",
                "evidence": ["proof.txt"],
            }
        }
    }
    register_path.write_text(json.dumps(register), encoding="utf-8")
    spec = {"type": "manual", "path": "register.json", "key": "X-1"}

    ok, reason = gate.check(tmp_path, spec)
    assert not ok
    assert "owner" in reason

    register["manual_records"]["X-1"]["owner"] = "test-owner"
    register_path.write_text(json.dumps(register), encoding="utf-8")
    assert gate.check(tmp_path, spec)[0]

    register["manual_records"]["X-1"]["evidence"] = ["missing-proof.txt"]
    register_path.write_text(json.dumps(register), encoding="utf-8")
    ok, reason = gate.check(tmp_path, spec)
    assert not ok
    assert "missing" in reason

    register["manual_records"]["X-1"]["evidence"] = ["proof.txt"]
    register["manual_records"]["X-1"]["date"] = "27-11-2026"
    register_path.write_text(json.dumps(register), encoding="utf-8")
    ok, reason = gate.check(tmp_path, spec)
    assert not ok
    assert "ISO-8601" in reason

    register["manual_records"]["X-1"]["date"] = "2026-11-27"
    register["manual_records"]["X-1"]["status"] = "pending"
    register_path.write_text(json.dumps(register), encoding="utf-8")
    ok, reason = gate.check(tmp_path, spec)
    assert not ok
    assert "status" in reason


def test_paths_and_pointers_fail_closed(tmp_path):
    with pytest.raises(gate.GateError):
        gate.resolve_path(tmp_path, "../outside.json")
    with pytest.raises(gate.GateError):
        gate.resolve_path(tmp_path, str(tmp_path / "absolute.json"))
    with pytest.raises(gate.GateError):
        gate.resolve_pointer({"a": 1}, "a")
    with pytest.raises(gate.GateError):
        gate.resolve_pointer({"a": [1]}, "/a/2")


def test_manifest_validation_rejects_tampering():
    root = _workspace_root()
    original = gate.load_json(root / gate.DEFAULT_MANIFEST)

    mismatched_count = json.loads(json.dumps(original))
    mismatched_count["expected_criteria_count"] += 1
    with pytest.raises(gate.GateError):
        gate.validate_manifest(mismatched_count)

    missing_uat = json.loads(json.dumps(original))
    missing_uat["criteria"] = [
        item for item in missing_uat["criteria"] if item["id"] != "UAT-12"
    ]
    with pytest.raises(gate.GateError):
        gate.validate_manifest(missing_uat)

    invalid_required = json.loads(json.dumps(original))
    invalid_required["criteria"][0]["required"] = "yes"
    with pytest.raises(gate.GateError):
        gate.validate_manifest(invalid_required)


def test_all_check_aggregates_failures(tmp_path):
    payload = tmp_path / "evidence.json"
    payload.write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")

    ok, reason = gate.check(
        tmp_path,
        {
            "type": "all",
            "checks": [
                {
                    "type": "json_value",
                    "path": "evidence.json",
                    "pointer": "/a",
                    "equals": 1,
                },
                {
                    "type": "json_value",
                    "path": "evidence.json",
                    "pointer": "/b",
                    "equals": 3,
                },
            ],
        },
    )

    assert not ok
    assert "does not match" in reason


def test_main_exit_codes(tmp_path, capsys):
    root = _workspace_root()

    assert gate.main(["--root", str(root), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is False

    assert (
        gate.main(
            ["--root", str(root), "--manifest", str(tmp_path / "missing.json")]
        )
        == 2
    )
    capsys.readouterr()

    evidence = tmp_path / "ok.json"
    evidence.write_text(json.dumps({"value": "PASS"}), encoding="utf-8")
    manifest = {
        "schema": gate.GATE_SCHEMA,
        "ticket": gate.TICKET,
        "expected_criteria_count": len(gate.UAT_SCENARIOS) + 1,
        "criteria": [
            {
                "id": scenario,
                "category": "uat",
                "description": "fixture criterion",
                "owner": "test-owner",
                "required": False,
                "verification": {"type": "file_nonempty", "path": "ok.json"},
            }
            for scenario in gate.UAT_SCENARIOS
        ]
        + [
            {
                "id": "AUTO-FIXTURE",
                "category": "evidence",
                "description": "fixture criterion",
                "owner": "automated evidence check",
                "required": True,
                "verification": {
                    "type": "json_value",
                    "path": "ok.json",
                    "pointer": "/value",
                    "equals": "PASS",
                },
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert gate.main(["--root", str(tmp_path), "--manifest", str(manifest_path)]) == 0
    assert "READY" in capsys.readouterr().out


def test_register_keeps_sheet_untouched_and_manual_records_pending():
    root = _workspace_root()
    register = gate.load_json(
        root / ".playwright-mcp" / "pln027-uat-go-live-result.json"
    )

    assert register["sheet"]["cell"] == "H28"
    assert register["sheet"]["current_value"] == "To Do"
    assert register["sheet"]["changed_in_this_work_period"] is False
    assert register["repository_state"]["production_compose_changed"] is False
    assert register["repository_state"]["docker_compose_down_v_used"] is False
    assert register["manual_records"]
    assert all(
        item["status"] == "pending" and item["evidence"] == []
        for item in register["manual_records"].values()
    )
