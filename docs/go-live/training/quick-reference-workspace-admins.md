# Quick reference — Workspace admins

**Draft for a two-page PDF. Publisher/date: not recorded.**

| Area               | What to manage                                | Reminder                                                    |
| ------------------ | --------------------------------------------- | ----------------------------------------------------------- |
| Workspace settings | Name, projects, members                       | Names and owners are recorded by the business               |
| Integrations       | Provider configuration surfaces               | Success paths need operator credentials                     |
| Service tokens     | Scope and revocation                          | Store secret values only in the operator secret store       |
| Audit/activity     | Locate and inspect events                     | Use for UAT-11/UAT-12 evidence                              |
| Email              | God Mode email page, test email, delivery log | Keep `EMAIL_TEST_MODE=false` in production                  |
| Backup/restore     | Ownership and drill evidence                  | PLN-025 drill passed; production PITR is a separate handoff |
| Escalation         | On-call and handover                          | See `who-to-ask.md` and `../support-model.md`               |

Do not run `docker compose down -v`. Use `down --remove-orphans` for test
teardown.
