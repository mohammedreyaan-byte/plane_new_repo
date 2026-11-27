# Quick reference — QA

**Draft for a two-page PDF. Publisher/date: not recorded.**

| Task        | Where                    | Key points                                      |
| ----------- | ------------------------ | ----------------------------------------------- |
| Test a bug  | Work-item detail         | `In Testing -> Tested` after verifying the fix  |
| Close a bug | Work-item detail         | `Tested -> Closed`; QA owns this transition     |
| Reopen      | Work-item detail         | Reopen with a reason and evidence               |
| Raise a bug | Project -> New work item | Steps, expected vs actual, severity, attachment |
| Filter      | Board/list filters       | State, assignee, priority, type                 |
| Save view   | Filters -> Save          | Name and share with the team                    |
| Report      | Project -> Reports       | Verify counts against a manual list; export CSV |

## Remember

- Developers are blocked at `Tested`; this is intentional workflow control.
- Attach evidence, never real customer data from production.
- Link a defect ID to every failed UAT step in `defect-log.md`.
