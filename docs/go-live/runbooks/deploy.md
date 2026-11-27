# Deploy runbook — go-live window

**Status: TEMPLATE.** Fill the approval fields before execution.

## Preconditions

- Readiness gate exits `0`.
- Release digests are approved and recorded by the release owner.
- Final backup is verified (`backup-restore.md`).
- Rollback owner and window are confirmed.

| Field                    | Value        |
| ------------------------ | ------------ |
| Approved release/digests | Not recorded |
| Release owner            | Not named    |
| Change window            | Not recorded |
| Migration version        | Not recorded |
| Health endpoint          | Not recorded |

## Steps

|   # | Action                                                | Expected                             | Actual | Time (UTC) | Owner |
| --: | ----------------------------------------------------- | ------------------------------------ | ------ | ---------- | ----- |
|   1 | Announce window and set maintenance banner            | Users informed                       |        |            |       |
|   2 | Deploy approved images without rebuilding on the host | Services start with approved digests |        |            |       |
|   3 | Run database migrations                               | Migrations complete with no errors   |        |            |       |
|   4 | Verify health of web, api, worker, live and proxy     | All health checks green              |        |            |       |
|   5 | Run the go-live smoke test from `../go-live-plan.md`  | All checks pass                      |        |            |       |
|   6 | Verify roles and real project data                    | All 15 users have expected access    |        |            |       |
|   7 | Remove banner and announce availability               | Users informed with training links   |        |            |       |
|   8 | Monitor for two hours                                 | No rollback trigger hit              |        |            |       |

## Stop conditions

If any rollback trigger in `../go-live-plan.md` occurs, stop and follow
`rollback.md`. Do not continue deploying to "finish" the window.
