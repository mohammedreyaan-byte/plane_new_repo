# UAT-04 — Task, Story and Epic workflows

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Non-bug work-item workflows

## Objective

Walk one Task, one Story and one Epic through their configured states and verify
that an Epic with incomplete children cannot be completed.

## Preconditions

- Task, Story and Epic workflows are configured on staging.
- Child items exist for the Epic test case.

## Steps and expected results

|   # | Step                                                     | Expected result                                      | Actual result | Pass/Fail |
| --: | -------------------------------------------------------- | ---------------------------------------------------- | ------------- | --------- |
|   1 | Move the Task through each configured state              | Every allowed transition succeeds and is recorded    |               |           |
|   2 | Attempt one disallowed Task transition                   | Transition is blocked with an explained reason       |               |           |
|   3 | Move the Story through each configured state             | Every allowed transition succeeds                    |               |           |
|   4 | Add at least two child items to the Epic                 | Children are linked and visible under the Epic       |               |           |
|   5 | Attempt to complete the Epic while a child is incomplete | Guard blocks completion and names the blocking child |               |           |
|   6 | Complete all children, then complete the Epic            | Epic completes successfully                          |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
