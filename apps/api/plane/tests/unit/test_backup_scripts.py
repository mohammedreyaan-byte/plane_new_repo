# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for the dependency-free PLN-025 backup and restore scripts."""

from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _scripts_dir() -> Path:
    configured = os.environ.get("PLN025_SCRIPTS_DIR")
    if configured:
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / "backup" / "backup_common.py"
        if candidate.is_file():
            return parent / "scripts" / "backup"
    raise FileNotFoundError("Could not locate scripts/backup/backup_common.py from this test file")


def _load_module(name: str, filename: str):
    scripts_dir = _scripts_dir()
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(name, scripts_dir / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = _load_module("backup_common", "backup_common.py")
backup = _load_module("backup_tool", "backup_tool.py")
verify = _load_module("verify_backup", "verify_backup.py")
restore = _load_module("restore_tool", "restore_tool.py")


RESTORE_LIST = b";\n;\n1; TABLE public public workspace public.workspace\n"


class RecordingRunner:
    """Records command labels/arguments and writes deterministic dump output."""

    def __init__(
        self, *, fail_label: str | None = None, disk_full_label: str | None = None
    ) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.fail_label = fail_label
        self.disk_full_label = disk_full_label

    def __call__(self, command, *, label, stdin_path=None, stdout_path=None):
        self.calls.append((label, list(command)))
        if label == self.fail_label:
            raise common.CommandError(f"{label} failed")
        if label == self.disk_full_label:
            raise OSError(28, "No space left on device")
        if label in {"config-encrypt", "config-decrypt"}:
            output_path = Path(command[-1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"encrypted-config")
        if stdout_path is not None:
            output = RESTORE_LIST if label == "pg_restore-list" else b"payload\n"
            Path(stdout_path).write_bytes(output)
        if label == "object-mirror":
            destination = Path(command[-1])
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "asset.txt").write_text("object payload", encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0, b"", b"")

    @property
    def labels(self) -> list[str]:
        return [label for label, _command in self.calls]


def _settings(tmp_path: Path, **overrides) -> backup.BackupSettings:
    root = tmp_path / "backups"
    root.mkdir(exist_ok=True)
    values = {
        "backup_root": root,
        "db_name": "plane",
        "compose": common.ComposeConfig(
            compose_project="pln025-tests",
            compose_files=("docker-compose-test.yml",),
            db_service="test-db",
        ),
        "correlation_id": "unit-correlation",
    }
    values.update(overrides)
    return backup.BackupSettings(**values)


def _artifact_dirs(root: Path) -> list[Path]:
    return [path.parent for path in root.glob("*/manifest.json")]


def test_backup_success_creates_verifiable_manifest(tmp_path):
    settings = _settings(
        tmp_path,
        mc_command="mc",
        object_source="local/uploads",
        object_destination_template=str(
            settings_root(tmp_path) / "{artifact}" / "objects"
        ),
    )
    runner = RecordingRunner()

    result = backup.run_backup(settings, runner=runner)

    assert result["success"] is True
    artifact_dir = Path(result["artifact_dir"])
    assert artifact_dir.is_dir()
    assert verify.verify_manifest(artifact_dir / "manifest.json") == []
    for label in ("pg_dump", "pg_dump-schema", "pg_restore-list", "object-mirror"):
        assert label in runner.labels
    assert (artifact_dir / "objects" / "asset.txt").is_file()


def settings_root(tmp_path: Path) -> Path:
    return tmp_path / "backups"


def test_config_backup_uses_separate_encryption(tmp_path):
    source = tmp_path / "plane.env"
    source.write_text("placeholder-configuration", encoding="utf-8")
    settings = _settings(
        tmp_path,
        config_sources=(source,),
        config_encrypt_command="config-encrypt-hook",
    )
    runner = RecordingRunner()

    result = backup.run_backup(settings, runner=runner)

    assert result["success"] is True
    artifact_dir = Path(result["artifact_dir"])
    manifest = common.load_manifest(artifact_dir / "manifest.json")
    config_artifacts = [
        entry for entry in manifest["artifacts"] if entry["kind"] == "config"
    ]
    assert len(config_artifacts) == 1
    assert config_artifacts[0]["encrypted"] is True
    assert config_artifacts[0]["source_name"] == "plane.env"
    assert runner.labels.count("config-encrypt") == 1
    assert (artifact_dir / "config" / "00-plane-env.enc").is_file()
    assert not (artifact_dir / "config" / "00-plane-env").exists()
    assert verify.verify_manifest(artifact_dir / "manifest.json") == []


def test_config_backup_refuses_without_separate_hook(tmp_path):
    source = tmp_path / "plane.env"
    source.write_text("placeholder-configuration", encoding="utf-8")
    settings = _settings(tmp_path, config_sources=(source,))

    with pytest.raises(common.BackupError):
        backup.run_backup(settings, runner=RecordingRunner())


def test_restore_requires_explicit_config_handling(tmp_path):
    source = tmp_path / "plane.env"
    source.write_text("placeholder-configuration", encoding="utf-8")
    artifact = Path(
        backup.run_backup(
            _settings(
                tmp_path,
                config_sources=(source,),
                config_encrypt_command="config-encrypt-hook",
            ),
            runner=RecordingRunner(),
        )["artifact_dir"]
    )
    manifest = common.load_manifest(artifact / "manifest.json")

    settings = restore.RestoreSettings(
        backup_dir=artifact,
        target_db="plane_restore",
        compose=common.ComposeConfig(),
        confirm=True,
        dry_run=True,
        correlation_id="unit",
    )
    with pytest.raises(common.RestoreSafetyError):
        restore.prepare_restore(
            settings, runner=RecordingRunner(), logger=logging.getLogger("test")
        )

    restore.validate_config_restore(
        restore.RestoreSettings(**{**settings.__dict__, "skip_config": True}),
        manifest,
    )


def test_config_restore_decrypts_to_staging_destination(tmp_path):
    source = tmp_path / "plane.env"
    source.write_text("placeholder-configuration", encoding="utf-8")
    artifact = Path(
        backup.run_backup(
            _settings(
                tmp_path,
                config_sources=(source,),
                config_encrypt_command="config-encrypt-hook",
            ),
            runner=RecordingRunner(),
        )["artifact_dir"]
    )
    manifest = common.load_manifest(artifact / "manifest.json")
    destination = tmp_path / "restored-config"
    runner = RecordingRunner()
    settings = restore.RestoreSettings(
        backup_dir=artifact,
        target_db="plane_restore",
        compose=common.ComposeConfig(),
        confirm=True,
        dry_run=False,
        correlation_id="unit",
        config_destination=destination,
        config_decrypt_command="config-decrypt-hook",
    )

    restored = restore.restore_config_artifacts(
        settings, manifest, runner=runner, logger=logging.getLogger("test")
    )

    assert restored == 1
    assert runner.labels.count("config-decrypt") == 1
    assert (destination / "plane.env").read_bytes() == b"encrypted-config"


def test_upload_mirror_failure_is_fatal_and_cleans_up(tmp_path):
    settings = _settings(
        tmp_path,
        mc_command="mc",
        object_source="local/uploads",
        object_destination_template=str(
            settings_root(tmp_path) / "{artifact}" / "objects"
        ),
    )
    runner = RecordingRunner(fail_label="object-mirror")

    with pytest.raises(common.CommandError):
        backup.run_backup(settings, runner=runner)

    assert _artifact_dirs(settings.backup_root) == []
    assert list(settings.backup_root.glob(".pln025-*")) == []


def test_main_returns_nonzero_and_alerts_on_failure(tmp_path, monkeypatch):
    def explode(*_args, **_kwargs):
        raise common.CommandError("pg_dump failed")

    alerts = []
    monkeypatch.setattr(backup, "run_backup", explode)
    monkeypatch.setattr(
        backup, "send_alert", lambda settings, reason, **_kwargs: alerts.append(reason)
    )

    exit_code = backup.main(
        ["--backup-root", str(tmp_path / "backups"), "--alert-command", "alert-hook"]
    )

    assert exit_code == 1
    assert alerts == ["backup-failed"]


def test_stale_backup_triggers_alert(tmp_path, monkeypatch):
    settings = _settings(tmp_path, alert_command="alert-hook", staleness_hours=1)
    reasons = []
    monkeypatch.setattr(
        backup,
        "send_alert",
        lambda _settings, reason, **_kwargs: reasons.append(reason),
    )

    backup.warn_if_stale(
        settings,
        datetime(2026, 11, 28, tzinfo=timezone.utc),
        runner=RecordingRunner(),
        logger=logging.getLogger("test"),
    )

    assert reasons == ["stale-backup"]


def test_disk_full_simulation_fails_backup(tmp_path):
    settings = _settings(tmp_path)
    runner = RecordingRunner(disk_full_label="pg_dump")

    with pytest.raises(OSError):
        backup.run_backup(settings, runner=runner)

    assert _artifact_dirs(settings.backup_root) == []


def test_overlapping_lock_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    lock_path = settings.backup_root / ".backup.lock"
    with common.acquire_lock(lock_path, "first-run"):
        with pytest.raises(common.OverlapError):
            common.acquire_lock(lock_path, "second-run")

    with common.acquire_lock(lock_path, "first-run"):
        with pytest.raises(common.OverlapError):
            backup.run_backup(settings, runner=RecordingRunner())
        assert lock_path.is_file()


def test_retention_never_deletes_last_successful_backup():
    now = datetime(2026, 11, 27, tzinfo=timezone.utc)
    backups = []
    for days_ago in range(10):
        created = now - timedelta(days=days_ago)
        backups.append(
            {
                "path": f"/backups/{days_ago:02d}",
                "created_at": created.isoformat().replace("+00:00", "Z"),
                "success": days_ago == 9,
            }
        )

    candidates = common.select_prune_candidates(
        backups, now, daily=2, weekly=1, monthly=1, keep_paths=["/backups/00"]
    )

    assert "/backups/09" not in candidates
    assert "/backups/00" not in candidates
    assert "/backups/05" in candidates


def test_manifest_tamper_is_detected(tmp_path):
    artifacts_dir = tmp_path / "artifact"
    artifacts_dir.mkdir()
    dump_path = artifacts_dir / "db.dump"
    original = b"valid custom dump bytes"
    dump_path.write_bytes(original)
    restore_list = artifacts_dir / "restore-list.txt"
    restore_list.write_bytes(b"1; TABLE public public workspaces\n")
    entries = [
        common.make_manifest_entry(dump_path, artifacts_dir, "db_dump"),
        common.make_manifest_entry(restore_list, artifacts_dir, "restore_list"),
    ]
    manifest = common.build_manifest(
        correlation_id="cid",
        created_at=datetime(2026, 11, 27, tzinfo=timezone.utc),
        database="plane",
        artifacts=entries,
        dump_list=["1; TABLE public public workspaces"],
    )
    common.write_manifest(artifacts_dir / "manifest.json", manifest)
    assert verify.verify_manifest(artifacts_dir / "manifest.json") == []

    dump_path.write_bytes(original + b"tampered")
    errors = verify.verify_manifest(artifacts_dir / "manifest.json")

    assert any("checksum mismatch" in error for error in errors)


@pytest.mark.parametrize(
    "target", ["plane", "postgres", "template1", "TEMPLATE_custom", "prod_plane"]
)
def test_restore_guard_refuses_production_database_names(target):
    with pytest.raises(common.RestoreSafetyError):
        restore.validate_restore_target(target)


def test_restore_guard_allows_explicit_staging_database_name():
    assert restore.validate_restore_target("plane_restore") == "plane_restore"


def test_command_construction_is_exact_and_contains_no_shell_prefix():
    config = common.ComposeConfig(
        compose_project="pln025-drill",
        compose_files=(
            "docker-compose-test.yml",
            "scripts/backup/docker-compose-test.pln025.yml",
        ),
        db_service="test-db",
    )

    assert common.build_pg_dump_command(config, "plane") == [
        "docker",
        "compose",
        "-f",
        "docker-compose-test.yml",
        "-f",
        "scripts/backup/docker-compose-test.pln025.yml",
        "-p",
        "pln025-drill",
        "exec",
        "-T",
        "test-db",
        "pg_dump",
        "-Fc",
        "--no-owner",
        "--no-privileges",
        "--username",
        "plane",
        "--dbname",
        "plane",
    ]
    assert "--schema-only" in common.build_pg_dump_command(
        config, "plane", schema_only=True
    )
    assert common.build_pg_restore_list_command(config)[-4:] == [
        "pg_restore",
        "--list",
        "--username",
        "plane",
    ]
    assert common.build_mc_mirror_command(
        "mc", "local/uploads", "/backups/a/objects"
    ) == [
        "mc",
        "mirror",
        "--overwrite",
        "local/uploads",
        "/backups/a/objects",
    ]
    assert common.build_mc_copy_command(
        "mc --no-color", "/backups/a/objects/.", "local/restore-1"
    ) == [
        "mc",
        "--no-color",
        "cp",
        "--recursive",
        "/backups/a/objects/",
        "local/restore-1",
    ]
    assert common.build_createdb_command(config, "plane_restore")[-4:] == [
        "createdb",
        "--username",
        "plane",
        "plane_restore",
    ]
    assert common.build_dropdb_command(config, "plane_restore")[-5:] == [
        "dropdb",
        "--if-exists",
        "--username",
        "plane",
        "plane_restore",
    ]
    assert common.build_pg_restore_command(config, "plane_restore")[-4:] == [
        "--username",
        "plane",
        "--dbname",
        "plane_restore",
    ]


def test_object_path_mapping_supports_containerised_mc():
    mappings = (("/pln025-backups", "/tmp/host-backups"),)
    assert (
        common.map_mc_path("/pln025-backups/staging/objects", mappings)
        == "/tmp/host-backups/staging/objects"
    )
    assert common.map_host_to_mc_path(
        "/tmp/host-backups/staging/objects", mappings
    ) == ("/pln025-backups/staging/objects")


def test_object_path_mapping_accepts_windows_host_paths():
    mappings = (("/pln025-backups", r"C:\host\backups"),)
    assert common.map_host_to_mc_path(
        r"C:\host\backups\staging\objects", mappings
    ) == "/pln025-backups/staging/objects"
