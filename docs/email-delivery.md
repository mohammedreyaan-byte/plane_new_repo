# Email delivery validation (PLN-017)

This document describes the production-ready email delivery controls added for PLN-017 and the
manual steps needed to sign off a real deployment. No SMTP credentials, mailbox contents or
provider dashboard screenshots belong in this repository.

## Configuration source of truth

SMTP values are stored in the instance configuration through **God Mode → Email**. The API also
reads environment fallbacks for first-run/bootstrap scenarios, but the admin form is the source of
truth for a configured instance. The password is write-only: the API returns only
`EMAIL_HOST_PASSWORD_SET` and stores the encrypted value.

Defaults and guards:

| Setting                            | Default      | Purpose                                                                                            |
| ---------------------------------- | ------------ | -------------------------------------------------------------------------------------------------- |
| `EMAIL_TIMEOUT`                    | `10` seconds | A dead relay cannot hang a web worker or Celery worker.                                            |
| `EMAIL_RATE_LIMIT_PER_MINUTE`      | `60`         | In-process token bucket shared by every outbound path. A `locmem` test backend is never throttled. |
| `EMAIL_SUBJECT_MAX_BYTES`          | `150`        | Subjects are truncated by UTF-8 byte length; full titles remain in bodies.                         |
| `EMAIL_TEST_MODE`                  | `false`      | Redirects every message to one test inbox and prefixes subjects with `[EMAIL TEST MODE]`.          |
| `EMAIL_TEST_RECIPIENT`             | empty        | Required and validated when test mode is on.                                                       |
| `EMAIL_TEST_MODE_ALLOW_REAL_RELAY` | `false`      | Explicit staging opt-in. Without it, test mode refuses any host that is not local/reserved.        |
| `EMAIL_UNSUBSCRIBE_MAX_AGE_DAYS`   | `90`         | Maximum age of a signed one-click unsubscribe link.                                                |

When `EMAIL_TEST_MODE=true` and the configured relay is a real host, delivery fails with:

> `EMAIL_TEST_MODE is enabled with a real SMTP relay. Use a local test relay or set EMAIL_TEST_MODE_ALLOW_REAL_RELAY=1 explicitly for staging.`

Production deployments must leave `EMAIL_TEST_MODE=false`.

## Safe outbound path

All application email uses `plane.utils.smtp.send_email_message` (or the Celery wrapper
`plane.bgtasks.email_task.deliver_email_message`). That central path applies suppression, the
rate limit, test-mode redirection, safe error translation and SMTP response logging. Logs contain
only the numeric SMTP code and enhanced status (for example `535 5.7.8`); they never contain
credentials, headers or bodies.

Admin **Send test email** is asynchronous:

1. `POST /api/instances/smtp/test-email/` validates the admin and recipient, writes `queued`, and
   enqueues `send_test_email.delay(...)`.
2. The worker re-reads the database configuration and sends the message. Credentials are never
   serialised onto the queue.
3. `GET /api/instances/smtp/test-email/` returns `idle | queued | success | failed`, the safe
   message and timestamp. The admin UI polls this endpoint and stops after 60 seconds.

Recent attempts are available at `GET /api/instances/email-delivery-log/` and
`GET /api/instances/email-delivery-log/<id>/`. Authentication failures are terminal and are not
retried. Temporary failures use bounded exponential backoff; hard-bounced recipients are added to
the suppression list.

Signed unsubscribe links are public and login-free at
`/api/public/unsubscribe/<token>/` (GET or POST). They disable only the event type encoded in the
token. Security messages (password reset, magic link, verification) never add unsubscribe links.

## Local Mailpit validation

Mailpit is a private local relay. Its UI binds to `127.0.0.1` only; SMTP is not published to the
host.

```bash
# Start the private relay
docker compose -f docker-compose.mailpit.yml up -d

# Configure in God Mode -> Email
#   Host: mailpit      Port: 1025      TLS/SSL: off      Auth: blank
#   Sender: notifications@example.invalid
# UI: http://127.0.0.1:8025
```

Use the admin **Send test email** action, then confirm the message in the Mailpit UI with the
expected `From`, `Subject`, plain-text alternative and HTML body. To stop the relay without
deleting any volume:

```bash
docker compose -f docker-compose.mailpit.yml stop
```

## Automated tests and smoke command

Run the focused backend suite without destroying the test volumes:

```bash
docker compose -f docker-compose-test.yml run --rm --build api-tests pytest \
  plane/tests/unit/utils/test_smtp.py \
  plane/tests/unit/utils/test_unsubscribe.py \
  plane/tests/unit/utils/test_email_templates.py \
  plane/tests/unit/bg_tasks/test_email_task.py \
  plane/tests/contract/app/test_smtp_endpoints.py \
  plane/tests/contract/app/test_project_invite_task_dispatch.py
```

The Mailpit integration test is manual and never contacts a real relay:

```bash
docker compose -f docker-compose-test.yml -f docker-compose.mailpit.test.yml run --rm --build \
  api-tests pytest -m integration
```

The smoke command sends cases 1–4 and prints a pass/fail table. It cleans up invitation rows it
creates and never prints credentials or message bodies:

```bash
python manage.py email_smoke_test \
  --to recipient@example.invalid \
  --workspace-slug example-workspace \
  --project-id 00000000-0000-0000-0000-000000000000

# Safe preview without sending:
python manage.py email_smoke_test --dry-run
```

Use `--to` repeatedly for additional mailboxes. In `EMAIL_TEST_MODE`, all messages go to the
configured test inbox and the table labels the recipient as `test inbox`.

## Manual test matrix handoff

The 20-case matrix in `prompts/23-PLN-017.txt` requires real mailboxes and a configured relay. It
cannot be completed from a code-only environment. For each case, record sender, recipient, subject,
timestamp, message-id, SMTP response and a screenshot in `docs/evidence/email/<case>.md` using the
template in `docs/evidence/email/README.md`.

Provider-specific checks still to be completed by the deployment owner:

- Gmail **Show original** shows `spf=pass`, `dkim=pass`, `dmarc=pass` and the message is in Inbox.
- Microsoft 365 shows the same authentication results and the message is not quarantined.
- The relay suppression/bounce dashboard has no unexpected entries after the run.
- Links use the public `WEB_URL`, not `localhost`, and resolve to the correct workspace/item.
- Unsubscribing from one event type does not stop security email.
- Removed project members receive no further project email.

SPF, DKIM and DMARC are configured on the sending domain and relay, not in this application. Use a
dedicated subdomain, publish the relay's SPF include and DKIM selector, start DMARC at `p=none`
with `rua` reporting, and move to quarantine only after two weeks of clean reports.

## Failure behaviour

| Failure                   | Observable behaviour                                                                                        |
| ------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Wrong credentials         | Admin test returns `failed` with `Invalid SMTP credentials provided`; no retry; no secret in logs.          |
| Relay timeout             | Delivery log records `Timeout or network error while connecting to the SMTP server`; bounded retry applies. |
| 550/551 hard bounce       | Recipient is suppressed and retries stop.                                                                   |
| 421/450 temporary failure | Bounded exponential backoff with a maximum delay of one hour.                                               |
| Duplicate retry           | Lock/idempotency checks prevent a second message for the same activity.                                     |
