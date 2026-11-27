# Release notes — plain-language summary

These notes describe capabilities delivered in this programme. They are a
draft for the release owner to confirm against the actual release candidate;
no deployment date or production availability is claimed here.

## What users can do

- Work inside isolated projects: members see only the projects and items they
  are entitled to see, and guests see only their own items.
- Use work-item templates, page comments and embeds, and import work from CSV,
  Jira and GitHub job flows.
- Manage initiatives, automations and GitHub/GitLab/Slack integrations through
  the settings pages.
- Create and classify bugs, tasks, stories and epics with states, priorities,
  assignees, estimates, labels, cycles, modules and saved views.
- Follow defined workflows with blocked transitions enforced, so QA controls
  the final test-to-closed step.
- Receive in-app notifications and email notifications; administrators can
  configure SMTP in God Mode, send a test email, inspect the delivery log and
  manage unsubscribe behaviour.
- Change the interface language from personal preferences. The signed-in user's
  UI was observed in Spanish and changed to English through the UI; this is a
  per-user preference and not a code change.

## What administrators and operators get

- Backup, verify, restore and retention tooling with manifests and checksums,
  plus runbooks for isolated restore drills.
- End-to-end and load-test suites with guarded staging-by-default targets and a
  read-only production smoke check.
- A dependency-free readiness gate that refuses to declare go-live readiness
  while any human criterion lacks named, dated evidence.
- Documentation for UAT scripts, training, support, rollback, incidents and
  hypercare.

## What has not changed or is not yet verified

- No performance threshold was weakened.
- No production configuration or production data was changed by this package.
- Real provider success paths, real mailbox delivery and live load thresholds
  remain environment-dependent handoffs.
- Go-live and hypercare have not been executed.

## Confirmation required before publishing

- Release version and image digests: **not recorded**
- Deployment date and window: **not recorded**
- Release owner approval: **not recorded**
