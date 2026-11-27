# PLN-027 readiness checklist

Authoritative machine-readable source: `readiness-manifest.json`. This table is
the human view of the same 41 criteria. Blank owner/date cells are intentional:
no human owner has been named or has recorded a result in this environment.

"Evidence verified" means an automated check read a completed artifact from an
earlier ticket. It does **not** mean staging or production readiness.

| ID                   | Category      | Criterion                                                   | Owner                    | Date       | Status            | Evidence                           |
| -------------------- | ------------- | ----------------------------------------------------------- | ------------------------ | ---------- | ----------------- | ---------------------------------- |
| ENTRY-01             | Entry         | All P0 prompts merged and deployed to staging from the fork |                          |            | Pending           | None recorded                      |
| ENTRY-02A            | Entry         | PLN-026 local suites green, thresholds unchanged            | automated evidence check | 2026-11-27 | Evidence verified | `pln026-e2e-load-result.json`      |
| ENTRY-02B            | Entry         | Live authenticated staging E2E and k6 load runs green       |                          |            | Pending           | None recorded                      |
| ENTRY-03             | Entry         | PLN-021/015 isolation security suite green                  | automated evidence check | 2026-11-27 | Evidence verified | `issue-pln015-backend-result.json` |
| ENTRY-04             | Entry         | PLN-017 real mailbox matrix complete on two providers       |                          |            | Pending           | None recorded                      |
| ENTRY-05             | Entry         | PLN-025 restore drill succeeded at least once               | automated evidence check | 2026-11-27 | Evidence verified | `pln025-restore-drill-result.json` |
| ENTRY-06             | Entry         | Staging matches production images and configuration         |                          |            | Pending           | None recorded                      |
| ENTRY-07             | Entry         | No open P0/P1; P2 accepted in writing                       |                          |            | Pending           | None recorded                      |
| ENTRY-08             | Entry         | UAT users, roles and test data exist on staging             |                          |            | Pending           | None recorded                      |
| ENTRY-09             | Entry         | UAT coordinator and business owner named                    |                          |            | Pending           | None recorded                      |
| EVID-PLN017          | Evidence      | PLN-017 mailer backend tests green                          | automated evidence check | 2026-11-27 | Evidence verified | `issue-pln017-backend-result.json` |
| EVID-STACK           | Evidence      | App stack restored intact under `plane-ce-project`          | automated evidence check | 2026-11-27 | Evidence verified | `pln026-e2e-load-result.json`      |
| EVID-SHEET           | Evidence      | Only `H26`/`H27` changed in the Google Sheet                | automated evidence check | 2026-11-27 | Evidence verified | before/after proof files           |
| UAT-01               | UAT           | Workspace and project access                                |                          |            | Pending           | `uat/UAT-01.md` (script only)      |
| UAT-02               | UAT           | Create and classify work                                    |                          |            | Pending           | `uat/UAT-02.md` (script only)      |
| UAT-03               | UAT           | Bug workflow                                                |                          |            | Pending           | `uat/UAT-03.md` (script only)      |
| UAT-04               | UAT           | Task, Story and Epic workflows                              |                          |            | Pending           | `uat/UAT-04.md` (script only)      |
| UAT-05               | UAT           | Backlog and sprint                                          |                          |            | Pending           | `uat/UAT-05.md` (script only)      |
| UAT-06               | UAT           | Board and filters                                           |                          |            | Pending           | `uat/UAT-06.md` (script only)      |
| UAT-07               | UAT           | Modules and Epic linkage                                    |                          |            | Pending           | `uat/UAT-07.md` (script only)      |
| UAT-08               | UAT           | Reporting                                                   |                          |            | Pending           | `uat/UAT-08.md` (script only)      |
| UAT-09               | UAT           | Notifications and email                                     |                          |            | Pending           | `uat/UAT-09.md` (script only)      |
| UAT-10               | UAT           | GitHub and Slack                                            |                          |            | Pending           | `uat/UAT-10.md` (script only)      |
| UAT-11               | UAT           | CI and service tokens                                       |                          |            | Pending           | `uat/UAT-11.md` (script only)      |
| UAT-12               | UAT           | Security and isolation                                      |                          |            | Pending           | `uat/UAT-12.md` (script only)      |
| SIGNOFF-BUSINESS     | Sign-off      | Business owner signed UAT summary with P2/P3 list           |                          |            | Pending           | None recorded                      |
| SIGNOFF-TECHNICAL    | Sign-off      | Technical owner signed deployed/retested fixes              |                          |            | Pending           | None recorded                      |
| TRAIN-01             | Training      | All-users session delivered and recorded                    |                          |            | Pending           | None recorded                      |
| TRAIN-02             | Training      | Developers session delivered and recorded                   |                          |            | Pending           | None recorded                      |
| TRAIN-03             | Training      | QA session delivered and recorded                           |                          |            | Pending           | None recorded                      |
| TRAIN-04             | Training      | Project admins session delivered and recorded               |                          |            | Pending           | None recorded                      |
| TRAIN-05             | Training      | Workspace admins session delivered and recorded             |                          |            | Pending           | None recorded                      |
| TRAIN-MATERIALS      | Training      | Quick references, FAQ, who-to-ask and recordings published  |                          |            | Pending           | None recorded                      |
| GO-LIVE-PROD-SMOKE   | Go-live       | Production configured and smoke-tested                      |                          |            | Pending           | None recorded                      |
| GO-LIVE-BACKUPS      | Go-live       | Final backup taken and verified on the day                  |                          |            | Pending           | None recorded                      |
| GO-LIVE-EXECUTED     | Go-live       | Go-live executed with monitoring or clean rollback          |                          |            | Pending           | None recorded                      |
| HYPERCARE-STARTED    | Hypercare     | Support model published and daily metrics captured          |                          |            | Pending           | None recorded                      |
| DOC-PACKAGE-REVIEWED | Documentation | Package complete and reviewed                               |                          |            | Pending           | None recorded                      |
| EVIDENCE-ATTACHED    | Documentation | Tracker, sign-off, attendance, log and metrics attached     |                          |            | Pending           | None recorded                      |
| HANDOVER-SECRETS     | Handover      | Secrets/backups/monitoring/on-call ownership handed over    |                          |            | Pending           | None recorded                      |
| HANDOVER-SANDBOX     | Handover      | Sandbox and test accounts disabled after hypercare          |                          |            | Pending           | None recorded                      |

## Gate result at package creation

```text
total 41, passed 6, blocking failures 35, ready = False
```
