# PLN-027 go-live package

This directory contains the UAT, training, go-live and hypercare **framework** for
PLN-027. It is a working package for named human owners to execute and evidence;
it is **not** a record of completed UAT, training or go-live.

## Current status

**NOT READY.** The automated readiness gate currently reports 6 evidence checks
passed and 35 human criteria blocking. No UAT scenario, business or technical
sign-off, training session, production smoke, go-live execution or hypercare
metric has been recorded. The Google Sheet cell `H28` remains `To Do` and is not
to be changed until the full acceptance checklist is evidenced.

## Contents

| Path                      | Purpose                                                          |
| ------------------------- | ---------------------------------------------------------------- |
| `readiness-checklist.md`  | Every readiness criterion with owner and date fields             |
| `readiness-manifest.json` | Machine-readable criteria consumed by the gate                   |
| `uat/`                    | Twelve executable UAT scripts and the summary tracker            |
| `uat-summary.md`          | Results, defects and sign-off record (pending)                   |
| `defect-log.md`           | P0-P3 defect register (empty)                                    |
| `training/`               | Five audience outlines, quick references, FAQ and handover pages |
| `runbooks/`               | Deploy, rollback, backup/restore and incident runbooks           |
| `support-model.md`        | Support boundaries, hours and escalation                         |
| `known-limitations.md`    | Accepted P2/P3 items and workarounds (pending)                   |
| `release-notes.md`        | Plain-language changes for users                                 |
| `data-migration.md`       | Import counts and reconciliation (pending)                       |
| `go-live-plan.md`         | T-14 / T-7 / T-1 / go-live-day plan                              |
| `go-live-log.md`          | Controlled execution and monitoring log (pending)                |
| `hypercare/`              | Stand-up, metrics, decision log and exit criteria                |

## Readiness gate

From the workspace root:

```text
python plane-ce-project/scripts/go-live/readiness_gate.py
python plane-ce-project/scripts/go-live/readiness_gate.py --json
```

Exit codes: `0` ready, `1` not ready, `2` invalid manifest or evidence document.

The gate reads completed evidence from earlier tickets for automated criteria.
Human criteria pass only when `.playwright-mcp/pln027-uat-go-live-result.json`
contains, for that criterion ID, a record with `status: "pass"`, a named `owner`,
an ISO-8601 `date`, and at least one evidence file that exists and is not empty.
The gate never writes to either document and never treats prose in Markdown as
evidence. Editing a status to `pass` without real evidence is a process failure,
not a gate failure.

## Rules for owners

1. Execute UAT on staging against the release candidate; record actual results,
   tester, date and an evidence file for every scenario.
2. Link every defect to a ticket and a fix commit. No verbal fixes.
3. Obtain written business and technical sign-off before the change window.
4. Train on the sandbox project, never on production data.
5. Do not start the go-live window until the gate exits `0`.
6. Keep `EMAIL_TEST_MODE=false` in production.
7. Do not run `docker compose down -v`; use `down --remove-orphans`.
8. Do not store credentials, secrets or fake provider values in this package.
