# Production deployment runbook — Plane CE

**Status: deployment mechanics ready; execution NOT authorized.**
The readiness gate must exit `0` and a named release owner must approve the
change window before this runbook is executed. This document contains no
credentials, secrets, provider values, image digests or dates.

## 1. Files used

Only these Compose files are valid for production:

| File                                     | Purpose                                                                                                   |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `docker-compose.yml`                     | Base services. Must be unchanged from the approved commit.                                                |
| `docker-compose.production.override.yml` | Fail-closed production overrides. Requires operator-supplied `SITE_ADDRESS` and `LIVE_SERVER_SECRET_KEY`. |

**Never use** `docker-compose.demo.override.yml` or
`docker-compose.dev.override.yml` in production. The demo override contains a
placeholder `LIVE_SERVER_SECRET_KEY`; the dev override contains local-only
ports, a local MinIO image substitution and a bind-mounted Caddyfile.

## 2. Operator-supplied inputs (names only — no values recorded here)

| Input                              | Where it is supplied                                                            | Requirement                                                                                                                                                                                                                                |
| ---------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SITE_ADDRESS`                     | Operator environment or secret store                                            | Real production site address; not `:80` and not blank.                                                                                                                                                                                     |
| `LIVE_SERVER_SECRET_KEY`           | Operator environment or secret store                                            | Unique production value; not the demo placeholder.                                                                                                                                                                                         |
| root `.env`                        | Secret store / deployment environment, written to the host only by the operator | `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PASSWORD`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `RABBITMQ_VHOST`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `LISTEN_HTTP_PORT`, `LISTEN_HTTPS_PORT`, plus TLS/Caddy settings as applicable. |
| `apps/api/.env`                    | Secret store / deployment environment, written to the host only by the operator | Application `SECRET_KEY`, database/cache/queue/storage settings, SMTP settings and all provider configuration.                                                                                                                             |
| Image digests or tags              | Approved release record                                                         | Immutable, reviewed and recorded by the release owner.                                                                                                                                                                                     |
| `EMAIL_TEST_MODE`                  | `apps/api/.env`                                                                 | Must be `false` in production.                                                                                                                                                                                                             |
| `EMAIL_TEST_MODE_ALLOW_REAL_RELAY` | `apps/api/.env`                                                                 | `false` unless a separately approved test is in progress.                                                                                                                                                                                  |

Do not paste any of these values into chat, tickets, source files, notes,
screenshots, Excel or this package. Do not commit `.env` files.

## 3. Preflight (run on the production host)

From the repository root, with the operator environment already loaded:

```bash
python scripts/go-live/production_preflight.py
docker compose -p plane-ce-project \
  -f docker-compose.yml \
  -f docker-compose.production.override.yml \
  config --quiet
```

Both commands must exit `0`. `config --quiet` validates interpolation without
printing resolved values. If either fails, stop; do not "fix" production by
switching to a demo/dev override or by building on the host.

Additional mandatory checks before proceeding:

- Readiness gate exits `0` (`python scripts/go-live/readiness_gate.py`).
- Final verified backup and checksum exist (`backup-restore.md`).
- Approved image digests are recorded; the `<=15m` RPO decision (WAL
  archiving/base backups) is recorded as implemented or formally accepted.
- Rollback owner, change window and monitoring endpoints are recorded.

## 4. Deploy

Use pre-built approved images. Never rebuild on the production host.

```bash
docker compose -p plane-ce-project \
  -f docker-compose.yml \
  -f docker-compose.production.override.yml \
  up -d --no-build
```

Migrations are run by the existing `migrator` service entrypoint as part of the
stack start. Confirm completion in its logs before continuing.

## 5. Post-deploy verification

|   # | Check                                                                                                   | Expected                                       | Actual | Time (UTC) | Owner |
| --: | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ------ | ---------- | ----- |
|   1 | `docker compose -p plane-ce-project -f docker-compose.yml -f docker-compose.production.override.yml ps` | All services Up; none Restarting               |        |            |       |
|   2 | `docker compose ... logs migrator`                                                                      | Migrations completed without errors            |        |            |       |
|   3 | `curl -fsS http://<site>/`                                                                              | HTTP `200`, English UI                         |        |            |       |
|   4 | `curl -fsS http://<site>/god-mode/`                                                                     | HTTP `200` for an authorized operator          |        |            |       |
|   5 | API health/authenticated smoke from `../../docs/go-live/go-live-plan.md`                                | All checks pass                                |        |            |       |
|   6 | `EMAIL_TEST_MODE` from the operator environment (do not print values)                                   | `false`                                        |        |            |       |
|   7 | Confirm no demo/dev override is active                                                                  | Only the two approved files are in the command |        |            |       |
|   8 | Monitor for the agreed hypercare window                                                                 | No rollback trigger hit                        |        |            |       |

Replace `<site>` with the approved production address supplied by the operator.
Record observations only; leave fields blank until actually executed.

## 6. Stop and rollback

If any rollback trigger in `../go-live-plan.md` occurs, stop and follow
`rollback.md`. Do not continue deploying to "finish" the window.

Never run `docker compose down -v`. Use `down --remove-orphans` when a stack
must be stopped. Never modify production `docker-compose.yml` during the
window. Only reviewed P0 fixes with a retest may change application code.
