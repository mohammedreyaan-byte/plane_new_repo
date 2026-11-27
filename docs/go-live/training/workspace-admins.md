# Workspace-admin training — 45 minutes

**Status: NOT DELIVERED.** Outline for TRAIN-05. Use the sandbox project only.

## Learning outcomes

Workspace admins can manage workspace settings, integrations, service tokens,
audit views, email settings, backup/restore ownership and escalation.

## Agenda

| Minutes | Topic                           | Demonstration                                          | Practice                |
| ------: | ------------------------------- | ------------------------------------------------------ | ----------------------- |
|     0-8 | Workspace settings and projects | Settings overview, project list                        | Review sandbox settings |
|    8-18 | Integrations and service tokens | Configuration surfaces, scope model; no secret display | Name token owners       |
|   18-25 | Audit and activity              | Locate audit/activity views                            | Inspect one event       |
|   25-32 | Email settings and delivery log | God Mode email page, test email, delivery log          | Identify mail owner     |
|   32-39 | Backup and restore ownership    | Runbook pointers, drill evidence, escalation           | Name backup owner       |
|   39-45 | Escalation and handover         | `who-to-ask.md`, support model, hypercare exit         | Questions               |

## Guardrails

- `EMAIL_TEST_MODE` must stay `false` in production.
- Secret values belong in the operator's secret store, never in this package,
  tickets or chat.
- Backup restores go to isolated targets unless explicitly approved.

## Delivery record

| Field                   | Value         |
| ----------------------- | ------------- |
| Trainer                 |               |
| Date                    |               |
| Attendance file         | None recorded |
| Recording link          | None recorded |
| Sandbox reset confirmed |               |
