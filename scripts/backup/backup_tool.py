# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Production-oriented, standard-library-only backup orchestrator for PLN-025.

Creates a timestamped logical Postgres backup (custom dump + plain schema dump),
verifies it with ``pg_restore --list``, mirrors object storage through a
configurable ``mc`` command, writes a checksum manifest, and prunes old backups
under the 7 daily / 4 weekly / 12 monthly policy.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from backup_common import (
    BackupError,
    ComposeConfig,
    CommandError,
    OverlapError,
    acquire_lock,
    build_hook_command,
    build_manifest,
    build_mc_mirror_command,
    build_pg_dump_command,
    build_pg_restore_list_command,
    compute_sha256,
    is_stale,
    load_manifest,
    make_manifest_entry,
    map_mc_path,
    parse_path_mapping,
    parse_restore_list,
    run_command,
    select_prune_candidates,
    write_manifest,
)

Runner = Callable[..., object]
LOGGER_NAME = "pln025.backup"
SAFE_CORRELATION_RE = re.compile(r"[^A-Za-z0-9_-]")


class CorrelationFilter(logging.Filter):
    """Attach a correlation id to every log record."""

    def __init__(self, correlation_id: str) -> None:
        super().__init__()
        self.correlation_id = correlation_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = self.correlation_id
        return True


def configure_logging(correlation_id: str) -> logging.Logger:
    """Configure a correlation-aware logger without touching other loggers."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s correlation=%(correlation_id)s %(message)s"
            )
        )
        logger.addHandler(handler)
    logger.handlers[0].addFilter(CorrelationFilter(correlation_id))
    return logger


@dataclass(frozen=True)
class BackupSettings:
    """All settings needed for one backup run."""

    backup_root: Path
    db_name: str
    compose: ComposeConfig
    correlation_id: str
    strict: bool = True
    mc_command: str | None = None
    object_source: str | None = None
    object_destination_template: str | None = None
    mc_path_maps: tuple[tuple[str, str], ...] = ()
    encrypt_command: str | None = None
    alert_command: str | None = None
    staleness_hours: float = 26.0
    retention_daily: int = 7
    retention_weekly: int = 4
    retention_monthly: int = 12
    config_sources: tuple[Path, ...] = ()
    config_encrypt_command: str | None = None


def discover_backup_dirs(root: Path) -> list[dict]:
    """List successful/failed backup directories by reading their manifests."""
    discovered: list[dict] = []
    for manifest_path in sorted(Path(root).glob("*/manifest.json")):
        try:
            manifest = load_manifest(manifest_path)
            created_at = str(manifest["created_at"])
        except (BackupError, KeyError):
            continue
        discovered.append(
            {
                "path": str(manifest_path.parent),
                "created_at": created_at,
                "success": bool(manifest.get("success", False)),
            }
        )
    return discovered


def latest_successful_backup(root: Path) -> str | None:
    """Return the newest successful manifest timestamp, if one exists."""
    successes = [
        item["created_at"] for item in discover_backup_dirs(root) if item["success"]
    ]
    return max(successes) if successes else None


def send_alert(
    settings: BackupSettings, reason: str, *, runner: Runner, logger: logging.Logger
) -> None:
    """Invoke the optional alert hook; alert failures never mask the original error."""
    if not settings.alert_command:
        logger.warning("alert hook not configured (reason=%s)", reason)
        return
    message = f"PLN-025 correlation={settings.correlation_id} reason={reason}"
    try:
        runner(build_hook_command(settings.alert_command, message), label="alert")
    except Exception as error:  # noqa: BLE001 - alerting is best-effort by design
        logger.warning("alert hook failed: %s", type(error).__name__)


def warn_if_stale(
    settings: BackupSettings, now: datetime, *, runner: Runner, logger: logging.Logger
) -> None:
    """Alert when the most recent successful backup is outside the staleness window."""
    newest = latest_successful_backup(settings.backup_root)
    if is_stale(newest, now, hours=settings.staleness_hours):
        send_alert(settings, "stale-backup", runner=runner, logger=logger)


def sanitize_correlation_id(correlation_id: str) -> str:
    """Reduce a correlation id to a safe artifact-name suffix."""
    cleaned = SAFE_CORRELATION_RE.sub("-", correlation_id).strip("-")
    return cleaned[:16] or "cid"


def format_object_destination(
    template: str,
    *,
    staging_name: str,
    final_name: str,
    correlation_id: str,
    timestamp: str,
) -> str:
    """Expand supported placeholders in the mc-visible object destination."""
    try:
        return template.format(
            artifact=staging_name,
            staging=staging_name,
            final=final_name,
            correlation_id=correlation_id,
            timestamp=timestamp,
        )
    except (KeyError, ValueError) as error:
        raise BackupError(
            "object destination template contains an unsupported placeholder"
        ) from error


def encrypt_entries(
    entries: list[dict],
    *,
    artifact_root: Path,
    settings: BackupSettings,
    runner: Runner,
    logger: logging.Logger,
) -> list[dict]:
    """Run the encryption hook and replace plaintext entries with encrypted ones."""
    if not settings.encrypt_command:
        return entries
    encrypted: list[dict] = []
    for entry in entries:
        source = artifact_root / str(entry["path"])
        destination = source.with_name(source.name + ".enc")
        runner(
            build_hook_command(settings.encrypt_command, str(source), str(destination)),
            label="encrypt",
        )
        source.unlink()
        relative = destination.resolve().relative_to(artifact_root.resolve()).as_posix()
        encrypted.append(
            {
                **entry,
                "path": relative,
                "sha256": compute_sha256(destination),
                "size": destination.stat().st_size,
                "encrypted": True,
            }
        )
    logger.info("encrypted %d artifacts", len(encrypted))
    return encrypted


def collect_config_artifacts(
    *,
    artifact_root: Path,
    settings: BackupSettings,
    runner: Runner,
    logger: logging.Logger,
) -> list[dict]:
    """Encrypt configuration files with a separate hook and key custody."""
    if not settings.config_sources:
        return []
    if not settings.config_encrypt_command:
        raise BackupError("config sources require --config-encrypt-command")
    config_dir = Path(artifact_root) / "config"
    config_dir.mkdir(exist_ok=True)
    entries: list[dict] = []
    for index, source in enumerate(settings.config_sources):
        source_path = Path(source)
        if not source_path.is_file():
            raise BackupError("configuration source is not a regular file")
        name = SAFE_CORRELATION_RE.sub("-", source_path.name).strip("-") or "config"
        plaintext_path = config_dir / f"{index:02d}-{name}"
        encrypted_path = plaintext_path.with_name(plaintext_path.name + ".enc")
        shutil.copy2(source_path, plaintext_path)
        try:
            runner(
                build_hook_command(
                    settings.config_encrypt_command,
                    str(plaintext_path),
                    str(encrypted_path),
                ),
                label="config-encrypt",
            )
            entry = make_manifest_entry(encrypted_path, artifact_root, "config")
            entry["encrypted"] = True
            entry["source_name"] = source_path.name
            entries.append(entry)
        finally:
            plaintext_path.unlink(missing_ok=True)
    logger.info("encrypted configuration files=%d", len(entries))
    return entries


def prune_backups(
    settings: BackupSettings,
    *,
    final_dir: Path,
    now: datetime,
    logger: logging.Logger,
) -> None:
    """Apply retention, protecting the just-completed backup directory."""
    candidates = select_prune_candidates(
        discover_backup_dirs(settings.backup_root),
        now,
        daily=settings.retention_daily,
        weekly=settings.retention_weekly,
        monthly=settings.retention_monthly,
        keep_paths=[final_dir],
    )
    root = settings.backup_root.resolve()
    for candidate in candidates:
        path = Path(candidate)
        if path.resolve() == final_dir.resolve() or path.parent.resolve() != root:
            continue
        logger.info("pruning backup directory %s", path.name)
        shutil.rmtree(path, ignore_errors=True)


def run_backup(
    settings: BackupSettings,
    *,
    runner: Runner = run_command,
    now: datetime | None = None,
    logger: logging.Logger | None = None,
) -> dict:
    """Execute one backup run and return a small result dictionary."""
    current_time = now or datetime.now(timezone.utc)
    log = logger or configure_logging(settings.correlation_id)
    timestamp = current_time.strftime("%Y%m%dT%H%M%SZ")
    final_name = f"{timestamp}-{sanitize_correlation_id(settings.correlation_id)}"
    staging: Path | None = None

    if settings.object_source and not settings.mc_command:
        raise BackupError("object source requires --mc-command")

    try:
        with acquire_lock(
            settings.backup_root / ".backup.lock", settings.correlation_id
        ):
            staging = Path(
                tempfile.mkdtemp(prefix=".pln025-", dir=settings.backup_root)
            )
            log.info(
                "starting backup database=%s artifacts=%s",
                settings.db_name,
                staging.name,
            )
            warn_if_stale(settings, current_time, runner=runner, logger=log)

            dump_path = staging / "db.dump"
            schema_path = staging / "schema.sql"
            restore_list_path = staging / "restore-list.txt"

            runner(
                build_pg_dump_command(settings.compose, settings.db_name),
                label="pg_dump",
                stdout_path=dump_path,
            )
            entries = [make_manifest_entry(dump_path, staging, "db_dump")]

            runner(
                build_pg_dump_command(
                    settings.compose, settings.db_name, schema_only=True
                ),
                label="pg_dump-schema",
                stdout_path=schema_path,
            )
            entries.append(make_manifest_entry(schema_path, staging, "schema_sql"))

            runner(
                build_pg_restore_list_command(settings.compose),
                label="pg_restore-list",
                stdin_path=dump_path,
                stdout_path=restore_list_path,
            )
            dump_list = parse_restore_list(
                restore_list_path.read_text(encoding="utf-8", errors="replace")
            )
            if not dump_list:
                raise BackupError("pg_restore list contains no objects")
            entries.append(
                make_manifest_entry(restore_list_path, staging, "restore_list")
            )

            if settings.mc_command and settings.object_source:
                destination_template = (
                    settings.object_destination_template or "{artifact}/objects"
                )
                mc_destination = format_object_destination(
                    destination_template,
                    staging_name=staging.name,
                    final_name=final_name,
                    correlation_id=settings.correlation_id,
                    timestamp=timestamp,
                )
                host_destination = Path(
                    map_mc_path(mc_destination, settings.mc_path_maps)
                )
                host_destination.mkdir(parents=True, exist_ok=True)
                runner(
                    build_mc_mirror_command(
                        settings.mc_command, settings.object_source, mc_destination
                    ),
                    label="object-mirror",
                )
                object_files = sorted(
                    path for path in host_destination.rglob("*") if path.is_file()
                )
                entries.extend(
                    make_manifest_entry(path, staging, "object")
                    for path in object_files
                )
                log.info("mirrored object storage files=%d", len(object_files))

            entries = encrypt_entries(
                entries,
                artifact_root=staging,
                settings=settings,
                runner=runner,
                logger=log,
            )
            entries.extend(
                collect_config_artifacts(
                    artifact_root=staging,
                    settings=settings,
                    runner=runner,
                    logger=log,
                )
            )
            manifest = build_manifest(
                correlation_id=settings.correlation_id,
                created_at=current_time,
                database=settings.db_name,
                artifacts=entries,
                dump_list=dump_list,
                object_source=settings.object_source,
            )
            write_manifest(staging / "manifest.json", manifest)

            final_dir = settings.backup_root / final_name
            if final_dir.exists():
                raise BackupError("target backup directory already exists")
            os.replace(staging, final_dir)
            staging = None
            prune_backups(settings, final_dir=final_dir, now=current_time, logger=log)
            log.info(
                "backup completed directory=%s checksums=%d", final_name, len(entries)
            )
            return {
                "success": True,
                "artifact_dir": final_dir,
                "manifest_path": final_dir / "manifest.json",
                "artifact_name": final_name,
            }
    except Exception as error:
        if staging is not None and settings.strict and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if isinstance(error, (BackupError, CommandError, OverlapError, OSError)):
            raise
        raise BackupError(f"backup failed: {type(error).__name__}") from error


def build_parser() -> argparse.ArgumentParser:
    """Build the backup CLI parser."""
    parser = argparse.ArgumentParser(
        description="Create a verified Plane backup (PLN-025)."
    )
    parser.add_argument("--backup-root", type=Path, default=Path("backups"))
    parser.add_argument("--db-name", default=os.environ.get("POSTGRES_DB", "plane"))
    parser.add_argument(
        "--db-user",
        default=os.environ.get("PLN025_DB_USER", os.environ.get("POSTGRES_USER", "plane")),
        help="Postgres role used by pg_dump; password must come from the environment",
    )
    parser.add_argument("--compose-project", default=None)
    parser.add_argument(
        "--compose-file", action="append", default=[], dest="compose_files"
    )
    parser.add_argument("--db-service", default="plane-db")
    parser.add_argument(
        "--mc-command",
        default=None,
        help="mc command prefix; omit to skip object mirroring",
    )
    parser.add_argument(
        "--object-source", default=None, help="mc alias/path such as local/uploads"
    )
    parser.add_argument(
        "--object-destination",
        default=None,
        help="mc-visible destination; supports {artifact} and {timestamp}",
    )
    parser.add_argument(
        "--mc-path-map",
        action="append",
        default=[],
        dest="mc_path_maps",
        metavar="CONTAINER_PATH=HOST_PATH",
    )
    parser.add_argument(
        "--encrypt-command", default=None, help="hook receiving INPUT OUTPUT paths"
    )
    parser.add_argument(
        "--config-source",
        action="append",
        type=Path,
        default=[],
        dest="config_sources",
        help="configuration or secret file to encrypt separately; may be repeated",
    )
    parser.add_argument(
        "--config-encrypt-command",
        default=None,
        help="separate encryption hook for configuration artifacts",
    )
    parser.add_argument(
        "--alert-command", default=None, help="hook receiving one message argument"
    )
    parser.add_argument("--staleness-hours", type=float, default=26.0)
    parser.add_argument("--retention-daily", type=int, default=7)
    parser.add_argument("--retention-weekly", type=int, default=4)
    parser.add_argument("--retention-monthly", type=int, default=12)
    parser.add_argument("--correlation-id", default=uuid.uuid4().hex[:12])
    parser.add_argument("--strict", dest="strict", action="store_true", default=True)
    parser.add_argument("--no-strict", dest="strict", action="store_false")
    return parser


def settings_from_args(args: argparse.Namespace) -> BackupSettings:
    """Convert parsed CLI arguments into immutable settings."""
    return BackupSettings(
        backup_root=args.backup_root,
        db_name=args.db_name,
        compose=ComposeConfig(
            compose_project=args.compose_project,
            compose_files=tuple(args.compose_files),
            db_service=args.db_service,
            db_user=args.db_user,
        ),
        correlation_id=args.correlation_id,
        strict=args.strict,
        mc_command=args.mc_command,
        object_source=args.object_source,
        object_destination_template=args.object_destination,
        mc_path_maps=tuple(parse_path_mapping(item) for item in args.mc_path_maps),
        encrypt_command=args.encrypt_command,
        config_sources=tuple(args.config_sources),
        config_encrypt_command=args.config_encrypt_command,
        alert_command=args.alert_command,
        staleness_hours=args.staleness_hours,
        retention_daily=args.retention_daily,
        retention_weekly=args.retention_weekly,
        retention_monthly=args.retention_monthly,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns 0 only when every enabled step succeeds."""
    args = build_parser().parse_args(argv)
    settings = settings_from_args(args)
    logger = configure_logging(settings.correlation_id)
    try:
        result = run_backup(settings, logger=logger)
    except (BackupError, CommandError, OverlapError, OSError) as error:
        logger.error("backup failed: %s", str(error) or type(error).__name__)
        send_alert(settings, "backup-failed", runner=run_command, logger=logger)
        return 1
    print(f"ARTIFACT_DIR={result['artifact_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
