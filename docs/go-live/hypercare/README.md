# Hypercare — PLN-027

**Status: NOT STARTED.** Hypercare covers the first 10 working days after
go-live. No daily stand-up, metric, decision or exit acceptance has been recorded.

| File               | Purpose                                                             |
| ------------------ | ------------------------------------------------------------------- |
| `standup-log.md`   | Daily 15-minute stand-up: defects, questions, adoption blockers     |
| `metrics.csv`      | Daily active users, items, transitions, email, webhook, errors, p95 |
| `decision-log.md`  | Configuration changes requested during hypercare                    |
| `exit-criteria.md` | Written exit decision and acceptance                                |

## Operating rules

- Single intake channel; no side DMs.
- P0 response 1 hour, P1 same day, P2 within 3 days.
- Every configuration change is logged before it is applied.
- Daily metrics are captured by a named owner with a dated evidence file.
- Exit requires 3 consecutive days without P0/P1, adoption by all 15 users and
  the business owner's written acceptance.
- After exit, disable the training sandbox and test accounts and record it.
