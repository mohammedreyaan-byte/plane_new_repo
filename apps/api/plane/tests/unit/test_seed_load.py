# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for PLN-026 load seed guards and dry-run reporting."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from plane.db.management.commands import seed_e2e, seed_load
from plane.db.models import APIToken, Workspace

pytestmark = pytest.mark.unit


def _clear_seed_env(monkeypatch):
    for name in (
        seed_e2e.PASSWORD_ENV,
        seed_e2e.SAFETY_OPT_IN_ENV,
        seed_e2e.TARGET_ENV_NAME,
        seed_load.SAFETY_OPT_IN_ENV,
        seed_load.TARGET_ENV_NAME,
        "PLANE_ENV",
        "DEPLOY_ENV",
        "APP_ENV",
        "ENVIRONMENT",
        "DJANGO_SETTINGS_MODULE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.unit
def test_load_dry_run_reports_all_expected_counts_without_writes(db, monkeypatch, capsys):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("PLANE_LOAD_ENV", "local")
    slug = "load-dry-run-unit"

    call_command("seed_load", "--workspace", slug, "--project", "Load", "--dry-run")

    output = capsys.readouterr().out
    assert "Planned load seed counts (dry run)" in output
    for key, value in seed_load.EXPECTED_COUNTS.items():
        assert f"{key:<18} {value}" in output
    assert not Workspace.objects.filter(slug=slug).exists()
    assert not APIToken.objects.exists()


@pytest.mark.unit
@pytest.mark.parametrize("environment", ["production", "prod", "live"])
def test_load_seed_refuses_production_markers(db, monkeypatch, environment):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("PLANE_LOAD_ENV", environment)

    with pytest.raises(CommandError, match="Refusing to seed a production target"):
        call_command("seed_load", "--workspace", "load-guard-unit", "--project", "Load", "--dry-run")


@pytest.mark.unit
def test_load_seed_refuses_production_settings_even_with_staging_target(db, monkeypatch):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "plane.settings.production")
    monkeypatch.setenv("PLANE_LOAD_ENV", "staging")

    with pytest.raises(CommandError, match="DJANGO_SETTINGS_MODULE looks like production"):
        call_command("seed_load", "--workspace", "load-guard-unit", "--project", "Load", "--dry-run")


@pytest.mark.unit
@pytest.mark.parametrize(
    "opt_in",
    [{"LOAD_ALLOW_LOCAL_STAGING": "1"}, {"PLANE_LOAD_ENV": "staging"}, {"--flag": "--allow-local-staging"}],
)
def test_load_seed_refuses_production_marker_even_with_opt_in(db, monkeypatch, opt_in):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("PLANE_ENV", "production")
    args = ["seed_load", "--workspace", "load-guard-unit", "--project", "Load", "--dry-run"]
    for name, value in opt_in.items():
        if name == "--flag":
            args.append(value)
        else:
            monkeypatch.setenv(name, value)

    with pytest.raises(CommandError, match="cannot be overridden"):
        call_command(*args)


@pytest.mark.unit
def test_load_seed_allows_explicit_staging_target(db, monkeypatch):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("PLANE_LOAD_ENV", "staging")

    call_command("seed_load", "--workspace", "load-guard-unit", "--project", "Load", "--dry-run")
