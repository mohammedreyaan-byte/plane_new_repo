# Workflow state write rules

`plane.utils.workflow.transition.transition_issue` is the only ordinary runtime path that
moves an existing work item from one workflow state to another. It locks the row, checks
the active workflow and transition policy, then saves the state. API updates, bulk updates,
and scheduled auto-close must call this service.

## Narrow allowlist

- `plane/utils/workflow/transition.py`: the transition service's validated assignment.
- `plane/db/models/issue.py` and `plane/db/models/draft.py`: assign an initial default
  state only while creating an item/draft that has no state yet.
- `plane/app/serializers/intake.py` and `plane/api/serializers/intake.py`: accepting a
  triaged intake item assigns the configured initial project state. This is intake
  acceptance into the workflow, not a transition between workflow states.
- `plane/db/management/commands/repair_states.py`: an explicit, dry-run-by-default PLN-002
  repair command. Its bulk `.update(state=...)` is part of the documented allowlist.
- Database migrations and tests may set state directly to migrate or arrange fixtures.

Do not add direct state assignments or bulk state updates elsewhere. If a new system path
must move existing items, route it through `transition_issue` and preserve its actor,
activity, and notification behavior.

## Guard

`check_state_writes.py` fails CI when runtime code assigns `.state` directly or calls
`.update(state=...)` outside the allowlist above. Migrations and tests may set state
directly to arrange data. Run the same check locally from the repository root:

```bash
python apps/api/plane/utils/workflow/check_state_writes.py
```

The check runs as the `Guard workflow state writes` step in
`.github/workflows/pull-request-build-lint-api.yml`.
