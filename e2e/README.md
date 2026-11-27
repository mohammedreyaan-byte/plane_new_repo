# PLN-026 end-to-end suite

Playwright/TypeScript suite in `e2e/`. There is no second runner. Specs live in `e2e/specs`, fixtures and page objects in `e2e/fixtures.ts`, `e2e/support/`, and `e2e/pages/`.

## Commands

From the repository root:

```bash
pnpm test:e2e                 # full suite
pnpm test:e2e:smoke           # @smoke subset (auth + create + transition)
pnpm test:e2e:list            # list discovered tests
pnpm test:e2e:report          # open the HTML report
pnpm seed:e2e                 # deterministic E2E data, with --reset
```

Inside `e2e/` (or with `pnpm --filter @plane/e2e ...`):

```bash
pnpm test -- --grep @smoke
pnpm test -- --grep @production-smoke
pnpm check:types
```

Tests wait on UI/network state; there are no fixed sleeps. Retries are limited to one in CI and a retry is tracked as a flake, not ignored.

## Target environments

- The full suite, nightly schedule, release gate and reusable workflow calls default to `E2E_ENV=staging` against the dedicated staging deployment.
- `E2E_ENV=local` is an explicit opt-in for ad-hoc developer runs and PR validation. A local run is never presented as staging or production evidence.
- `E2E_ENV=production` is an explicit opt-in for the read-only `@production-smoke` subset only.

## Environment variables

All credentials are supplied through environment variables backed by GitHub secrets or a local secret store. Never paste token or password values into YAML, specs, fixtures, logs, or artifacts.

| Variable                              | Required | Default                                              | Purpose                                                                       |
| ------------------------------------- | -------- | ---------------------------------------------------- | ----------------------------------------------------------------------------- |
| `E2E_ENV`                             | no       | `local` ad-hoc; `staging` in full/nightly/release CI | `local`, `staging`, or `production`.                                          |
| `E2E_BASE_URL`                        | no       | `http://127.0.0.1:3000`                              | Base URL of the app under test.                                               |
| `E2E_TEST_PASSWORD`                   | **yes**  | —                                                    | Shared password for the six seeded role accounts. Secret.                     |
| `E2E_SERVICE_TOKEN`                   | no       | —                                                    | Project-scoped service token for API/service scenarios. Secret.               |
| `E2E_WORKSPACE_SLUG`                  | no       | `e2e`                                                | Seeded workspace slug.                                                        |
| `E2E_PROJECT_NAME`                    | no       | `E2E`                                                | Seeded project name.                                                          |
| `E2E_PROJECT_IDENTIFIER`              | no       | `E2E`                                                | Seeded project identifier.                                                    |
| `E2E_WEBHOOK_RECEIVER_URL`            | no       | `http://127.0.0.1:8787`                              | Local webhook receiver.                                                       |
| `E2E_WEBHOOK_SECRET`                  | no       | —                                                    | Webhook signing secret. Secret.                                               |
| `MOCK_WEBHOOK_SECRET`                 | no       | —                                                    | Mock-only signature verifier, sourced from `E2E_WEBHOOK_SECRET`. Secret.      |
| `E2E_GITHUB_MOCK_URL`                 | no       | `http://127.0.0.1:8787`                              | Credential-free local integration mock.                                       |
| `E2E_GITHUB_WEBHOOK_SECRET`           | no       | —                                                    | Operator-supplied GitHub webhook secret. Secret.                              |
| `E2E_SLACK_MOCK_URL`                  | no       | `http://127.0.0.1:8787`                              | Credential-free local integration mock.                                       |
| `E2E_EVENT_SINK_URL`                  | no       | —                                                    | API/worker sink for GitHub/Slack app-to-mock forwarding (local/staging only). |
| `E2E_MAILPIT_URL`                     | no       | —                                                    | Mailpit base URL for email assertions.                                        |
| `E2E_RUN_ID`                          | no       | timestamp                                            | Correlation id for generated data.                                            |
| `E2E_ALLOW_PRODUCTION_SMOKE`          | no       | —                                                    | Must be `1` for the read-only `@production-smoke` subset.                     |
| `E2E_SHARD_INDEX` / `E2E_SHARD_TOTAL` | no       | —                                                    | 1-based shard index and total shard count.                                    |
| `E2E_WEB_SERVER_COMMAND`              | no       | —                                                    | Optional Playwright-managed web server command.                               |

## Credential-free integration mock

Local, PR, staging/full and release runs start the in-process mock on `127.0.0.1:8787` (the default port) and wait for `/health`:

```bash
pnpm --filter @plane/e2e mock:integrations
curl -fsS http://127.0.0.1:8787/health
```

The mock is credential-free: it records webhook/message payloads in memory and requires no provider credentials. `E2E_GITHUB_MOCK_URL`, `E2E_SLACK_MOCK_URL` and `E2E_WEBHOOK_RECEIVER_URL` all point at this URL.

For signed-delivery assertions the mock accepts `MOCK_WEBHOOK_SECRET` as an operator-supplied environment variable, populated in CI from the `E2E_WEBHOOK_SECRET` GitHub secret expression only. Its value must never be written in this repository or in specs, fixtures, logs, or artifacts. When set, the mock verifies `X-Plane-Signature` on `/receiver/e2e/01`; without it, records are marked `signature_verified: false` and the signed-delivery scenario cannot pass. The GitHub webhook scenario still uses `E2E_GITHUB_WEBHOOK_SECRET` (referenced by GitHub secret name only) to match the application's webhook configuration.

GitHub/Slack app-to-mock event forwarding requires `E2E_EVENT_SINK_URL` on the API and worker, pointing at this mock URL, plus an explicit `E2E_ALLOW_LOCAL_STAGING=1` or `PLANE_E2E_ENV=local|staging` on those processes. Forwarding is refused in production.

Companion load variables (see `docs/testing/performance.md`):

| Variable                   | Purpose                                           |
| -------------------------- | ------------------------------------------------- |
| `LOAD_SCENARIO`            | `smoke`, `average`, `stress`, `spike`, `soak`.    |
| `LOAD_BASE_URL`            | Dedicated local/staging base URL.                 |
| `LOAD_SERVICE_TOKEN`       | Service token scoped to the load project. Secret. |
| `LOAD_ENV`                 | `local` or `staging`; production is refused.      |
| `LOAD_PROJECT_ID`          | UUID printed by `seed_load`.                      |
| `LOAD_WORKSPACE_SLUG`      | Defaults to `load`.                               |
| `LOAD_ALLOW_LOCAL_STAGING` | Must be `1` for load generation.                  |
| `LOAD_SUMMARY_PATH`        | Output path for the k6 JSON summary.              |

## Sharding

The nightly job runs the full suite in four shards:

```bash
E2E_SHARD_INDEX=1 E2E_SHARD_TOTAL=4 pnpm test:e2e
E2E_SHARD_INDEX=2 E2E_SHARD_TOTAL=4 pnpm test:e2e
E2E_SHARD_INDEX=3 E2E_SHARD_TOTAL=4 pnpm test:e2e
E2E_SHARD_INDEX=4 E2E_SHARD_TOTAL=4 pnpm test:e2e
```

Each shard uploads `playwright-report/` and `test-results/`. The flake job merges the JSON results into a 14-day dashboard; a scenario failing more than twice in that window is quarantined and fixed within a week.

## Environment and production guard

- `E2E_ENV=staging` is the default target for the full suite, nightly schedule, release gate and reusable workflow calls. It must use a deployment with the same image digests as production, a separate database, Mailpit, and the credential-free local GitHub/Slack mock.
- `E2E_ENV=production` is **refused** unless `E2E_ALLOW_PRODUCTION_SMOKE=1`, and then only scenarios tagged `@production-smoke` may run. These are read-only checks only: no test project is created, and no destructive tests, load generation, or seeding run against production data.
- The load runner refuses `LOAD_ENV=production`, production-looking hosts, and any run without `LOAD_ALLOW_LOCAL_STAGING=1`. `seed_load` refuses any `DJANGO_SETTINGS_MODULE` that looks like production with no override.

## Cleanup

- Scenarios create uniquely named entities and clean them up through fixtures; do not rely on a global reset between tests.
- `pnpm seed:e2e` re-seeds deterministically with `--reset` and only affects the dedicated E2E project.
- After a local compose run: stop the isolated stack with `docker compose down --remove-orphans` and keep its volumes. Do not delete local data volumes as part of test cleanup.
- Never delete or reset staging/production workspaces to "clean up" a failed run; use the dedicated project and its recorded ids.

## Evidence locations

| Artifact                                   | Local path                                           | CI artifact                  |
| ------------------------------------------ | ---------------------------------------------------- | ---------------------------- |
| HTML report                                | `e2e/playwright-report/index.html`                   | `pln026-e2e-report-<shard>`  |
| Traces and screenshots                     | `e2e/test-results/`                                  | `pln026-e2e-traces-<shard>`  |
| Machine-readable results                   | `e2e/test-results/results.json`                      | `pln026-e2e-results-<shard>` |
| 14-day flake dashboard                     | generated in CI                                      | `pln026-flake-dashboard`     |
| k6 summary JSON                            | `load-tests/results/k6-<scenario>.json`              | `pln026-k6-<scenario>`       |
| Performance before/after and EXPLAIN plans | `docs/testing/performance.md`, `load-tests/results/` | `pln026-performance-diff`    |

## Evidence register

Record one row per gated run from the uploaded artifacts. Expected paths are `e2e/playwright-report/index.html` and `load-tests/results/k6-<scenario>.json`; no measurements are invented here.

| Run ID       | Date         | Commit SHA   | Environment  | Playwright report path | k6 summary path | Gate result  | Approver     |
| ------------ | ------------ | ------------ | ------------ | ---------------------- | --------------- | ------------ | ------------ |
| not recorded | not recorded | not recorded | not recorded | not recorded           | not recorded    | not recorded | not recorded |
| not recorded | not recorded | not recorded | not recorded | not recorded           | not recorded    | not recorded | not recorded |
| not recorded | not recorded | not recorded | not recorded | not recorded           | not recorded    | not recorded | not recorded |

The written threshold acceptance policy is in `docs/testing/performance.md`: thresholds must not be weakened, and any unmet threshold requires dated written acceptance before release.
