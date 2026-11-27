# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared, standard-library-only helpers for the PLN-025 backup tools.

The functions in this module are deliberately pure where practical so the
command construction, manifest and retention policy can be unit tested without
Docker, Postgres or object storage.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

MANIFEST_SCHEMA = "pln025.backup.v1"
DEFAULT_DB_SERVICE = "plane-db"
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BackupError(RuntimeError):
    """Base error for all backup/restore tooling failures."""


class CommandError(BackupError):
    """A subprocess failed; details are intentionally kept out of the message."""


class OverlapError(BackupError):
    """Another backup process already holds the lock."""


class RestoreSafetyError(BackupError):
    """A restore target failed its safety checks."""


@dataclass(frozen=True)
class ComposeConfig:
    """Command-line settings that shape Docker Compose command prefixes."""

    compose_project: str | None = None
    compose_files: tuple[str, ...] = ()
    db_service: str = DEFAULT_DB_SERVICE
    db_user: str = "plane"


@dataclass
class LockHandle:
    """An exclusive lock file that is released on context-manager exit."""

    path: Path
    fd: int | None

    def release(self) -> None:
        if self.fd is None:
            return
        with suppress(OSError):
            os.close(self.fd)
        self.fd = None
        with suppress(FileNotFoundError):
            self.path.unlink()

    def __enter__(self) -> LockHandle:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def build_compose_prefix(config: ComposeConfig) -> list[str]:
    """Build the ``docker compose`` prefix shared by all database commands."""
    command = ["docker", "compose"]
    for compose_file in config.compose_files:
        command.extend(["-f", compose_file])
    if config.compose_project:
        command.extend(["-p", config.compose_project])
    return command


def _compose_exec(config: ComposeConfig) -> list[str]:
    return [*build_compose_prefix(config), "exec", "-T", config.db_service]


def build_pg_dump_command(
    config: ComposeConfig, db_name: str, *, schema_only: bool = False
) -> list[str]:
    """Build a pg_dump command writing a custom or plain SQL dump to stdout."""
    command = _compose_exec(config)
    command.append("pg_dump")
    if schema_only:
        command.append("--schema-only")
    else:
        command.append("-Fc")
    command.extend(
        [
            "--no-owner",
            "--no-privileges",
            "--username",
            config.db_user,
            "--dbname",
            db_name,
        ]
    )
    return command


def build_pg_restore_list_command(config: ComposeConfig) -> list[str]:
    """Build the pg_restore command used to inspect a dump before trusting it."""
    return [
        *_compose_exec(config),
        "pg_restore",
        "--list",
        "--username",
        config.db_user,
    ]


def build_createdb_command(config: ComposeConfig, db_name: str) -> list[str]:
    """Build a createdb command for an explicitly named, non-production database."""
    return [
        *_compose_exec(config),
        "createdb",
        "--username",
        config.db_user,
        db_name,
    ]


def build_dropdb_command(config: ComposeConfig, db_name: str) -> list[str]:
    """Build an idempotent dropdb command for an explicitly named staging database."""
    return [
        *_compose_exec(config),
        "dropdb",
        "--if-exists",
        "--username",
        config.db_user,
        db_name,
    ]


def build_pg_restore_command(config: ComposeConfig, db_name: str) -> list[str]:
    """Build a pg_restore command that reads the custom-format dump from stdin."""
    return [
        *_compose_exec(config),
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "--username",
        config.db_user,
        "--dbname",
        db_name,
    ]


def build_mc_prefix(mc_command: str) -> list[str]:
    """Parse a configurable ``mc`` command prefix without invoking a shell."""
    parts = shlex.split(mc_command)
    if not parts:
        raise BackupError("mc command prefix is empty")
    return parts


def build_mc_mirror_command(
    mc_command: str, source: str, destination: str
) -> list[str]:
    """Build an object-storage mirror command (source is an mc alias/path)."""
    return [*build_mc_prefix(mc_command), "mirror", "--overwrite", source, destination]


def build_mc_bucket_create_command(mc_command: str, target: str) -> list[str]:
    """Build an idempotent bucket-create command for a staging target."""
    return [*build_mc_prefix(mc_command), "mb", target, "-p"]


def build_mc_copy_command(mc_command: str, source: str, target: str) -> list[str]:
    """Build an object copy command that restores objects into a staging bucket.

    The source must end with a slash so ``mc cp`` copies the directory contents
    into the bucket root. A ``/.`` suffix makes MinIO keep the parent directory
    name as an additional object key prefix, which breaks manifest comparison.
    """
    normalized_source = source.replace("\\", "/")
    while normalized_source.endswith("/."):
        normalized_source = normalized_source[: -len("/.")]
    normalized_source = normalized_source.rstrip("/") + "/"
    return [
        *build_mc_prefix(mc_command),
        "cp",
        "--recursive",
        normalized_source,
        target,
    ]


def build_hook_command(prefix: str, *arguments: str) -> list[str]:
    """Build an encryption/alert hook command from a configurable prefix."""
    parts = shlex.split(prefix)
    if not parts:
        raise BackupError("hook command prefix is empty")
    return [*parts, *arguments]


def parse_restore_list(output: str | bytes | Sequence[str] | None) -> list[str]:
    """Return object lines from pg_restore output or a stored manifest list."""
    if output is None:
        return []
    if isinstance(output, bytes):
        text = output.decode("utf-8", errors="replace")
    elif isinstance(output, str):
        text = output
    else:
        return [
            line.strip()
            for line in output
            if line.strip() and not line.lstrip().startswith(";")
        ]
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(";")
    ]


def parse_timestamp(value: str | datetime) -> datetime:
    """Parse an ISO-8601 timestamp, normalising naive values to UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def compute_sha256(path: Path) -> str:
    """Stream a file through SHA-256 without loading it into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_manifest_entry(
    path: Path, artifact_root: Path, kind: str, *, encrypted: bool = False
) -> dict:
    """Create a manifest entry with a path relative to the artifact directory."""
    resolved = Path(path).resolve()
    root = Path(artifact_root).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise BackupError("artifact path is outside the backup directory") from error
    return {
        "path": relative.as_posix(),
        "sha256": compute_sha256(resolved),
        "size": resolved.stat().st_size,
        "kind": kind,
        "encrypted": encrypted,
    }


def build_manifest(
    *,
    correlation_id: str,
    created_at: datetime,
    database: str,
    artifacts: Sequence[Mapping[str, object]],
    dump_list: Sequence[str],
    object_source: str | None = None,
) -> dict:
    """Assemble the manifest written last, after every other artifact succeeds."""
    return {
        "schema": MANIFEST_SCHEMA,
        "correlation_id": correlation_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "database": database,
        "success": True,
        "object_source": object_source,
        "dump_list": list(dump_list),
        "artifacts": [dict(artifact) for artifact in artifacts],
    }


def write_manifest(path: Path, manifest: Mapping[str, object]) -> None:
    """Write a deterministic, human-readable manifest."""
    Path(path).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_manifest(path: Path) -> dict:
    """Load and minimally validate a manifest document."""
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BackupError("manifest cannot be read or parsed") from error
    if not isinstance(manifest, dict):
        raise BackupError("manifest is not a JSON object")
    return manifest


def resolve_artifact(manifest_path: Path, entry: Mapping[str, object]) -> Path:
    """Resolve a manifest entry path without allowing parent-directory escapes."""
    raw_path = str(entry.get("path", ""))
    if not raw_path:
        raise BackupError("manifest artifact has no path")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    base = Path(manifest_path).resolve().parent
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base):
        raise BackupError("manifest artifact path escapes the backup directory")
    return resolved


def verify_manifest(manifest_path: Path) -> list[str]:
    """Verify checksums, sizes and the stored pg_restore object list.

    Returns a list of human-readable problems; an empty list means the artifact
    directory is internally consistent.
    """
    errors: list[str] = []
    try:
        manifest = load_manifest(manifest_path)
    except BackupError as error:
        return [str(error)]

    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append("unsupported manifest schema")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("manifest has no artifacts")
        return errors

    restore_list_entries = []
    for index, entry in enumerate(artifacts):
        if not isinstance(entry, dict):
            errors.append(f"artifact {index} is not an object")
            continue
        try:
            artifact_path = resolve_artifact(manifest_path, entry)
        except BackupError as error:
            errors.append(f"artifact {index}: {error}")
            continue
        if not artifact_path.is_file():
            errors.append(f"artifact {index} is missing")
            continue
        actual_hash = compute_sha256(artifact_path)
        if actual_hash != entry.get("sha256"):
            errors.append(f"checksum mismatch for {entry.get('path')}")
        if artifact_path.stat().st_size != entry.get("size"):
            errors.append(f"size mismatch for {entry.get('path')}")
        if entry.get("kind") == "restore_list":
            restore_list_entries.append((entry, artifact_path))

    if not restore_list_entries:
        errors.append("manifest has no pg_restore list artifact")
    else:
        entry, artifact_path = restore_list_entries[0]
        if not entry.get("encrypted"):
            listed = parse_restore_list(
                artifact_path.read_text(encoding="utf-8", errors="replace")
            )
            if not listed:
                errors.append("pg_restore list contains no objects")
            declared = parse_restore_list(manifest.get("dump_list", []))
            if declared != listed:
                errors.append("pg_restore list does not match the manifest dump_list")
    return errors


def select_prune_candidates(
    backups: Iterable[Mapping[str, object]],
    now: datetime,
    *,
    daily: int = 7,
    weekly: int = 4,
    monthly: int = 12,
    keep_paths: Iterable[str | Path] = (),
) -> list[str]:
    """Choose backup directories to prune under the 7/4/12 retention policy.

    The newest successful backup is always kept, even when it is older than the
    retention windows. Invalid timestamps are never pruned.
    """
    parsed: list[tuple[datetime, str, bool]] = []
    for backup in backups:
        try:
            created = parse_timestamp(str(backup.get("created_at", "")))
        except (TypeError, ValueError):
            continue
        parsed.append(
            (created, str(backup.get("path", "")), bool(backup.get("success", False)))
        )

    parsed.sort(key=lambda item: item[0], reverse=True)
    protected = {str(Path(path).resolve()) for path in keep_paths}
    for _created, path, success in parsed:
        if success:
            protected.add(str(Path(path).resolve()))
            break

    keep: set[str] = set()
    seen_days: set[tuple[int, int, int]] = set()
    seen_weeks: set[tuple[int, int]] = set()
    seen_months: set[tuple[int, int]] = set()
    for created, path, _success in parsed:
        day = (created.year, created.month, created.day)
        iso_week = created.isocalendar()
        week = (iso_week.year, iso_week.week)
        month = (created.year, created.month)
        if day not in seen_days and len(seen_days) < daily:
            seen_days.add(day)
            keep.add(path)
        if week not in seen_weeks and len(seen_weeks) < weekly:
            seen_weeks.add(week)
            keep.add(path)
        if month not in seen_months and len(seen_months) < monthly:
            seen_months.add(month)
            keep.add(path)

    return [
        path
        for _created, path, _success in parsed
        if path not in keep and str(Path(path).resolve()) not in protected
    ]


def is_stale(
    latest_success: datetime | str | None, now: datetime, *, hours: float
) -> bool:
    """Return True when no successful backup exists within the staleness window."""
    if latest_success is None:
        return True
    created = parse_timestamp(latest_success)
    return (now - created).total_seconds() > hours * 3600


def validate_restore_target(name: str) -> str:
    """Reject production-looking database names before any restore command runs."""
    if not IDENTIFIER_RE.fullmatch(name):
        raise RestoreSafetyError("target database name is not a safe SQL identifier")
    lowered = name.lower()
    if lowered in {"plane", "postgres"} or lowered.startswith("template"):
        raise RestoreSafetyError(
            "target database name is reserved for production or templates"
        )
    if (
        lowered.startswith("prod")
        or lowered.endswith("_prod")
        or "production" in lowered
    ):
        raise RestoreSafetyError("target database name looks like production")
    return name


def validate_object_target(bucket: str, *, source_bucket: str | None = None) -> str:
    """Require a clearly named staging bucket distinct from the backup source."""
    if not bucket or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", bucket):
        raise RestoreSafetyError("object target bucket name is invalid")
    lowered = bucket.lower()
    if not (lowered.startswith("restore-") or lowered.startswith("staging-")):
        raise RestoreSafetyError(
            "object target bucket must start with restore- or staging-"
        )
    if source_bucket and lowered == source_bucket.lower():
        raise RestoreSafetyError(
            "object target bucket must differ from the backup source bucket"
        )
    return bucket


def parse_path_mapping(value: str) -> tuple[str, str]:
    """Parse a ``CONTAINER_PATH=HOST_PATH`` mapping used by containerised mc."""
    if "=" not in value:
        raise BackupError("path mapping must use CONTAINER_PATH=HOST_PATH")
    container, host = value.split("=", 1)
    if not container or not host:
        raise BackupError("path mapping contains an empty side")
    return container, host


def map_mc_path(path: str | Path, mappings: Sequence[tuple[str, str]]) -> str:
    """Translate an mc-visible path to its host equivalent for checksumming."""
    text = str(path)
    for container, host in sorted(
        mappings, key=lambda item: len(item[0]), reverse=True
    ):
        prefix = container.rstrip("/")
        if text == prefix:
            return host.rstrip("/")
        if text.startswith(prefix + "/"):
            return host.rstrip("/") + text[len(prefix) :]
    return text


def map_host_to_mc_path(path: str | Path, mappings: Sequence[tuple[str, str]]) -> str:
    """Translate a host path back into the path visible to a containerised mc.

    Host paths may arrive from Windows PowerShell with backslash separators while
    the configured mapping uses either separator style. Normalize both sides to
    forward slashes before comparing so containerised ``mc`` always receives a
    path it can see.
    """
    text = str(path)
    normalized_text = text.replace("\\", "/")
    for container, host in sorted(
        mappings, key=lambda item: len(str(item[1])), reverse=True
    ):
        host_prefix = str(host).replace("\\", "/").rstrip("/")
        container_root = str(container).replace("\\", "/").rstrip("/") or "/"
        if not host_prefix:
            continue
        if normalized_text == host_prefix:
            return container_root
        if normalized_text.startswith(host_prefix + "/"):
            return container_root + normalized_text[len(host_prefix) :]
    return text


def acquire_lock(path: Path, owner: str) -> LockHandle:
    """Create an exclusive lock file atomically; raise OverlapError if it exists."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise OverlapError("another backup is already running") from error
    try:
        os.write(fd, f"{owner}\n".encode("utf-8"))
    except OSError:
        with suppress(OSError):
            os.close(fd)
        with suppress(FileNotFoundError):
            lock_path.unlink()
        raise
    return LockHandle(path=lock_path, fd=fd)


def run_command(
    command: Sequence[str],
    *,
    label: str,
    stdin_path: Path | None = None,
    stdout_path: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a subprocess with streams bound to files, never logging command text.

    Command text and stderr are deliberately omitted from errors because they
    may contain credentials supplied by an operator-provided command prefix.
    """
    stdin_handle = None
    stdout_handle = None
    try:
        if stdin_path is not None:
            stdin_handle = Path(stdin_path).open("rb")
        if stdout_path is not None:
            stdout_handle = Path(stdout_path).open("wb")
        completed = subprocess.run(  # noqa: S603 - command prefix is operator supplied and never logged
            list(command),
            stdin=stdin_handle or subprocess.DEVNULL,
            stdout=stdout_handle or subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise CommandError(
            f"{label} could not start: {error.strerror or type(error).__name__}"
        ) from error
    finally:
        if stdin_handle is not None:
            stdin_handle.close()
        if stdout_handle is not None:
            stdout_handle.close()
    if completed.returncode != 0:
        raise CommandError(f"{label} failed with exit code {completed.returncode}")
    return completed
