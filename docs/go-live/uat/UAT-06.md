# UAT-06 — Board and filters

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Daily board work

## Objective

Use the board as a user would for a working day: confirm allowed drags, explain
blocked columns, filter by type/assignee/priority and save and share a view.

## Preconditions

- Board columns and transition rules are configured on staging.
- At least one item exists in each tested state.

## Steps and expected results

|   # | Step                                                | Expected result                                    | Actual result | Pass/Fail |
| --: | --------------------------------------------------- | -------------------------------------------------- | ------------- | --------- |
|   1 | Drag an item between two states the workflow allows | Card moves and state updates after reload          |               |           |
|   2 | Drag an item into a blocked column                  | Move is rejected and the reason is explained       |               |           |
|   3 | Filter by work-item type                            | Only matching cards remain                         |               |           |
|   4 | Add assignee and priority filters                   | Combined filters return the correct intersection   |               |           |
|   5 | Save the filtered board as a named view             | View is saved and listed for the user              |               |           |
|   6 | Share the view with another named user              | Recipient can open it with the same filters        |               |           |
|   7 | Clear filters and reload the board                  | Default board is restored without residual filters |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
