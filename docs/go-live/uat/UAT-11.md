# UAT-11 — CI and service tokens

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Automation and scoped API access

## Objective

Confirm that a CI job can comment and transition an item with a correctly scoped
service token, and that a token scoped to another project is denied.

## Preconditions

- A CI runner and service tokens are provisioned by a named operator; secret
  values are never written into this package.
- Token scopes are recorded in writing.

## Steps and expected results

|   # | Step                                                      | Expected result                                       | Actual result | Pass/Fail |
| --: | --------------------------------------------------------- | ----------------------------------------------------- | ------------- | --------- |
|   1 | Run the CI job against an item in its authorized project  | Job authenticates and adds the comment                |               |           |
|   2 | Run the same job to transition the item                   | Transition succeeds and is attributed to the token    |               |           |
|   3 | Use a token scoped to project A against project B         | Request is denied with a not-found/forbidden response |               |           |
|   4 | Attempt to read a project B item with the project A token | No project B data is returned                         |               |           |
|   5 | Revoke the token and retry the CI job                     | Job fails authentication                              |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
