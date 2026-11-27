# UAT-12 — Security and isolation

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Access control and isolation

## Objective

Confirm that a project-A user cannot see project-B data, that a guest sees only
their own items and that a removed member loses both access and email.

## Preconditions

- Two projects with distinct members and marked test items exist on staging.
- A named tester controls the accounts used for removal testing.

## Steps and expected results

|   # | Step                                                  | Expected result                                          | Actual result | Pass/Fail |
| --: | ----------------------------------------------------- | -------------------------------------------------------- | ------------- | --------- |
|   1 | As a project-A member, request a project-B item by ID | Request is denied; no content or metadata is returned    |               |           |
|   2 | Search globally for a known project-B title           | No project-B results for the project-A user              |               |           |
|   3 | As a guest, list items                                | Only the guest's own items are visible                   |               |           |
|   4 | As a guest, request another user's item by ID         | Request is denied                                        |               |           |
|   5 | Remove a member from the project                      | Member loses project access immediately                  |               |           |
|   6 | Trigger an email event to the removed member          | No email is delivered to that address for the project    |               |           |
|   7 | Review audit/activity entries                         | Access-denied attempts are recorded without leaking data |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
