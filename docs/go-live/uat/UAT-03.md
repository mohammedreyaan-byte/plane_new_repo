# UAT-03 — Bug workflow

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Defect resolution workflow

## Objective

Walk a real bug through `New -> In Progress -> Code Review -> In Testing ->
Tested -> Closed` with the actual developer and QA users, confirming that the
developer is blocked at `Tested` and only QA can close.

## Preconditions

- Bug workflow is configured on staging with the listed states and guards.
- A named developer account and a named QA account are available.

## Steps and expected results

|   # | Step                                                          | Expected result                                        | Actual result | Pass/Fail |
| --: | ------------------------------------------------------------- | ------------------------------------------------------ | ------------- | --------- |
|   1 | QA creates a bug in `New` with reproduction evidence attached | Bug is created in `New` with attachment visible        |               |           |
|   2 | Developer transitions `New -> In Progress`                    | Transition succeeds and activity records the developer |               |           |
|   3 | Developer transitions `In Progress -> Code Review`            | Transition succeeds                                    |               |           |
|   4 | Developer transitions `Code Review -> In Testing`             | Transition succeeds and QA is notified                 |               |           |
|   5 | QA transitions `In Testing -> Tested`                         | Transition succeeds                                    |               |           |
|   6 | Developer attempts `Tested -> Closed`                         | Transition is blocked with an explained reason         |               |           |
|   7 | QA transitions `Tested -> Closed`                             | Transition succeeds and closure is recorded            |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
