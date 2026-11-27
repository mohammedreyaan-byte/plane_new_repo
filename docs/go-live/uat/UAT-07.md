# UAT-07 — Modules and Epic linkage

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Module planning and Epic progress

## Objective

Confirm that an Epic can be linked to a module, children can be added and module
progress reflects the children correctly.

## Preconditions

- At least one module and one Epic exist on staging.
- Child work items are available to link to the Epic.

## Steps and expected results

|   # | Step                                        | Expected result                                           | Actual result | Pass/Fail |
| --: | ------------------------------------------- | --------------------------------------------------------- | ------------- | --------- |
|   1 | Link the Epic to a module                   | Link is saved and visible on both the Epic and the module |               |           |
|   2 | Add three child items to the Epic           | Children are listed under the Epic                        |               |           |
|   3 | Complete one child                          | Module progress updates to reflect one of three complete  |               |           |
|   4 | Open the module detail and inspect progress | Progress percentage/count matches the manual calculation  |               |           |
|   5 | Unlink the Epic from the module             | Epic is removed from the module and progress recalculates |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
