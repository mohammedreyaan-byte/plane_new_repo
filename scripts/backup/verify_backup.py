# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Verify a PLN-025 backup directory without restoring it.

Checks every checksum and size recorded in the manifest, validates the stored
``pg_restore --list`` output, and can optionally re-run pg_restore against the
dump for independent confirmation.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_common import (  # noqa: E402 - path bootstrap must precede local imports
    ComposeConfig,
    build_pg_restore_list_command,
    parse_restore_list,
    resolve_artifact,
    run_command,
    verify_manifest,
)


def find_manifest(backup_dir: Path, manifest_name: str = "manifest.json") -> Path:
    """Return the manifest path inside a backup directory."""
    manifest_path = Path(backup_dir) / manifest_name
    if not manifest_path.is_file():
        raise FileNotFoundError("manifest.json is missing from the backup directory")
    return manifest_path


def verify_dump_list(
    backup_dir: Path,
    config: ComposeConfig,
    *,
    runner=run_command,
    manifest_name: str = "manifest.json",
) -> list[str]:
    """Re-run pg_restore --list and compare it with the recorded dump list."""
    from backup_common import load_manifest  # noqa: PLC0415 - keep CLI imports light

    manifest_path = find_manifest(backup_dir, manifest_name)
    manifest = load_manifest(manifest_path)
    dump_entry = next(
        (
            entry
            for entry in manifest.get("artifacts", [])
            if entry.get("kind") == "db_dump"
        ),
        None,
    )
    if dump_entry is None:
        return ["manifest has no custom-format dump artifact"]

    errors: list[str] = []
    dump_path = resolve_artifact(manifest_path, dump_entry)
    with tempfile.TemporaryDirectory(prefix=".pln025-verify-") as temporary:
        list_path = Path(temporary) / "restore-list.txt"
        runner(
            build_pg_restore_list_command(config),
            label="pg_restore-list",
            stdin_path=dump_path,
            stdout_path=list_path,
        )
        listed = parse_restore_list(
            list_path.read_text(encoding="utf-8", errors="replace")
        )
    if not listed:
        errors.append("pg_restore list contains no objects")
    declared = parse_restore_list(manifest.get("dump_list", []))
    if declared != listed:
        errors.append("pg_restore list differs from the manifest dump_list")
    return errors


def build_parser() -> argparse.ArgumentParser:
    """Build the verification CLI parser."""
    parser = argparse.ArgumentParser(description="Verify a PLN-025 backup directory.")
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--manifest", default="manifest.json")
    parser.add_argument("--run-pg-restore", action="store_true")
    parser.add_argument("--compose-project", default=None)
    parser.add_argument(
        "--compose-file", action="append", default=[], dest="compose_files"
    )
    parser.add_argument("--db-service", default="plane-db")
    parser.add_argument(
        "--db-user",
        default=os.environ.get("PLN025_DB_USER", os.environ.get("POSTGRES_USER", "plane")),
        help="Postgres role used for pg_restore verification",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns non-zero when any verification fails."""
    args = build_parser().parse_args(argv)
    errors: list[str] = []
    try:
        manifest_path = find_manifest(args.backup_dir, args.manifest)
    except FileNotFoundError as error:
        print(f"VERIFY=FAIL: {error}", file=sys.stderr)
        return 1

    errors.extend(verify_manifest(manifest_path))
    if args.run_pg_restore:
        config = ComposeConfig(
            compose_project=args.compose_project,
            compose_files=tuple(args.compose_files),
            db_service=args.db_service,
            db_user=args.db_user,
        )
        try:
            errors.extend(verify_dump_list(args.backup_dir, config))
        except Exception as error:  # noqa: BLE001 - report verification failures uniformly
            errors.append(f"pg_restore verification failed: {type(error).__name__}")

    if errors:
        for error in errors:
            print(f"VERIFY=FAIL: {error}", file=sys.stderr)
        return 1
    print("VERIFY=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
