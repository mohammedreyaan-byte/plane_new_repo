# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for the PLN-026 seed command guards and password handling."""

import secrets

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from plane.db.management.commands import seed_e2e
from plane.db.models import User, Webhook, Workspace

pytestmark = pytest.mark.unit


def _clear_seed_env(monkeypatch):
    for name in (
        seed_e2e.PASSWORD_ENV,
        seed_e2e.WEBHOOK_SECRET_ENV,
        seed_e2e.SAFETY_OPT_IN_ENV,
        seed_e2e.TARGET_ENV_NAME,
        "PLANE_ENV",
        "DEPLOY_ENV",
        "APP_ENV",
        "ENVIRONMENT",
        "DJANGO_SETTINGS_MODULE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.unit
def test_dry_run_reports_all_expected_counts_without_writes(db, monkeypatch, capsys):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("PLANE_E2E_ENV", "local")
    slug = "e2e-dry-run-unit"

    call_command("seed_e2e", "--workspace", slug, "--project", "E2E", "--dry-run")

    output = capsys.readouterr().out
    assert "Planned E2E seed counts (dry run)" in output
    for key, value in seed_e2e.EXPECTED_COUNTS.items():
        assert f"{key:<18} {value}" in output
    assert not Workspace.objects.filter(slug=slug).exists()
    assert not User.objects.filter(email__endswith=f"@{slug}.example.invalid").exists()


@pytest.mark.unit
@pytest.mark.parametrize("settings_module", ["plane.settings.production", "plane.settings.prod"])
def test_production_target_is_refused_without_explicit_opt_in(db, monkeypatch, settings_module):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", settings_module)

    with pytest.raises(CommandError, match="Refusing to seed a production target"):
        call_command("seed_e2e", "--workspace", "e2e-guard-unit", "--project", "E2E", "--dry-run")


@pytest.mark.unit
@pytest.mark.parametrize("environment", ["production", "prod", "live"])
def test_production_environment_marker_is_refused_without_explicit_opt_in(db, monkeypatch, environment):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("PLANE_E2E_ENV", environment)

    with pytest.raises(CommandError, match="Refusing to seed a production target"):
        call_command("seed_e2e", "--workspace", "e2e-guard-unit", "--project", "E2E", "--dry-run")


@pytest.mark.unit
@pytest.mark.parametrize(
    "opt_in",
    [{"E2E_ALLOW_LOCAL_STAGING": "1"}, {"PLANE_E2E_ENV": "staging"}, {"PLANE_E2E_ENV": "local"}],
)
def test_production_settings_are_refused_even_with_safe_environment_opt_in(db, monkeypatch, opt_in):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "plane.settings.production")
    for name, value in opt_in.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(CommandError, match="active Django settings module is production"):
        call_command("seed_e2e", "--workspace", "e2e-guard-unit", "--project", "E2E", "--dry-run")


@pytest.mark.unit
@pytest.mark.parametrize(
    "opt_in",
    [{"E2E_ALLOW_LOCAL_STAGING": "1"}, {"PLANE_E2E_ENV": "staging"}, {"PLANE_E2E_ENV": "local"}],
)
def test_production_marker_is_refused_even_with_safe_environment_opt_in(db, monkeypatch, opt_in):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "plane.settings.test")
    monkeypatch.setenv("PLANE_ENV", "production")
    for name, value in opt_in.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(CommandError, match="cannot be overridden"):
        call_command("seed_e2e", "--workspace", "e2e-guard-unit", "--project", "E2E", "--dry-run")


@pytest.mark.unit
def test_password_is_read_from_environment_at_runtime_and_never_printed(db, monkeypatch, capsys):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("PLANE_E2E_ENV", "local")
    slug = "e2e-password-unit"
    runtime_password = secrets.token_urlsafe(24)
    monkeypatch.setenv(seed_e2e.PASSWORD_ENV, runtime_password)

    call_command("seed_e2e", "--workspace", slug, "--project", "E2E", "--reset")

    captured = capsys.readouterr()
    output = captured.out
    assert runtime_password not in output
    assert runtime_password not in captured.err
    admin = User.objects.get(email=seed_e2e.Command._email(slug, "admin"))
    assert admin.check_password(runtime_password)
    assert f"{'service_tokens':<18} 0" in output

    workspace = Workspace.objects.get(slug=slug)
    urls = list(Webhook.objects.filter(workspace=workspace).values_list("url", flat=True))
    assert len(urls) == seed_e2e.WEBHOOK_COUNT
    assert all(url.startswith("http://127.0.0.1:8787/receiver/e2e/") for url in urls)


@pytest.mark.unit
def test_missing_password_creates_users_without_usable_password_and_warns(db, monkeypatch, capsys):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("PLANE_E2E_ENV", "local")
    slug = "e2e-no-password-unit"

    call_command("seed_e2e", "--workspace", slug, "--project", "E2E", "--reset")

    output = capsys.readouterr().out
    assert "E2E_TEST_PASSWORD is not set" in output
    assert "UI login scenarios require it" in output
    assert all(
        not user.has_usable_password() for user in User.objects.filter(email__endswith=f"@{slug}.example.invalid")
    )


@pytest.mark.unit
def test_webhook_secret_is_read_from_environment_and_never_printed(db, monkeypatch, capsys):
    _clear_seed_env(monkeypatch)
    monkeypatch.setenv("PLANE_E2E_ENV", "local")
    slug = "e2e-webhook-secret-unit"
    runtime_secret = secrets.token_urlsafe(24)
    monkeypatch.setenv(seed_e2e.WEBHOOK_SECRET_ENV, runtime_secret)

    call_command("seed_e2e", "--workspace", slug, "--project", "E2E", "--reset")

    captured = capsys.readouterr()
    assert runtime_secret not in captured.out
    assert runtime_secret not in captured.err
    workspace = Workspace.objects.get(slug=slug)
    secrets_in_db = set(Webhook.objects.filter(workspace=workspace).values_list("secret_key", flat=True))
    assert secrets_in_db == {runtime_secret}
