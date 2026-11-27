# UAT-02 — Create and classify work

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Creating and classifying work

## Objective

Confirm that one Bug, Task, Story and Epic can be created with all required
classification fields and that each item appears correctly in every layout.

## Preconditions

- UAT-01 passed for the tester's account and role.
- Work-item types, states, priorities, labels, cycles, modules and views exist
  on staging with UAT data.

## Steps and expected results

|   # | Step                                                             | Expected result                                             | Actual result | Pass/Fail |
| --: | ---------------------------------------------------------------- | ----------------------------------------------------------- | ------------- | --------- |
|   1 | Create one Bug with type, state, priority, assignee and estimate | Bug is created with all values persisted                    |               |           |
|   2 | Add labels, cycle, module and a parent to the Bug                | All associations are saved and visible on the detail page   |               |           |
|   3 | Repeat creation for one Task, one Story and one Epic             | All four items exist with their own type                    |               |           |
|   4 | Open each item in list, board, backlog and cycle layouts         | Each item appears in the correct layout with correct fields |               |           |
|   5 | Apply a saved view that should include the items                 | View returns the expected items and excludes others         |               |           |
|   6 | Edit each classification field and reload                        | Changes persist and audit activity reflects them            |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
