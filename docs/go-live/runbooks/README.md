# Go-live runbooks — PLN-027

These runbooks are written for named operators to execute during the change
window. No operator has been named and no runbook has been executed here.

| Runbook                    | Use                                                                      |
| -------------------------- | ------------------------------------------------------------------------ |
| `production-deployment.md` | Exact production Compose command, operator inputs and post-deploy checks |
| `deploy.md`                | Deploy approved digests, run migrations, verify health                   |
| `rollback.md`              | Trigger assessment and controlled rollback                               |
| `backup-restore.md`        | Pre-go-live backup, verification and isolated restore                    |
| `incidents.md`             | Incident intake, communication and post-incident review                  |

Existing deeper references:

- `../../runbooks/backup-restore.md` — PLN-025 backup/restore runbook
- `../../runbooks/restore-verify.sql` — restore verification queries
- `scripts/backup/` — backup, restore and verify tooling

## Safety rules

- Never run `docker compose down -v`; use `down --remove-orphans`.
- Never change production `docker-compose.yml` during the window.
- Application code changes are limited to approved P0 fixes with reviewed PRs
  and a retest.
- Secret values are supplied by the operator's secret store and never recorded
  in this package.
- Keep `EMAIL_TEST_MODE=false` in production.
