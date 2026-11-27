# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Isolated restore drill helper for PLN-025.

This tool never touches a production database. It requires an explicit
``--confirm`` and a non-production target database name, verifies the manifest
before restoring, and copies objects only into a clearly named staging bucket.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_common import (  # noqa: E402 - path bootstrap must precede local imports
    BackupError,
    ComposeConfig,
    RestoreSafetyError,
    build_createdb_command,
    build_dropdb_command,
    build_hook_command,
    build_mc_bucket_create_command,
    build_mc_copy_command,
    build_pg_restore_command,
    load_manifest,
    map_host_to_mc_path,
    parse_path_mapping,
    resolve_artifact,
    run_command,
    validate_object_target,
    validate_restore_target,
    verify_manifest,
)

Runner = Callable[..., object]
LOGGER_NAME = "pln025.restore"


def configure_logging() -> logging.Logger:
    """Return a small logger that writes progress information to stderr."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


@dataclass(frozen=True)
class RestoreSettings:
    """All settings needed for one isolated restore."""

    backup_dir: Path
    target_db: str
    compose: ComposeConfig
    confirm: bool
    dry_run: bool
    correlation_id: str
    mc_command: str | None = None
    object_target_bucket: str | None = None
    decrypt_command: str | None = None
    config_destination: Path | None = None
    config_decrypt_command: str | None = None
    skip_config: bool = False
    mc_path_maps: tuple[tuple[str, str], ...] = ()


def source_bucket_from_object_source(object_source: str | None) -> str | None:
    """Extract the bucket name from an mc source such as ``local/uploads``."""
    if not object_source:
        return None
    _alias, separator, remainder = object_source.partition("/")
    if not separator:
        return object_source
    return remainder.split("/", 1)[0] or None


def manifest_artifact_path(backup_dir: Path, manifest: dict, kind: str) -> Path | None:
    """Find the first manifest artifact path of a given kind."""
    manifest_path = Path(backup_dir) / "manifest.json"
    for entry in manifest.get("artifacts", []):
        if entry.get("kind") == kind:
            return resolve_artifact(manifest_path, entry)
    return None


def config_entries(manifest: dict) -> list[dict]:
    """Return manifest entries for separately encrypted configuration files."""
    return [
        entry
        for entry in manifest.get("artifacts", [])
        if entry.get("kind") == "config"
    ]


def validate_config_restore(settings: RestoreSettings, manifest: dict) -> None:
    """Require an explicit staging destination and decrypt hook for config files."""
    entries = config_entries(manifest)
    if not entries or settings.skip_config:
        return
    if not settings.config_destination:
        raise RestoreSafetyError(
            "backup contains encrypted config; --config-destination is required "
            "or use --skip-config"
        )
    if not settings.config_decrypt_command:
        raise RestoreSafetyError(
            "backup contains encrypted config; --config-decrypt-command is required "
            "or use --skip-config"
        )
    destination = Path(settings.config_destination).resolve()
    if destination == Path(settings.backup_dir).resolve():
        raise RestoreSafetyError(
            "config destination must differ from the backup directory"
        )
    if destination.exists() and not destination.is_dir():
        raise RestoreSafetyError("config destination is not a directory")


def restore_config_artifacts(
    settings: RestoreSettings,
    manifest: dict,
    *,
    runner: Runner,
    logger: logging.Logger,
) -> int:
    """Decrypt configuration artifacts into an explicitly chosen staging directory."""
    entries = config_entries(manifest)
    if not entries or settings.skip_config:
        return 0
    if not settings.config_destination or not settings.config_decrypt_command:
        raise RestoreSafetyError("config restore settings are incomplete")

    destination_root = Path(settings.config_destination)
    destination_root.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(settings.backup_dir) / "manifest.json"
    restored = 0
    for entry in entries:
        source = resolve_artifact(manifest_path, entry)
        declared_name = Path(str(entry.get("source_name") or "config")).name
        target = destination_root / declared_name
        runner(
            build_hook_command(
                settings.config_decrypt_command, str(source), str(target)
            ),
            label="config-decrypt",
        )
        restored += 1
    logger.info("restored configuration files=%d", restored)
    return restored


def decrypt_artifacts(
    backup_dir: Path,
    manifest: dict,
    settings: RestoreSettings,
    *,
    runner: Runner,
    destination_root: Path,
) -> dict[str, Path]:
    """Decrypt encrypted artifacts into a temporary directory when required."""
    encrypted = [
        entry
        for entry in manifest.get("artifacts", [])
        if entry.get("encrypted") and entry.get("kind") != "config"
    ]
    if not encrypted:
        return {}
    if not settings.decrypt_command:
        raise RestoreSafetyError("encrypted backup requires --decrypt-command")

    decrypted: dict[str, Path] = {}
    for entry in encrypted:
        manifest_path = Path(backup_dir) / "manifest.json"
        source = resolve_artifact(manifest_path, entry)
        relative = Path(str(entry["path"]))
        if relative.suffix == ".enc":
            relative = relative.with_suffix("")
        target = destination_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        runner(
            build_hook_command(settings.decrypt_command, str(source), str(target)),
            label="decrypt",
        )
        decrypted[str(entry.get("kind"))] = target
    return decrypted


def prepare_restore(
    settings: RestoreSettings,
    *,
    runner: Runner,
    logger: logging.Logger,
) -> dict:
    """Validate settings and manifest before any restore command is issued."""
    if not settings.confirm:
        raise RestoreSafetyError("restore requires --confirm")
    validate_restore_target(settings.target_db)

    manifest_path = Path(settings.backup_dir) / "manifest.json"
    errors = verify_manifest(manifest_path)
    if errors:
        raise RestoreSafetyError(
            f"manifest verification failed with {len(errors)} problem(s)"
        )
    manifest = load_manifest(manifest_path)

    source_bucket = source_bucket_from_object_source(manifest.get("object_source"))
    if settings.mc_command and not settings.object_target_bucket:
        raise RestoreSafetyError("object restore requires --object-target-bucket")
    if settings.object_target_bucket:
        validate_object_target(
            settings.object_target_bucket, source_bucket=source_bucket
        )
    validate_config_restore(settings, manifest)

    logger.info(
        "manifest verified correlation=%s artifacts=%d",
        settings.correlation_id,
        len(manifest.get("artifacts", [])),
    )
    return manifest


def run_restore(
    settings: RestoreSettings,
    *,
    runner: Runner = run_command,
    logger: logging.Logger | None = None,
) -> dict:
    """Restore a verified backup into an explicitly named staging database."""
    log = logger or configure_logging()
    manifest = prepare_restore(settings, runner=runner, logger=log)
    object_entries = [
        entry
        for entry in manifest.get("artifacts", [])
        if entry.get("kind") == "object"
    ]
    dump_entry = next(
        (
            entry
            for entry in manifest.get("artifacts", [])
            if entry.get("kind") == "db_dump"
        ),
        {"path": "db.dump"},
    )
    plan = {
        "target_db": settings.target_db,
        "object_target_bucket": settings.object_target_bucket,
        "dump": Path(str(dump_entry.get("path"))).name,
        "object_files": len(object_entries),
    }
    if settings.dry_run:
        log.info("dry-run: no database or object changes were made")
        return {"success": True, "dry_run": True, **plan}

    with tempfile.TemporaryDirectory(prefix=".pln025-restore-") as temporary:
        temporary_root = Path(temporary)
        decrypted = decrypt_artifacts(
            settings.backup_dir,
            manifest,
            settings,
            runner=runner,
            destination_root=temporary_root,
        )
        dump_path = decrypted.get("db_dump") or manifest_artifact_path(
            settings.backup_dir, manifest, "db_dump"
        )
        if dump_path is None or not dump_path.is_file():
            raise RestoreSafetyError("custom-format dump is missing from the backup")

        object_source_host = Path(settings.backup_dir) / "objects"
        if object_entries and any(entry.get("encrypted") for entry in object_entries):
            object_source_host = temporary_root / "objects"

        runner(
            build_dropdb_command(settings.compose, settings.target_db),
            label="dropdb-staging",
        )
        runner(
            build_createdb_command(settings.compose, settings.target_db),
            label="createdb-staging",
        )
        runner(
            build_pg_restore_command(settings.compose, settings.target_db),
            label="pg_restore",
            stdin_path=dump_path,
        )
        log.info("restored database %s", settings.target_db)

        if (
            settings.mc_command
            and settings.object_target_bucket
            and object_source_host.is_dir()
        ):
            object_source = map_host_to_mc_path(
                object_source_host, settings.mc_path_maps
            )
            alias = str(manifest.get("object_source") or "").split("/", 1)[0] or "local"
            bucket_target = f"{alias}/{settings.object_target_bucket}"
            runner(
                build_mc_bucket_create_command(settings.mc_command, bucket_target),
                label="object-staging-bucket",
            )
            runner(
                build_mc_copy_command(
                    settings.mc_command, object_source, bucket_target
                ),
                label="object-staging-copy",
            )
            log.info(
                "restored objects to staging bucket %s", settings.object_target_bucket
            )

        plan["config_files"] = restore_config_artifacts(
            settings, manifest, runner=runner, logger=log
        )
        return {"success": True, "dry_run": False, **plan}


def build_parser() -> argparse.ArgumentParser:
    """Build the restore CLI parser."""
    parser = argparse.ArgumentParser(
        description="Restore a PLN-025 backup into an isolated staging target."
    )
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument(
        "--target-db",
        required=True,
        help="must be a non-production name such as plane_restore",
    )
    parser.add_argument(
        "--confirm", action="store_true", help="required safety confirmation"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--compose-project", default=None)
    parser.add_argument(
        "--compose-file", action="append", default=[], dest="compose_files"
    )
    parser.add_argument("--db-service", default="plane-db")
    parser.add_argument(
        "--db-user",
        default=os.environ.get("PLN025_DB_USER", os.environ.get("POSTGRES_USER", "plane")),
        help="Postgres role used for restore; password must come from the environment",
    )
    parser.add_argument(
        "--mc-command",
        default=None,
        help="mc command prefix for staging object restore",
    )
    parser.add_argument(
        "--object-target-bucket",
        default=None,
        help="must start with restore- or staging-",
    )
    parser.add_argument(
        "--decrypt-command", default=None, help="hook receiving ENCRYPTED OUTPUT paths"
    )
    parser.add_argument(
        "--config-destination",
        type=Path,
        default=None,
        help="staging directory for separately encrypted configuration artifacts",
    )
    parser.add_argument(
        "--config-decrypt-command",
        default=None,
        help="separate decrypt hook for configuration artifacts",
    )
    parser.add_argument(
        "--skip-config",
        action="store_true",
        help="explicitly skip configuration artifacts during a drill",
    )
    parser.add_argument(
        "--mc-path-map",
        action="append",
        default=[],
        dest="mc_path_maps",
        metavar="CONTAINER_PATH=HOST_PATH",
    )
    parser.add_argument("--correlation-id", default=uuid.uuid4().hex[:12])
    return parser


def settings_from_args(args: argparse.Namespace) -> RestoreSettings:
    """Convert parsed CLI arguments into immutable settings."""
    return RestoreSettings(
        backup_dir=args.backup_dir,
        target_db=args.target_db,
        compose=ComposeConfig(
            compose_project=args.compose_project,
            compose_files=tuple(args.compose_files),
            db_service=args.db_service,
            db_user=args.db_user,
        ),
        confirm=args.confirm,
        dry_run=args.dry_run,
        correlation_id=args.correlation_id,
        mc_command=args.mc_command,
        object_target_bucket=args.object_target_bucket,
        decrypt_command=args.decrypt_command,
        config_destination=args.config_destination,
        config_decrypt_command=args.config_decrypt_command,
        skip_config=args.skip_config,
        mc_path_maps=tuple(parse_path_mapping(item) for item in args.mc_path_maps),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns non-zero for any failed or refused restore."""
    args = build_parser().parse_args(argv)
    settings = settings_from_args(args)
    logger = configure_logging()
    try:
        result = run_restore(settings, logger=logger)
    except (BackupError, RestoreSafetyError, OSError) as error:
        logger.error(
            "restore refused or failed: %s", str(error) or type(error).__name__
        )
        return 1
    if result["dry_run"]:
        print("RESTORE=DRY_RUN")
    else:
        print(f"RESTORE=OK target_db={result['target_db']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
