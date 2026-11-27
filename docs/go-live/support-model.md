# Support model — PLN-027 hypercare

No names, hours or channels have been supplied. Every field below is a template
for the named owners to complete before hypercare starts.

## Roles

| Role             | Name | Responsibility                            | Contact channel | Escalation to |
| ---------------- | ---- | ----------------------------------------- | --------------- | ------------- |
| UAT coordinator  |      | Owns scripts, results and evidence        |                 |               |
| Business owner   |      | Accepts UAT and P2/P3 items               |                 |               |
| Technical owner  |      | Deploy/rollback decisions and retest      |                 |               |
| Product owner    |      | Priority and scope decisions              |                 |               |
| On-call engineer |      | P0/P1 response during hypercare           |                 |               |
| Backup owner     |      | Backup verification and restore execution |                 |               |
| Monitoring owner |      | Alerts, dashboards and log access         |                 |               |

## Intake

- Single intake channel: **not configured**
- Side DMs are not accepted as intake; they must be redirected to the channel.
- Request types: defect, question, configuration change, access change.

## Response targets (first 10 working days)

| Severity | Response target  | Resolve/escalate target               |
| -------- | ---------------- | ------------------------------------- |
| P0       | 1 hour           | Continuous until resolved or rollback |
| P1       | Same working day | Written workaround or fix             |
| P2       | 3 working days   | Scheduled after go-live               |
| P3       | Best effort      | Log only                              |

## Support hours

- Hypercare coverage window: **not configured**
- Outside-hours on-call route: **not configured**
- Escalation after 30 minutes without P0 acknowledgement: **not configured**

## Boundaries

- Support owns platform defects and configuration questions; the business owner
  owns acceptance and priority decisions.
- Configuration changes during hypercare require an entry in
  `hypercare/decision-log.md`; no undocumented changes.
- Production data changes require named approval and a recorded reason.
- Secrets are never pasted into the intake channel or this package.
