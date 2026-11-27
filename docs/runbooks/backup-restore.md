# PLN-025 backup and restore drill runbook

Scope: logical Postgres backups plus an object-storage mirror for Plane CE. The
scripts are standard-library-only Python 3.10+ and run on the host or in an
isolated CI job. They never print command prefixes, credentials or stderr from
database/object commands.

## Objectives and targets

- **RPO:** nightly (up to 24 hours) with the logical backup in this runbook.
  **RPO <= 15 minutes is claimed only when PITR is enabled** (WAL archiving plus
  a tested base backup). This tool does not configure PITR.
- **RTO:** <= 4 hours target for a full staging restore and verification.
- **Retention:** 7 daily, 4 weekly, 12 monthly directories. The newest
  successful backup is never pruned.
- **Isolation:** restore targets must be a non-production database such as
  `plane_restore` and a staging bucket beginning with `restore-` or `staging-`.

## Roles and controls

- Two-person rule: an operator runs the job; a second person reviews the
  manifest, verification output and sign-off before any production decision.
- Credentials are supplied by the secret manager or the operator's existing
  `mc` alias / Compose environment. Do not place credentials in this runbook,
  the backup directory, the workflow file or test fixtures.
- Alert hook receives one message argument. Configure it to page the on-call
  channel on `backup-failed` and `stale-backup`.
- Lock file: `<backup-root>/.backup.lock` prevents overlapping backups. Remove
  it manually only after confirming no backup process is running.

## Production backup

Prepare an `mc` alias out-of-band (for example `local`) so the command prefix
`mc` can mirror the configured bucket. The hook contracts are:

- `--encrypt-command <prefix>`: invoked as `<prefix> INPUT OUTPUT`; writes the
  encrypted OUTPUT file. Keys must come from KMS/secret manager, never argv.
- `--config-source <path>`: repeatable path to `plane.env`, proxy configuration,
  TLS/ACME material or a secret-manager export. Each file is copied into the
  artifact, encrypted with `--config-encrypt-command`, and the plaintext copy is
  deleted. Configuration uses a separate hook so keys can have separate custody.
- `--config-encrypt-command <prefix>`: invoked as `<prefix> INPUT OUTPUT` for
  configuration files only. Required whenever `--config-source` is supplied.
- `--alert-command <prefix>`: invoked as `<prefix> "PLN-025 ... message"`.

```bash
export BACKUP_ROOT=/var/backups/plane
mkdir -p "$BACKUP_ROOT"

python3 scripts/backup/backup_tool.py \
  --backup-root "$BACKUP_ROOT" \
  --db-name "${POSTGRES_DB:-plane}" \
  --compose-file docker-compose.yml \
  --db-service plane-db \
  --mc-command "mc" \
  --object-source "local/${AWS_S3_BUCKET_NAME}" \
  --object-destination "$BACKUP_ROOT/{artifact}/objects" \
  --encrypt-command "/usr/local/bin/pln025-encrypt" \
  --config-source /etc/plane/plane.env \
  --config-source /etc/plane/proxy.conf \
  --config-encrypt-command "/usr/local/bin/pln025-encrypt-config" \
  --alert-command "/usr/local/bin/pln025-alert" \
  --staleness-hours 26 \
  --retention-daily 7 \
  --retention-weekly 4 \
  --retention-monthly 12 \
  --correlation-id "$(date -u +%Y%m%dT%H%M%SZ)-nightly"
```

The command prints exactly one stdout line: `ARTIFACT_DIR=<path>`. All progress
and errors go to stderr with the correlation id. A non-zero exit means the
backup failed; in strict mode (the default) partial staging directories are
removed.

If the `mc` command runs inside a container, map its mount back to the host so
checksums can be computed, for example:

```bash
--object-destination "/pln025-backups/{artifact}/objects" \
--mc-path-map "/pln025-backups=$BACKUP_ROOT"
```

## Verify a backup

```bash
python3 scripts/backup/verify_backup.py \
  --backup-dir "$ARTIFACT_DIR" \
  --run-pg-restore \
  --compose-file docker-compose.yml \
  --db-service plane-db
```

`VERIFY=PASS` means every checksum and size matches, the stored
`pg_restore --list` output has objects and matches the manifest, and the live
`pg_restore --list` re-run agrees. Any `VERIFY=FAIL` line is a failed drill.

## Isolated restore drill

Use `docker-compose-test.yml` with a unique project name and the PLN-025
override. The override mounts the scripts and the shared backup directory into
the disposable containers. Never use `docker compose down -v` for this drill.

```bash
PROJECT="pln025-drill-$(date +%s)"
export PLN025_PROJECT_ROOT="$PWD"
export PLN025_BACKUPS_HOST_DIR="$PWD/.pln025-backups"
mkdir -p "$PLN025_BACKUPS_HOST_DIR"

set -a
. apps/api/.env
set +a

COMPOSE=(docker compose
  -f docker-compose-test.yml
  -f scripts/backup/docker-compose-test.pln025.yml
  -p "$PROJECT")

MC_CMD="${COMPOSE[*]} exec -T test-minio mc"

"${COMPOSE[@]}" up -d test-db test-minio

ARTIFACT_DIR=$(python3 scripts/backup/backup_tool.py \
  --backup-root "$PLN025_BACKUPS_HOST_DIR" \
  --db-name "${POSTGRES_DB:-plane}" \
  --compose-file docker-compose-test.yml \
  --compose-file scripts/backup/docker-compose-test.pln025.yml \
  --compose-project "$PROJECT" \
  --db-service test-db \
  --mc-command "$MC_CMD" \
  --object-source "local/${AWS_S3_BUCKET_NAME}" \
  --object-destination "/pln025-backups/{artifact}/objects" \
  --mc-path-map "/pln025-backups=$PLN025_BACKUPS_HOST_DIR" \
  --correlation-id "$PROJECT" | tee verify-backup.log | sed -n 's/^ARTIFACT_DIR=//p')
```

Dry-run first, then restore. The object bucket must be a new staging bucket,
never the source bucket:

```bash
python3 scripts/backup/restore_tool.py \
  --backup-dir "$ARTIFACT_DIR" \
  --target-db plane_restore \
  --confirm --dry-run \
  --compose-file docker-compose-test.yml \
  --compose-file scripts/backup/docker-compose-test.pln025.yml \
  --compose-project "$PROJECT" \
  --db-service test-db \
  --mc-command "$MC_CMD" \
  --object-target-bucket "restore-${PROJECT}" \
  --mc-path-map "/pln025-backups=$PLN025_BACKUPS_HOST_DIR"

python3 scripts/backup/restore_tool.py \
  --backup-dir "$ARTIFACT_DIR" \
  --target-db plane_restore \
  --confirm \
  --compose-file docker-compose-test.yml \
  --compose-file scripts/backup/docker-compose-test.pln025.yml \
  --compose-project "$PROJECT" \
  --db-service test-db \
  --mc-command "$MC_CMD" \
  --object-target-bucket "restore-${PROJECT}" \
  --mc-path-map "/pln025-backups=$PLN025_BACKUPS_HOST_DIR" 2>&1 | tee restore.log
```

If the manifest contains encrypted database/object artifacts, add
`--decrypt-command "<prefix>"` with the contract `<prefix> ENCRYPTED OUTPUT`.
The tool refuses encrypted backups without a decrypt hook.

If the manifest contains configuration artifacts (created with
`--config-source`), specify a staging-only destination and the separate decrypt
hook, or explicitly pass `--skip-config` for a drill that does not exercise
configuration restore:

```bash
python3 scripts/backup/restore_tool.py \
  --backup-dir "$ARTIFACT_DIR" \
  --target-db plane_restore \
  --confirm \
  --compose-file docker-compose-test.yml \
  --compose-file scripts/backup/docker-compose-test.pln025.yml \
  --compose-project "$PROJECT" \
  --db-service test-db \
  --config-destination "$PWD/.pln025-restored-config" \
  --config-decrypt-command "/usr/local/bin/pln025-decrypt-config" \
  --mc-path-map "/pln025-backups=$PLN025_BACKUPS_HOST_DIR"
```

The configuration hook contract is `<prefix> ENCRYPTED OUTPUT`. The destination
must be a staging path, never the live instance directory.

Verify restored data with the included SQL (works on partial fixtures because
every lookup uses `to_regclass`):

```bash
"${COMPOSE[@]}" exec -T test-db \
  psql -U "${POSTGRES_USER:-plane}" -d plane_restore \
  < docs/runbooks/restore-verify.sql 2>&1 | tee restore-verify.log
```

Finish the drill:

```bash
"${COMPOSE[@]}" down --remove-orphans
```

## Object and configuration restore

- Objects are restored with `mc cp --recursive` from the verified manifest's
  `objects/` directory into a staging bucket. Never point
  `--object-target-bucket` at the live bucket.
- Application configuration (environment files, secrets, TLS material) is
  included only when `--config-source` is supplied at backup time. Those files
  are encrypted with the separate config hook; no plaintext configuration is
  written to the artifact directory. Restore them with `--config-destination`
  and `--config-decrypt-command` into a staging-only path, then rotate
  credentials before any deployment use.
- `pg_dump --schema-only` output is included in every artifact for schema
  review; the custom-format dump is the restore source.

## Success criteria

1. `verify_backup.py` reports `VERIFY=PASS` before restore.
2. Restore refuses a dry run with an unsafe target and accepts `plane_restore`.
3. `restore_tool.py` exits 0 and logs the staging database and bucket.
4. `restore-verify.sql` reports non-zero workspace/project/issue counts where
   the source fixture has data, zero orphan rows and zero duplicate rows for
   present tables; missing tables are reported as `SKIPPED`.
5. Object file count from the manifest matches the staging bucket listing.
6. Drill is completed within the 4-hour RTO and signed off by two people.
7. Alert hook was exercised for at least one simulated failure.

## Credential rotation

After any restore drill, rotate the database role password, MinIO root/user
credentials and any API tokens that were present in the restored dataset.
Store new values only in the secret manager; do not commit them or add them to
backup artifacts. Re-run the backup once after rotation to confirm the alert
and object hooks still work.

## Contacts

- Primary DBA / backup owner: `<on-call DBA>`
- Secondary reviewer: `<backup approver>`
- Security/secret-manager owner: `<security on-call>`

## Known limitations

- Queue contents (RabbitMQ) and cache/session state (Redis/Valkey) are not
  captured; messages in flight at backup time are lost.
- In-flight exports and asynchronous jobs may reference objects created after
  the object mirror; they must be regenerated after restore.
- Browser sessions are not restored; users must sign in again.
- Object mirroring is additive (`mc mirror --overwrite`); objects deleted from
  the live bucket after a mirror remain in that backup.
- Logical backups do not provide PITR. Enable WAL archiving separately for the
  15-minute RPO target.
- The alert/encryption hooks are operator-supplied; the scripts validate exit
  status only and never inspect hook arguments or secrets.
