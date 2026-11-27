# UAT-08 — Reporting

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Reporting and export

## Objective

Confirm that standard reports show counts that match a manually prepared list
and that CSV export can be opened and checked.

## Preconditions

- A manual expected-count list is prepared and dated by the tester.
- Reports are populated with the UAT project data.

## Steps and expected results

|   # | Step                                                             | Expected result                                | Actual result | Pass/Fail |
| --: | ---------------------------------------------------------------- | ---------------------------------------------- | ------------- | --------- |
|   1 | Open each standard report                                        | Reports load without error                     |               |           |
|   2 | Compare report counts to the manual list per state/type/assignee | All counts match                               |               |           |
|   3 | Apply a date or project filter                                   | Counts match the manually filtered expectation |               |           |
|   4 | Export the filtered report to CSV                                | Download completes with a readable file        |               |           |
|   5 | Open the CSV in a spreadsheet tool                               | Columns and rows match the on-screen report    |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
