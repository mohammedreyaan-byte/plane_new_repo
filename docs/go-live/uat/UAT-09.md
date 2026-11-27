# UAT-09 — Notifications and email

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Notifications and email delivery

## Objective

Confirm in-app notifications and email delivery on two configured providers for
assign, mention and transition events, plus unsubscribe from one event.

## Preconditions

- Two real provider accounts/mailboxes are configured by a named operator.
- `EMAIL_TEST_MODE=false` remains set in production; staging settings are
  recorded by the mail administrator.
- SMTP delivery log is accessible in God Mode.

## Steps and expected results

|   # | Step                                               | Expected result                                                | Actual result | Pass/Fail |
| --: | -------------------------------------------------- | -------------------------------------------------------------- | ------------- | --------- |
|   1 | Assign an item to a named user                     | In-app bell shows the notification                             |               |           |
|   2 | Check the recipient mailbox on provider one        | Assignment email is delivered                                  |               |           |
|   3 | Check the same event on provider two               | Assignment email is delivered there too                        |               |           |
|   4 | Mention a user in a comment                        | In-app notification and email are produced                     |               |           |
|   5 | Transition an item to a watched state              | Subscribed recipient receives the event                        |               |           |
|   6 | Use the signed unsubscribe link for one event type | That event type no longer produces email; other types still do |               |           |
|   7 | Inspect the God Mode delivery log                  | Delivery attempts and outcomes are recorded                    |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
