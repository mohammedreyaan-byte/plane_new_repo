# Backup and restore runbook — go-live day

**Status: TEMPLATE for the live event.** The tooling itself is implemented and
the isolated PLN-025 drill passed; production execution has not been recorded.

## References

- Implemented tooling: `scripts/backup/backup_tool.py`, `restore_tool.py`,
  `verify_backup.py`.
- Full runbook: `../../runbooks/backup-restore.md`.
- Verification queries: `../../runbooks/restore-verify.sql`.
- Prior drill evidence: `.playwright-mcp/pln025-restore-drill-result.json`
  (`VERIFY=PASS`, `RESTORE=OK`, 0 count mismatches, matching object checksums,
  RTO 20s, RPO 0s for that isolated drill).

## Go-live-day backup

| Field                    | Value        |
| ------------------------ | ------------ |
| Backup owner             | Not named    |
| Start time (UTC)         | Not recorded |
| Artifact directory       | Not recorded |
| Manifest checksum        | Not recorded |
| Verify result            | Not recorded |
| Off-server mirror result | Not recorded |

## Steps

|   # | Action                                          | Expected                                    | Actual | Owner |
| --: | ----------------------------------------------- | ------------------------------------------- | ------ | ----- |
|   1 | Run the backup tool for the production database | Backup completes and writes a manifest last |        |       |
|   2 | Verify the manifest with the verify tool        | Checksums/sizes and restore list match      |        |       |
|   3 | Mirror artifacts off-server                     | Object checksums match the manifest         |        |       |
|   4 | Record artifact directory and checksum          | Evidence link stored with the go-live log   |        |       |

## Restore rule

Restore drills use an explicitly named isolated target such as `plane_restore`,
never the production database name. Production restore requires named approval
and the `rollback.md` decision record. `EMAIL_TEST_MODE` stays `false` in
production.

## Limitation

Nightly logical backup RPO is up to 24 hours. A `<=15m` production RPO requires
separately enabled WAL archiving and base backups, which is a named operator
handoff and not configured here.
