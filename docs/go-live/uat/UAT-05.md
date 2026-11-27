# UAT-05 — Backlog and sprint

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Backlog ranking and cycle planning

## Objective

Confirm backlog ranking, cycle planning, item movement, completion, cycle close
with carry-over and burndown accuracy.

## Preconditions

- At least ten unstarted work items exist in the UAT project.
- A cycle is available for planning and a named owner can close it.

## Steps and expected results

|   # | Step                                                | Expected result                                              | Actual result | Pass/Fail |
| --: | --------------------------------------------------- | ------------------------------------------------------------ | ------------- | --------- |
|   1 | Rank backlog items by drag or keyboard ordering     | New order persists after reload                              |               |           |
|   2 | Move selected items into a planned cycle            | Items appear in the cycle and leave the unplanned backlog    |               |           |
|   3 | Complete some items while leaving at least one open | Completed and open states are reflected in the cycle         |               |           |
|   4 | Close the cycle with an open item                   | Cycle closes and the open item is carried over as configured |               |           |
|   5 | Open the burndown report for the closed cycle       | Remaining-work line matches the manual count of open items   |               |           |
|   6 | Reopen the backlog and verify carried-over item     | Item is present with correct cycle state                     |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
