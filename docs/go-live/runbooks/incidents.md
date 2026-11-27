# Incident runbook — hypercare and go-live

**Status: TEMPLATE.** No incident has been recorded.

## Intake

- All incidents enter through the single channel in `../support-model.md`.
- Side DMs are redirected to that channel.
- Record the reporter, time, severity and affected users.

| Field          | Value        |
| -------------- | ------------ |
| Incident ID    | Not recorded |
| Reporter       | Not recorded |
| Time (UTC)     | Not recorded |
| Severity       | Not recorded |
| Affected users | Not recorded |

## Response

| Severity | Response         | Actions                                                     |
| -------- | ---------------- | ----------------------------------------------------------- |
| P0       | 1 hour           | Engage technical owner; assess rollback trigger immediately |
| P1       | Same working day | Fix or written workaround approved by business owner        |
| P2       | 3 working days   | Log and schedule after go-live                              |
| P3       | Best effort      | Log only                                                    |

## Communication cadence

| When                | Audience                            | Owner | Actual time | Evidence |
| ------------------- | ----------------------------------- | ----- | ----------- | -------- |
| On detection        | Support channel and technical owner |       |             |          |
| Every 30 min for P0 | Stakeholders                        |       |             |          |
| On resolution       | All users                           |       |             |          |

## Closure

- Link a defect ticket and, when fixed, a reviewed fix commit.
- Record retest result and tester.
- Add a post-incident review entry with owner and date.

## Post-incident review

| Field                | Value        |
| -------------------- | ------------ |
| Review date          | Not recorded |
| Review owner         | Not named    |
| Root cause           | Not recorded |
| Preventive action    | Not recorded |
| Linked defect ticket | Not recorded |
