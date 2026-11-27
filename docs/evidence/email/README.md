# Email delivery evidence pack (PLN-017)

This directory holds the recorded results of the 20-case test matrix from
`prompts/23-PLN-017.txt`. Evidence must never contain SMTP passwords, app passwords, mailbox
passwords, full message bodies with real customer data, or credential-bearing URLs.

## Status

Automated backend coverage is implemented and documented in `docs/email-delivery.md`. Real-relay,
Gmail and Microsoft 365 validation is **credential-dependent and pending**: no provider credentials
or production relay details were available in the code-only environment. Do not mark the matrix
complete until the deployment owner records each case below.

## File convention

Create one file per case, for example `01-admin-test-email.md`, using this template:

```markdown
# Case 01 — Instance admin Send test email

- Status: PASS / FAIL
- Date/time (UTC):
- Environment: staging / production
- Relay: <provider or Mailpit; no credentials>
- Sender: notifications@<dedicated-subdomain>
- Recipient: <masked or internal test mailbox>
- Subject:
- Message-ID:
- SMTP response (code / enhanced status):
- Screenshot: ./screenshots/01-admin-test-email.png
- Checks: plain-text alternative, HTML body, public links, no secrets in output
- Notes:
```

## Matrix

| #   | Case                                                      | Evidence file                       | Status  |
| --- | --------------------------------------------------------- | ----------------------------------- | ------- |
| 1   | Admin Send test email                                     | `01-admin-test-email.md`            | Pending |
| 2   | Workspace invitation, link works                          | `02-workspace-invitation.md`        | Pending |
| 3   | Existing user invited to second workspace                 | `03-second-workspace-invitation.md` | Pending |
| 4   | Project invitation / added to project                     | `04-project-invitation.md`          | Pending |
| 5   | Password reset, link works                                | `05-password-reset.md`              | Pending |
| 6   | Magic link sign-in, link works                            | `06-magic-link.md`                  | Pending |
| 7   | Email change verification                                 | `07-email-change.md`                | Pending |
| 8   | Assignment notification                                   | `08-assignment.md`                  | Pending |
| 9   | State change notification                                 | `09-state-change.md`                | Pending |
| 10  | Comment notification                                      | `10-comment.md`                     | Pending |
| 11  | Mention notification                                      | `11-mention.md`                     | Pending |
| 12  | Work item completed notification                          | `12-completed.md`                   | Pending |
| 13  | Due soon and overdue via task                             | `13-due-dates.md`                   | Pending |
| 14  | Daily digest, one summary, no duplicates                  | `14-daily-digest.md`                | Pending |
| 15  | Webhook deactivation email                                | `15-webhook-deactivation.md`        | Pending |
| 16  | Unsubscribe link works without login                      | `16-unsubscribe.md`                 | Pending |
| 17  | Plain-text alternative present and readable               | `17-plain-text.md`                  | Pending |
| 18  | Non-ASCII names and emoji                                 | `18-non-ascii.md`                   | Pending |
| 19  | 200+ character title truncated in subject only            | `19-long-subject.md`                | Pending |
| 20  | Relay outage produces logged error, no crash or duplicate | `20-relay-outage.md`                | Pending |

## Provider sign-off

Record separate `gmail-authentication.md` and `microsoft365-authentication.md` files with masked
message identifiers and `spf=pass`, `dkim=pass`, `dmarc=pass` results. Record relay suppression
dashboard findings and removed-member isolation checks in `deliverability.md`.

## Evidence already produced by automation

- Focused backend test results: `.playwright-mcp/issue-pln017-backend-result.json`
- Manual relay procedure and safe defaults: `docs/email-delivery.md`
- Mailpit compose overlays: `docker-compose.mailpit.yml`, `docker-compose.mailpit.test.yml`
