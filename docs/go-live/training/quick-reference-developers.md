# Quick reference — Developers

**Draft for a two-page PDF. Publisher/date: not recorded.**

| Task           | Where                | Key points                                                      |
| -------------- | -------------------- | --------------------------------------------------------------- |
| Rank backlog   | Project -> Backlog   | Drag or use keyboard ordering; order persists                   |
| Plan a cycle   | Cycle planning       | Move items into the cycle; remove before close if needed        |
| Work the board | Project -> Board     | Drag only between allowed states                                |
| Bug flow       | Work-item detail     | New -> In Progress -> Code Review -> In Testing -> Tested       |
| PR link        | Pull request text    | Reference the work-item ID; link appears in activity            |
| Estimate       | Work-item detail     | Set estimate before planning if required by the team            |
| Sub-items      | Work-item detail     | Add children; parent progress follows children                  |
| Bulk actions   | List/board selection | Change state/assignee for several items at once                 |
| Shortcuts      | Keyboard             | Use search and navigation shortcuts after training confirmation |

## Remember

- You cannot close a bug at `Tested`; QA owns the final transition.
- Blocked columns are explained by workflow rules, not by a defect.
- Do not paste tokens or credentials into PR text or item comments.
