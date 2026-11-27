# PLN-026 performance and load-testing runbook

This runbook defines how to produce the performance evidence attached to the go-live approval. It is written for a **dedicated local or staging deployment** that mirrors the production image digests and Postgres major version. It deliberately contains no credentials.

Staging is the default target for nightly, release and reusable-call runs. `LOAD_ENV=local` is an explicit opt-in for ad-hoc local compose runs; local evidence must never be relabelled as staging. Production load generation is prohibited; only the read-only production E2E smoke subset is permitted.

> **Evidence boundary:** a laptop/local `docker compose` run is a development check only. It **cannot** be presented as staging or production evidence unless the infrastructure, seeded data, and credentials for that environment are supplied by an operator and the run is recorded below. Never relabel a local run as staging evidence. Production load generation is prohibited; only the read-only production E2E smoke subset is permitted.

## 1. Prerequisites

1. Seed the dedicated project (never a shared workspace):

   ```bash
   pnpm seed:load
   # or, explicitly:
   docker compose exec -e PLANE_LOAD_ENV=local -e LOAD_ALLOW_LOCAL_STAGING=1 api \
     python manage.py seed_load --workspace load --project Load --identifier LOAD --allow-local-staging
   ```

   The command prints the deterministic counts (`5,000` work items, `20` states, `500` label links, `200` cycles, `200` modules, `6` users) and **zero** service tokens created. Provision the project-scoped service token separately through the normal admin flow; pass it to k6 only through `LOAD_SERVICE_TOKEN`.

2. Export the configuration in the shell or CI step (values shown are placeholders, never real secrets):

   ```bash
   export LOAD_SCENARIO=average
   export LOAD_BASE_URL=https://<dedicated-staging-host>
   export LOAD_ENV=staging
   export LOAD_PROJECT_ID=<project-uuid-from-seed-output>
   export LOAD_WORKSPACE_SLUG=load
   export LOAD_ALLOW_LOCAL_STAGING=1
   export LOAD_SERVICE_TOKEN="<project-scoped-token-from-secret-store>"
   ```

   Optional observability probes:

   ```bash
   export LOAD_PROMETHEUS_URL=https://<prometheus-host>
   export LOAD_PROMETHEUS_TOKEN="<read-only-token-from-secret-store>"
   export LOAD_QUEUE_QUERY='sum(celery_queue_length{environment="staging"})'
   export LOAD_DB_RATIO_QUERY='sum(pg_stat_activity_count{datname=~".*load.*"}) / sum(pg_max_connections)'
   export LOAD_MEMORY_QUERY='sum(process_resident_memory_bytes{job=~".*plane-api.*"})'
   ```

3. Record the deployment identity before the run: image digests, Postgres version, commit SHA, worker count, database `max_connections`, and the workload shape. Store it in the evidence bundle alongside `k6-summary.json`.

## 2. Scenarios

| Scenario  | Load shape                            | Duration | Purpose                                                  |
| --------- | ------------------------------------- | -------- | -------------------------------------------------------- |
| `smoke`   | 1 VU                                  | 1 min    | Every endpoint family returns 2xx; release-gate gate.    |
| `average` | 15 VUs                                | 20 min   | Primary performance acceptance run.                      |
| `stress`  | 50 VUs                                | 10 min   | Find the knee; not a pass/fail substitute for `average`. |
| `spike`   | 5 → 50 in 30 s, hold 2 min, back to 5 | ~3 min   | Recovery behaviour.                                      |
| `soak`    | 15 VUs                                | 2 h      | Memory, connection and queue leaks.                      |

Traffic mix is enforced by `load-tests/runner.js`: **70% reads** (list, detail, board, cycle, analytics), **20% writes** (create/update, comment, transition), **10% admin/report/export**. Endpoint tags are exactly `list`, `detail`, `board`, `cycle`, `analytics`, `create_update`, `transition`, `admin_report_export`.

## 3. Capturing evidence

### 3.1 k6 summary JSON

```bash
mkdir -p load-tests/results
k6 run load-tests/runner.js \
  --env LOAD_SCENARIO=average \
  --env LOAD_SUMMARY_PATH=load-tests/results/k6-average.json \
  2>&1 | tee load-tests/results/k6-average.log
```

The runner writes a threshold-by-threshold summary JSON. It never writes the service token or any secret to stdout or to that file.

### 3.2 Grafana / Prometheus snapshots

Capture PNG snapshots (or exported panels) **before, during, and 5 minutes after** the run for:

- API request rate, error rate, and p95/p99 by endpoint tag.
- Worker queue depth and oldest queued job age.
- Database active connections vs. `max_connections` (must stay **< 80%**).
- API/worker process resident memory (soak must show no monotonic growth).
- postgres_commit latency and lock waits.

Save the snapshots and the raw PromQL responses as `load-tests/results/grafana-<scenario>-<timestamp>/`.

### 3.3 Slow query log and EXPLAIN plans

On the dedicated Postgres instance (not production):

```sql
ALTER DATABASE plane SET log_min_duration_statement = '200ms';
ALTER DATABASE plane SET log_statement = 'none';
SELECT pg_reload_conf();
```

After the run, extract the slowest statements and normalize literals before ranking:

```bash
docker compose exec -T plane-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT calls, round(total_exec_time::numeric, 1) AS total_ms, query \
      FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;"
```

For each of the **top 5 slow queries**, save the plan to `load-tests/results/explain-<n>.txt`:

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE) <normalized query with representative parameters>;
```

Restore `log_min_duration_statement` to its previous value afterwards. Never copy production query text, parameters, or user data into a ticket or artifact.

### 3.4 Worker queue drain check

With observability configured, the runner samples queue depth and fails the `pln026_infra_gate_failures` threshold if the queue is still above its pre-run baseline after five minutes. Nightly, release and reusable-call staging runs must configure `LOAD_PROMETHEUS_URL`, `LOAD_QUEUE_QUERY`, `LOAD_DB_RATIO_QUERY` and `LOAD_MEMORY_QUERY`; CI preflight fails the run when any is missing, so infrastructure gates are never silently skipped. Only an explicit `LOAD_ENV=local` run may omit observability: attach the Grafana queue snapshot manually and state explicitly that the automated gate was not exercised.

## 4. Threshold policy (non-negotiable)

| Gate                 | Threshold                                                                                           |
| -------------------- | --------------------------------------------------------------------------------------------------- |
| HTTP failures        | `http_req_failed < 0.5%`                                                                            |
| p95 list             | `< 400 ms`                                                                                          |
| p95 detail           | `< 300 ms`                                                                                          |
| p95 board            | `< 800 ms`                                                                                          |
| p95 analytics        | `< 1200 ms`                                                                                         |
| p95 create/update    | `< 500 ms`                                                                                          |
| p95 transition       | `< 400 ms`                                                                                          |
| p99                  | `< 3x p95` for every tagged endpoint (cycle and report export use the read/analytics class budgets) |
| Average scenario 5xx | `0`                                                                                                 |
| Worker queue         | back to baseline within `5 min`                                                                     |
| DB connections       | `< 80%` of `max_connections`                                                                        |
| Soak memory          | stable; no monotonic growth                                                                         |

**No silent loosening.** The thresholds above are fixed and must not be weakened in `load-tests/runner.js`, `load-tests/verify-summary.js` or `scripts/pln026/performance-diff.js`. Any unmet threshold requires dated written acceptance in the register below **before release**, with a named approver and a linked decision. Approval remains `not recorded` until that acceptance is actually signed.

## 5. Before/after table

Fill this in for every optimization. If a field is not measured, write `not measured` — do not infer or omit it.

| Metric                       | Before       | After | Threshold           | Evidence         | Status  |
| ---------------------------- | ------------ | ----- | ------------------- | ---------------- | ------- |
| p95 list (ms)                | not measured |       | < 400               | `k6-*.json`      | pending |
| p95 detail (ms)              | not measured |       | < 300               | `k6-*.json`      | pending |
| p95 board (ms)               | not measured |       | < 800               | `k6-*.json`      | pending |
| p95 analytics (ms)           | not measured |       | < 1200              | `k6-*.json`      | pending |
| p95 create/update (ms)       | not measured |       | < 500               | `k6-*.json`      | pending |
| p95 transition (ms)          | not measured |       | < 400               | `k6-*.json`      | pending |
| p99/p95 ratio (all tags)     | not measured |       | < 3                 | `k6-*.json`      | pending |
| 5xx count (average)          | not measured |       | 0                   | `k6-*.json`      | pending |
| Top slow query #1 total time | not measured |       | improved            | `explain-01.txt` | pending |
| Top slow query #2 total time | not measured |       | improved            | `explain-02.txt` | pending |
| Top slow query #3 total time | not measured |       | improved            | `explain-03.txt` | pending |
| Top slow query #4 total time | not measured |       | improved            | `explain-04.txt` | pending |
| Top slow query #5 total time | not measured |       | improved            | `explain-05.txt` | pending |
| Queue drain (min)            | not measured |       | < 5                 | Grafana snapshot | pending |
| DB connection peak (% max)   | not measured |       | < 80%               | Grafana snapshot | pending |
| Soak RSS growth              | not measured |       | no monotonic growth | Grafana snapshot | pending |

### Written acceptance register

| Threshold           | Reason for acceptance | Approver     | Date         | Linked decision |
| ------------------- | --------------------- | ------------ | ------------ | --------------- |
| any unmet threshold | not recorded          | not recorded | not recorded | not recorded    |

## 6. Evidence register

Expected evidence paths are `load-tests/results/k6-<scenario>.json`, `load-tests/results/grafana-<scenario>-<timestamp>/`, `load-tests/results/explain-01.txt` through `load-tests/results/explain-05.txt`, `load-tests/results/performance-diff.md` and `e2e/playwright-report/index.html`. No measurements are invented; every field stays `not recorded` until a real run is attached.

| Run ID       | Date         | Commit SHA   | Environment  | k6 summary path | Grafana path | EXPLAIN path(s) | Playwright report path | Gate result  | Approver     |
| ------------ | ------------ | ------------ | ------------ | --------------- | ------------ | --------------- | ---------------------- | ------------ | ------------ |
| not recorded | not recorded | not recorded | not recorded | not recorded    | not recorded | not recorded    | not recorded           | not recorded | not recorded |
| not recorded | not recorded | not recorded | not recorded | not recorded    | not recorded | not recorded    | not recorded           | not recorded | not recorded |
| not recorded | not recorded | not recorded | not recorded | not recorded    | not recorded | not recorded    | not recorded           | not recorded | not recorded |

## 7. Artifact layout

```text
load-tests/results/
  k6-<scenario>.json          # full summary, thresholds and metric values
  k6-<scenario>.log
  grafana-<scenario>-<ts>/    # PNG snapshots + raw PromQL responses
  explain-01.txt ... explain-05.txt
  performance-diff.md         # before/after table for this run
```

The nightly pipeline uploads these together with the Playwright HTML report, traces, and screenshots. The release gate requires full E2E green, `smoke` load green, and no open P0/P1 bugs.

## 8. Flake tracking

The nightly job aggregates Playwright `results.json` from all shards and the previous 14 days of artifacts into a dashboard (`flake-dashboard.html`) and `quarantine.json`. A scenario with **more than two failures in 14 days** is quarantined and must be fixed within one week. Quarantine is recorded as metadata; it is not a license to skip role, workflow, or isolation scenarios on a release branch.
