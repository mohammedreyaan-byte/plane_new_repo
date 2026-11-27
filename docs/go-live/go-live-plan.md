# Go-live plan — PLN-027

No change window has been supplied. All times, owners and dates are fields for
the release owner to complete. Do not start until the readiness gate exits `0`.

## Preconditions

- Gate: `python plane-ce-project/scripts/go-live/readiness_gate.py` exits `0`.
- Business and technical sign-off recorded in `uat-summary.md`.
- Rollback owner, window and criteria confirmed in writing.

## T-14 days

| Task                                                         | Owner | Date | Evidence | Done |
| ------------------------------------------------------------ | ----- | ---- | -------- | ---- |
| Freeze scope; only P0/P1 fixes allowed                       |       |      |          |      |
| Confirm production sizing and monitoring                     |       |      |          |      |
| Final restore drill from the latest production-shaped backup |       |      |          |      |
| Communicate cutover date, downtime and user changes          |       |      |          |      |

## T-7 days

| Task                                                                      | Owner | Date | Evidence | Done |
| ------------------------------------------------------------------------- | ----- | ---- | -------- | ---- |
| Deploy release candidate to a production empty/pilot project              |       |      |          |      |
| Run production smoke test                                                 |       |      |          |      |
| Create/verify workspace, 15 users and SDLC project; verify roles          |       |      |          |      |
| Configure SMTP, GitHub, Slack, types, workflows, states, labels and views |       |      |          |      |
| Run full email test with real mailboxes                                   |       |      |          |      |
| Confirm backups run and are verified                                      |       |      |          |      |
| Train the admins                                                          |       |      |          |      |

## T-1 day

| Task                                                  | Owner | Date | Evidence | Done |
| ----------------------------------------------------- | ----- | ---- | -------- | ---- |
| Final backup and checksum                             |       |      |          |      |
| Freeze configuration changes                          |       |      |          |      |
| Confirm rollback owner, window and criteria           |       |      |          |      |
| Send go-live notice with schedule and support channel |       |      |          |      |

## Go-live day

| Step | Action                                                                                          | Owner | Actual time | Result |
| ---: | ----------------------------------------------------------------------------------------------- | ----- | ----------- | ------ |
|    1 | Set maintenance banner or announce window                                                       |       |             |        |
|    2 | Deploy approved digests, run migrations, verify health                                          |       |             |        |
|    3 | Smoke test: login, project, create/transition/delete item, board, cycle, report, email, webhook |       |             |        |
|    4 | Seed/verify real project data and members                                                       |       |             |        |
|    5 | Remove banner; announce availability with training links                                        |       |             |        |
|    6 | Monitor 2 hours: errors, latency, queue depth, mail failures                                    |       |             |        |

## Rollback triggers (any one)

- Login or core work-item operations unavailable for 15 minutes.
- Data loss or corruption detected.
- Isolation breach.
- Migration failure not corrected forward within 30 minutes.

Rollback steps are in `runbooks/rollback.md`. A rollback is a recorded event in
`go-live-log.md`, never an implicit action.
