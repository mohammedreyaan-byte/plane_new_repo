# Rollback runbook — go-live window

**Status: TEMPLATE.** A rollback is a recorded decision, not an implicit action.

## Triggers (any one)

- Login or core work-item operations unavailable for 15 minutes.
- Data loss or corruption detected.
- Isolation breach.
- Migration failure not correctable forward within 30 minutes.

## Decision record

| Field                     | Value        |
| ------------------------- | ------------ |
| Trigger observed          | Not recorded |
| Time (UTC)                | Not recorded |
| Decision by               | Not named    |
| Business acknowledgement  | Not recorded |
| Rollback target digests   | Not recorded |
| Database restore required | Not recorded |

## Steps

|   # | Action                                             | Expected                                                          | Actual | Time (UTC) | Owner |
| --: | -------------------------------------------------- | ----------------------------------------------------------------- | ------ | ---------- | ----- |
|   1 | Announce rollback on the support channel           | Stakeholders informed                                             |        |            |       |
|   2 | Redeploy the previously approved digests           | Previous version is healthy                                       |        |            |       |
|   3 | Restore database only if migration/data is damaged | Restore follows the PLN-025 runbook into an isolated target first |        |            |       |
|   4 | Verify login, project, workflow and email          | Core functions pass                                               |        |            |       |
|   5 | Communicate status and new availability            | Users informed                                                    |        |            |       |
|   6 | Schedule post-incident review                      | Review owner and date recorded                                    |        |            |       |

## Constraints

- Do not restore production directly without named approval.
- Do not delete volumes; `down -v` is prohibited.
- Link the incident to a defect ticket and record the fix commit after review.
