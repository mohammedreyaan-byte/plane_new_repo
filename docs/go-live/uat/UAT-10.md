# UAT-10 — GitHub and Slack

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Developer integrations

## Objective

Confirm that a pull request links to a work item, that a configured Slack
channel receives the intended events and that unconfigured events are not
posted.

## Preconditions

- A GitHub repository and Slack workspace/channel are configured by named
  operators with operator-supplied credentials.
- Event-to-channel mapping is recorded in writing.

## Steps and expected results

|   # | Step                                                  | Expected result                                    | Actual result | Pass/Fail |
| --: | ----------------------------------------------------- | -------------------------------------------------- | ------------- | --------- |
|   1 | Open a pull request referencing a work item ID        | PR link appears on the work item                   |               |           |
|   2 | Merge the pull request                                | Work item activity records the linked PR event     |               |           |
|   3 | Trigger a configured Slack event                      | Expected message appears in the configured channel |               |           |
|   4 | Trigger an event not in the mapping                   | No message is posted to the channel                |               |           |
|   5 | Post to a second channel not configured for the event | No message is posted there                         |               |           |
|   6 | Review integration logs/results                       | Deliveries match the mapping with no duplicates    |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
