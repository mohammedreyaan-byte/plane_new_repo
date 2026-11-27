# Known limitations — PLN-027

## Accepted P2/P3 items

No P2 or P3 item has been accepted in writing by a business owner. The table is
blank by design and must not be filled from assumption.

| Defect ID | Severity | Impact | Workaround | Accepted by | Date |
| --------- | -------- | ------ | ---------- | ----------- | ---- |
|           |          |        |            |             |      |

## Environment-dependent limitations carried forward

These are **not** accepted business defects. They are handoffs that could not be
executed in a code-only environment and still require named owners and evidence.

| Area                      | Limitation                                                                                                | Evidence/status                                                                             | Owner required            |
| ------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------- |
| Email delivery            | Real relay, Gmail and Microsoft 365 mailbox matrix, SPF/DKIM/DMARC verification                           | Code/config UI and safe disabled paths verified; real delivery not recorded                 | Mail/workspace admin      |
| Provider integrations     | GitHub, GitLab and Slack success paths                                                                    | Backend plumbing and UI verified; no provider credentials or configured channels            | Integration owner         |
| Load testing              | Live k6 thresholds, staging URL, Prometheus/Grafana and slow-query evidence                               | k6 not installed; verifier, mutation check and mock endpoints passed unchanged              | Performance owner         |
| Restore RPO               | Nightly logical backup RPO is up to 24 hours; `<=15m` needs separately enabled WAL archiving/base backups | Isolated drill passed with measured RPO `0s` for that drill; production PITR not configured | Backup owner              |
| Configuration enforcement | Branch protection, bucket policy/CDN rules                                                                | Documentation/CI present; enforcement is an infrastructure handoff                          | Platform owner            |
| Staging/production parity | Image digests and configuration comparison                                                                | Not supplied                                                                                | Release owner             |
| Training                  | Recordings, published quick-reference PDFs, FAQ answers and attendance                                    | Templates only                                                                              | Training owner            |
| Go-live/hypercare         | Change window, go-live log, monitoring, metrics and exit acceptance                                       | Not executed                                                                                | Technical/business owners |

## Explicit non-changes

- No PLN-026 performance threshold was relaxed.
- `EMAIL_TEST_MODE` was not enabled and must stay `false` in production.
- Production `docker-compose.yml` was not changed.
- `docker compose down -v` was not used.
