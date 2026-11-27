# Data migration and reconciliation — PLN-027

**Status: NOT EXECUTED.** No production import, workspace creation, user import
or SDLC project seeding was performed for PLN-027. All counts below are blank by
design.

## Source and target

| Item                   | Value        |
| ---------------------- | ------------ |
| Source system / export | Not supplied |
| Target environment     | Not supplied |
| Target workspace       | Not supplied |
| Target SDLC project    | Not supplied |
| Migration owner        | Not named    |
| Migration date         | Not recorded |

## Import counts

| Object                | Expected | Imported | Reconciled | Evidence |
| --------------------- | -------: | -------: | ---------- | -------- |
| Workspace             |          |          |            |          |
| Users                 |          |          |            |          |
| Projects              |          |          |            |          |
| Work-item types       |          |          |            |          |
| Workflows and states  |          |          |            |          |
| Labels                |          |          |            |          |
| Cycles                |          |          |            |          |
| Modules               |          |          |            |          |
| Views                 |          |          |            |          |
| Work items            |          |          |            |          |
| Comments              |          |          |            |          |
| Attachments           |          |          |            |          |
| Integrations / tokens |          |          |            |          |

## Reconciliation method

1. Export source counts with a named owner and date.
2. Export target counts from the staging or production instance after import.
3. Compare per object type; record mismatches and their disposition.
4. Attach both exports as evidence and link them from `uat-summary.md`.
5. Verify role assignments for all 15 users before UAT-01 starts.

## Rollback of a migration

If the migration is damaged and cannot be corrected forward within 30 minutes,
follow `runbooks/rollback.md` and the PLN-025 restore runbook. Restore into an
isolated target first; do not overwrite production without named approval.
