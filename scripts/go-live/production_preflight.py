#!/usr/bin/env python3
"""Static preflight for the production deployment configuration.

This script never prints or evaluates secret values. It checks that the
production-only Compose override and runbook are present, fail-closed and do
not reference demo/dev overrides or test-mode email settings. It is safe to run
in a code-only environment; it does not contact Docker or any service.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = ROOT / "docker-compose.yml"
PROD_OVERRIDE = ROOT / "docker-compose.production.override.yml"
RUNBOOK = ROOT / "docs" / "go-live" / "runbooks" / "production-deployment.md"
RUNBOOKS = ROOT / "docs" / "go-live" / "runbooks"
ENV_EXAMPLES = [ROOT / ".env.example", ROOT / "apps" / "api" / ".env.example"]

required_interpolations = (
    "${SITE_ADDRESS:?",
    "${LIVE_SERVER_SECRET_KEY:?",
)

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"{status}: {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


for path in (BASE_COMPOSE, PROD_OVERRIDE, RUNBOOK):
    check(f"{path.relative_to(ROOT)} exists", path.is_file())

if PROD_OVERRIDE.is_file():
    override = read(PROD_OVERRIDE)
    for token in required_interpolations:
        check(f"production override requires {token[:-2]}", token in override)
    check(
        "production override has no demo placeholder secret",
        "secret-key" not in override.lower(),
    )
    check(
        "production override does not enable email test mode",
        not re.search(r"EMAIL_TEST_MODE\s*=\s*[\"']?true", override, re.I),
    )
    bad_secret_assignment = []
    for line in override.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.search(r"(SECRET|PASSWORD|TOKEN|CREDENTIAL|API_KEY)", stripped, re.I):
            if ":" not in stripped and "=" not in stripped:
                continue
            value = re.split(r"[:=]", stripped, maxsplit=1)[1].strip().strip("\"'")
            if not value.startswith("${"):
                bad_secret_assignment.append(stripped)
    check(
        "production override stores no literal secret values",
        not bad_secret_assignment,
        "; ".join(bad_secret_assignment) if bad_secret_assignment else "",
    )

if RUNBOOK.is_file():
    runbook = read(RUNBOOK)
    check(
        "runbook uses the production override in the up command",
        "-f docker-compose.production.override.yml" in runbook
        and "up -d --no-build" in runbook,
    )
    check(
        "runbook names both banned override files",
        "docker-compose.demo.override.yml" in runbook
        and "docker-compose.dev.override.yml" in runbook,
    )
    check(
        "runbook requires config --quiet validation",
        "config --quiet" in runbook,
    )
    check(
        "runbook states EMAIL_TEST_MODE=false",
        "EMAIL_TEST_MODE" in runbook and "`false`" in runbook,
    )

if RUNBOOKS.is_dir():
    destructive = []
    for path in sorted(RUNBOOKS.glob("*.md")):
        for number, line in enumerate(read(path).splitlines(), start=1):
            if "down -v" in line.lower() and not re.search(
                r"\b(never|prohibited|banned|forbidden|not allowed|do not)\b", line, re.I
            ):
                destructive.append(f"{path.name}:{number}")
    check("runbooks contain no executable down -v command", not destructive, ", ".join(destructive))

for path in ENV_EXAMPLES:
    if path.is_file():
        enabled = [
            line.strip()
            for line in read(path).splitlines()
            if not line.lstrip().startswith("#")
            and re.match(r"^\s*EMAIL_TEST_MODE\s*=\s*[\"']?true", line, re.I)
        ]
        check(
            f"{path.relative_to(ROOT)} does not enable email test mode",
            not enabled,
            "; ".join(enabled) if enabled else "",
        )

try:
    result = subprocess.run(
        ["git", "diff", "--quiet", "--", "docker-compose.yml"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    check("base docker-compose.yml is unchanged", result.returncode == 0)
except OSError as exc:
    check("base docker-compose.yml is unchanged", False, f"git unavailable: {exc}")

print(f"\nSUMMARY: {'PASS' if not failures else 'FAIL'} ({len(failures)} failure(s))")
sys.exit(1 if failures else 0)
