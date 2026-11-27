// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

/**
 * PLN-026 load suite (k6, ES module).
 *
 * Primary configuration (see e2e/README.md and docs/testing/performance.md):
 *   LOAD_SCENARIO           smoke | average | stress | spike | soak
 *   LOAD_BASE_URL           http(s) base URL of a dedicated local/staging deployment
 *   LOAD_SERVICE_TOKEN      service token scoped to the load project (secret; never logged)
 *   LOAD_ENV                local | staging (production is always refused)
 *   LOAD_PROJECT_ID         UUID of the dedicated project created by `seed_load`
 *   LOAD_ALLOW_LOCAL_STAGING=1  explicit operator opt-in for load generation
 *
 * Optional observability configuration:
 *   LOAD_WORKSPACE_SLUG     defaults to "load"
 *   LOAD_PROMETHEUS_URL     base URL of a Prometheus-compatible HTTP API
 *   LOAD_PROMETHEUS_TOKEN   bearer token for that API (secret; never logged)
 *   LOAD_QUEUE_QUERY        PromQL returning current worker queue depth
 *   LOAD_DB_RATIO_QUERY     PromQL returning active_db_connections / max_db_connections
 *   LOAD_MEMORY_QUERY       PromQL returning API worker RSS in bytes
 *   LOAD_MEMORY_GROWTH_MAX  allowed RSS growth during soak; strict positive finite
 *                           decimal number (default 0.2 = 20%). Zero, blank,
 *                           NaN, Infinity and non-numeric values are rejected.
 *   LOAD_SUMMARY_PATH       k6 summary JSON path (default k6-summary.json)
 *
 * Thresholds are intentionally strict. Do not relax them to make a run green;
 * fix the product or obtain written acceptance (see docs/testing/performance.md).
 */

import http from "k6/http";
import { check, sleep } from "k6";
import exec from "k6/execution";
import { Counter, Gauge } from "k6/metrics";

const SCENARIO_DEFINITIONS = Object.freeze({
  smoke: { executor: "constant-vus", vus: 1, duration: "1m" },
  average: { executor: "constant-vus", vus: 15, duration: "20m" },
  stress: { executor: "constant-vus", vus: 50, duration: "10m" },
  spike: {
    executor: "ramping-vus",
    startVUs: 5,
    stages: [
      { duration: "30s", target: 50 },
      { duration: "2m", target: 50 },
      { duration: "30s", target: 5 },
    ],
    gracefulRampDown: "30s",
  },
  soak: { executor: "constant-vus", vus: 15, duration: "2h" },
});

// p99 ceilings are exactly 3x the corresponding p95 ceilings.
const ENDPOINT_BUDGETS = Object.freeze({
  list: { p95: 400, p99: 1200 },
  detail: { p95: 300, p99: 900 },
  board: { p95: 800, p99: 2400 },
  cycle: { p95: 800, p99: 2400 },
  analytics: { p95: 1200, p99: 3600 },
  create_update: { p95: 500, p99: 1500 },
  transition: { p95: 400, p99: 1200 },
  // Admin/report export uses the analytics-class read budget.
  admin_report_export: { p95: 1200, p99: 3600 },
});

// 70% reads / 20% writes / 10% admin-report-export.
const OPERATION_WEIGHTS = Object.freeze([
  { weight: 25, endpoint: "list", operation: "list" },
  { weight: 20, endpoint: "detail", operation: "detail" },
  { weight: 10, endpoint: "board", operation: "board" },
  { weight: 10, endpoint: "cycle", operation: "cycle" },
  { weight: 5, endpoint: "analytics", operation: "analytics" },
  { weight: 10, endpoint: "create_update", operation: "create_or_update" },
  { weight: 5, endpoint: "create_update", operation: "comment" },
  { weight: 5, endpoint: "transition", operation: "transition" },
  { weight: 10, endpoint: "admin_report_export", operation: "admin_report_export" },
]);

const serverErrors = new Counter("pln026_server_errors");
const requestOutcomes = new Counter("pln026_request_outcomes");
const infraGateFailures = new Counter("pln026_infra_gate_failures");
const workerQueueDepth = new Gauge("pln026_worker_queue_depth");
const dbConnectionRatio = new Gauge("pln026_db_connection_ratio");
const apiMemoryBytes = new Gauge("pln026_api_memory_bytes");

function configError(message) {
  throw new Error(`PLN-026 load configuration error: ${message}`);
}

function envValue(names, fallback = "") {
  const candidates = Array.isArray(names) ? names : [names];
  for (const name of candidates) {
    const value = __ENV[name];
    if (value !== undefined && value !== null && String(value) !== "") return String(value);
  }
  return fallback;
}

function isTrue(value) {
  return ["1", "true", "yes", "on"].includes(
    String(value ?? "")
      .trim()
      .toLowerCase()
  );
}

function parseScenario() {
  const scenario = envValue(["LOAD_SCENARIO", "SCENARIO"]).trim().toLowerCase();
  if (!scenario) {
    configError("LOAD_SCENARIO is required (smoke, average, stress, spike, soak).");
  }
  if (!Object.prototype.hasOwnProperty.call(SCENARIO_DEFINITIONS, scenario)) {
    configError(`unknown LOAD_SCENARIO '${scenario}'.`);
  }
  return scenario;
}

function parseEnvironment() {
  const environment = envValue(["LOAD_ENV", "E2E_ENV"], "local").trim().toLowerCase();
  if (!["local", "staging", "production"].includes(environment)) {
    configError("LOAD_ENV must be local, staging, or production.");
  }
  // Load generation is never allowed against production, even with an opt-in.
  if (environment === "production") {
    configError("Refusing to generate load against production. Use the read-only production E2E smoke subset instead.");
  }
  if (!isTrue(envValue("LOAD_ALLOW_LOCAL_STAGING"))) {
    configError(
      "Refusing to run without explicit opt-in. Set LOAD_ALLOW_LOCAL_STAGING=1 only on a dedicated local/staging deployment."
    );
  }
  return environment;
}

function parseBaseUrl(environment) {
  const raw = envValue(["LOAD_BASE_URL", "E2E_LOAD_BASE_URL"], "http://127.0.0.1:3000");
  let parsed;
  try {
    parsed = new URL(raw);
  } catch (_) {
    configError("LOAD_BASE_URL must be an absolute http(s) URL.");
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    configError("LOAD_BASE_URL must use http or https.");
  }
  if (parsed.username || parsed.password) {
    configError("LOAD_BASE_URL must not embed credentials.");
  }
  const host = parsed.hostname.toLowerCase();
  const productionLike =
    host === "prod" ||
    host.startsWith("prod.") ||
    host.includes(".prod.") ||
    host.includes("production") ||
    host.endsWith(".live") ||
    host === "live";
  if (productionLike) {
    configError("Refusing to target a production-looking host with the load suite.");
  }
  const loopback = ["localhost", "127.0.0.1", "::1", "[::1]"].includes(host);
  if (environment === "local" && !loopback) {
    configError("LOAD_ENV=local requires a loopback LOAD_BASE_URL; use LOAD_ENV=staging for remote targets.");
  }
  if (environment === "staging" && loopback) {
    configError("LOAD_ENV=staging requires a remote staging URL; use LOAD_ENV=local for a local compose stack.");
  }
  return `${parsed.origin}${parsed.pathname.replace(/\/$/, "")}`;
}

function parseProjectId() {
  const projectId = envValue(["LOAD_PROJECT_ID", "E2E_LOAD_PROJECT_ID"]).trim();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(projectId)) {
    configError("LOAD_PROJECT_ID must be the UUID printed by `python manage.py seed_load`.");
  }
  return projectId;
}

function parseToken() {
  const token = envValue(["LOAD_SERVICE_TOKEN", "E2E_LOAD_API_TOKEN"]).trim();
  if (!token) {
    configError("LOAD_SERVICE_TOKEN is required and must be scoped to the dedicated load project.");
  }
  // The value is only used in request headers; it is never logged or serialized.
  return token;
}

const MEMORY_GROWTH_MAX_ERROR =
  "LOAD_MEMORY_GROWTH_MAX must be a strictly positive finite decimal number (for example 0.2 for 20%); zero, blank, NaN, Infinity and non-numeric values are rejected.";

function parseMemoryGrowthMax() {
  const raw = envValue("LOAD_MEMORY_GROWTH_MAX", "0.2").trim();
  if (!/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw)) {
    configError(MEMORY_GROWTH_MAX_ERROR);
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    configError(MEMORY_GROWTH_MAX_ERROR);
  }
  return parsed;
}

const scenarioName = parseScenario();
const environment = parseEnvironment();
const baseUrl = parseBaseUrl(environment);
const projectId = parseProjectId();
const serviceToken = parseToken();
const workspaceSlug = envValue(["LOAD_WORKSPACE_SLUG", "E2E_LOAD_WORKSPACE_SLUG"], "load").trim() || "load";
const summaryPath = envValue("LOAD_SUMMARY_PATH", "k6-summary.json");
const prometheusUrl = envValue("LOAD_PROMETHEUS_URL").replace(/\/$/, "");
const prometheusToken = envValue("LOAD_PROMETHEUS_TOKEN");
const queueQuery = envValue("LOAD_QUEUE_QUERY");
const dbRatioQuery = envValue("LOAD_DB_RATIO_QUERY");
const memoryQuery = envValue("LOAD_MEMORY_QUERY");
const memoryGrowthMax = parseMemoryGrowthMax();

const projectBase = `/api/v1/workspaces/${encodeURIComponent(workspaceSlug)}/projects/${projectId}`;
const appBase = `/api/workspaces/${encodeURIComponent(workspaceSlug)}/projects/${projectId}`;

const thresholdDefinitions = {
  http_req_failed: ["rate<0.005"],
  "pln026_server_errors{scenario:average}": ["count===0"],
  pln026_infra_gate_failures: ["count===0"],
};
for (const [endpoint, budget] of Object.entries(ENDPOINT_BUDGETS)) {
  thresholdDefinitions[`http_req_duration{endpoint:${endpoint}}`] = [`p(95)<${budget.p95}`, `p(99)<${budget.p99}`];
}

export const options = {
  thresholds: thresholdDefinitions,
  scenarios: { [scenarioName]: SCENARIO_DEFINITIONS[scenarioName] },
  tags: { suite: "PLN-026", environment, scenario: scenarioName },
};

function authHeaders() {
  return {
    Accept: "application/json, text/csv;q=0.9, */*;q=0.8",
    "Content-Type": "application/json",
    "X-Api-Key": serviceToken,
  };
}

function callApi(method, path, endpoint, operation, body) {
  const params = {
    headers: authHeaders(),
    tags: { endpoint, operation, scenario: scenarioName },
  };
  const payload = body === undefined ? null : JSON.stringify(body);
  const response = http.request(method, `${baseUrl}${path}`, payload, params);
  const ok = check(response, {
    "response is 2xx": (r) => r.status >= 200 && r.status < 300,
  });
  requestOutcomes.add(1, { endpoint, operation, outcome: ok ? "ok" : "failed" });
  if (response.status >= 500) {
    serverErrors.add(1, { endpoint, operation, scenario: scenarioName, status: String(response.status) });
  }
  return response;
}

function jsonArray(response) {
  try {
    const parsed = JSON.parse(response.body);
    if (Array.isArray(parsed)) return parsed;
    if (Array.isArray(parsed.results)) return parsed.results;
  } catch (_) {
    // Fixture discovery is best-effort; thresholds will report the failure.
  }
  return [];
}

function prometheusScalar(query, probe) {
  if (!prometheusUrl || !query) return null;
  const params = {
    headers: prometheusToken
      ? { Accept: "application/json", Authorization: `Bearer ${prometheusToken}` }
      : { Accept: "application/json" },
    tags: { probe, scenario: scenarioName },
  };
  const url = `${prometheusUrl}/api/v1/query?query=${encodeURIComponent(query)}`;
  const response = http.get(url, params);
  if (response.status !== 200) return null;
  try {
    const payload = JSON.parse(response.body);
    const sample = payload?.data?.result?.[0]?.value?.[1];
    const value = Number(sample);
    return Number.isFinite(value) ? value : null;
  } catch (_) {
    return null;
  }
}

function sampleInfrastructure(baseline) {
  const queue = prometheusScalar(queueQuery, "worker_queue");
  if (queue !== null) {
    workerQueueDepth.add(queue, { scenario: scenarioName });
    // A load run must not leave the queue above its pre-run baseline.
    if (queue > baseline.queue + 1) {
      infraGateFailures.add(1, { scenario: scenarioName, gate: "worker_queue" });
    }
  }
  const ratio = prometheusScalar(dbRatioQuery, "db_connections");
  if (ratio !== null) {
    dbConnectionRatio.add(ratio, { scenario: scenarioName });
    if (ratio >= 0.8) {
      infraGateFailures.add(1, { scenario: scenarioName, gate: "db_connections" });
    }
  }
  const memory = prometheusScalar(memoryQuery, "api_memory");
  if (memory !== null) {
    apiMemoryBytes.add(memory, { scenario: scenarioName });
    if (baseline.memory > 0 && memory > baseline.memory * (1 + memoryGrowthMax)) {
      infraGateFailures.add(1, { scenario: scenarioName, gate: "memory_growth" });
    }
  }
}

export function setup() {
  const list = callApi(
    "GET",
    `${projectBase}/work-items/?per_page=50&order_by=-created_at`,
    "list",
    "fixture_discovery"
  );
  const states = callApi("GET", `${projectBase}/states/`, "list", "fixture_discovery");
  const cycles = callApi("GET", `${projectBase}/cycles/?per_page=20`, "cycle", "fixture_discovery");

  const stateRows = jsonArray(states);
  const stateId = (group) => {
    const state = stateRows.find((row) => row.group === group && row.id);
    return state ? String(state.id) : null;
  };
  const fixtures = {
    issueIds: jsonArray(list)
      .map((row) => String(row.id))
      .filter(Boolean)
      .slice(0, 50),
    stateIds: {
      started: stateId("started"),
      completed: stateId("completed"),
    },
    cycleIds: jsonArray(cycles)
      .map((row) => String(row.id))
      .filter(Boolean)
      .slice(0, 20),
    baseline: {
      queue: prometheusScalar(queueQuery, "worker_queue_baseline") ?? 0,
      memory: prometheusScalar(memoryQuery, "api_memory_baseline") ?? 0,
    },
  };
  if (fixtures.issueIds.length === 0) {
    configError("Fixture discovery returned no work items. Run `pnpm seed:load` before the load suite.");
  }
  return fixtures;
}

function pickOperation() {
  const roll = Math.random() * 100;
  let cumulative = 0;
  for (const spec of OPERATION_WEIGHTS) {
    cumulative += spec.weight;
    if (roll < cumulative) return spec;
  }
  return OPERATION_WEIGHTS[OPERATION_WEIGHTS.length - 1];
}

function chooseItemId(fixtures, iteration) {
  const index = (exec.vu.idInTest - 1 + iteration) % fixtures.issueIds.length;
  return fixtures.issueIds[index];
}

function listPath() {
  return `${projectBase}/work-items/?per_page=50&order_by=-created_at`;
}

function detailPath(itemId) {
  return `${projectBase}/work-items/${encodeURIComponent(itemId)}/`;
}

function boardPath() {
  // The app-surface board payload groups the same work-item set by state.
  return `${appBase}/issues/?per_page=50&group_by=state`;
}

function cyclePath(fixtures, iteration) {
  const cycleId = fixtures.cycleIds[iteration % Math.max(fixtures.cycleIds.length, 1)];
  if (!cycleId) return `${projectBase}/cycles/?per_page=20`;
  return `${projectBase}/cycles/${encodeURIComponent(cycleId)}/cycle-issues/?per_page=50`;
}

function analyticsPath() {
  return `${appBase}/advance-analytics/`;
}

function adminExportPath() {
  return `${appBase}/reports/bugs-by-state/export/`;
}

export default function (fixtures) {
  const spec = pickOperation();
  const iteration = exec.scenario.iterationInTest ?? 0;
  const itemId = chooseItemId(fixtures, iteration);
  const runId = `${exec.instance?.currentTestRunId || "local"}-${exec.vu.idInTest}-${iteration}`;

  switch (spec.operation) {
    case "list":
      callApi("GET", listPath(), spec.endpoint, spec.operation);
      break;
    case "detail":
      callApi("GET", detailPath(itemId), spec.endpoint, spec.operation);
      break;
    case "board":
      callApi("GET", boardPath(), spec.endpoint, spec.operation);
      break;
    case "cycle":
      callApi("GET", cyclePath(fixtures, iteration), spec.endpoint, spec.operation);
      break;
    case "analytics":
      callApi("GET", analyticsPath(), spec.endpoint, spec.operation);
      break;
    case "create_or_update": {
      if (iteration % 2 === 0) {
        callApi("POST", `${projectBase}/work-items/`, spec.endpoint, "create", {
          name: `PLN-026 load item ${runId}`,
          description_html: "<p>Deterministic PLN-026 load-test item.</p>",
          priority: "none",
        });
      } else {
        callApi("PATCH", detailPath(itemId), spec.endpoint, "update", { name: `PLN-026 load item ${runId}` });
      }
      break;
    }
    case "comment":
      callApi("POST", `${projectBase}/work-items/${encodeURIComponent(itemId)}/comments/`, spec.endpoint, "comment", {
        comment_html: "<p>PLN-026 load-test comment.</p>",
      });
      break;
    case "transition": {
      const stateId = fixtures.stateIds[iteration % 2 === 0 ? "started" : "completed"];
      if (!stateId) {
        configError("Seeded load project has no started/completed state; cannot exercise transitions.");
      }
      callApi("PATCH", detailPath(itemId), spec.endpoint, "transition", { state_id: stateId });
      break;
    }
    case "admin_report_export":
      callApi("GET", adminExportPath(), spec.endpoint, "export");
      break;
    default:
      configError(`unsupported operation '${spec.operation}'.`);
  }

  // Probe infrastructure at a low cadence so the suite itself stays read-heavy.
  if ((iteration + exec.vu.idInTest) % 50 === 0) {
    sampleInfrastructure(fixtures.baseline);
  }
  sleep(1);
}

export function teardown(fixtures) {
  // Wait up to five minutes for the worker queue to return to its pre-run
  // baseline. Probes are skipped when observability is not configured; attach
  // the Grafana/Prometheus snapshot manually in that case.
  if (!prometheusUrl || !queueQuery) return;
  const deadline = Date.now() + 5 * 60 * 1000;
  let queue = prometheusScalar(queueQuery, "worker_queue_final");
  while (queue !== null && queue > fixtures.baseline.queue + 1 && Date.now() < deadline) {
    sleep(15);
    queue = prometheusScalar(queueQuery, "worker_queue_final");
  }
  if (queue !== null) {
    workerQueueDepth.add(queue, { scenario: scenarioName, phase: "final" });
    if (queue > fixtures.baseline.queue + 1) {
      infraGateFailures.add(1, { scenario: scenarioName, gate: "worker_queue_drain" });
    }
  }
}

function summarizeMetric(values) {
  const summary = {};
  for (const key of Object.keys(values || {})) {
    if (["p(95)", "p(99)", "avg", "max", "rate", "count"].includes(key)) {
      summary[key] = values[key];
    }
  }
  return summary;
}

export function handleSummary(data) {
  const metrics = {};
  const thresholds = {};
  for (const [name, metric] of Object.entries(data.metrics || {})) {
    metrics[name] = summarizeMetric(metric.values);
    if (metric.thresholds) {
      thresholds[name] = Object.fromEntries(
        Object.entries(metric.thresholds).map(([expression, result]) => [expression, result.ok])
      );
    }
  }
  const summary = {
    generated_at: new Date().toISOString(),
    suite: "PLN-026",
    scenario: scenarioName,
    environment,
    base_url: baseUrl,
    project_id: projectId,
    endpoint_budgets_ms: ENDPOINT_BUDGETS,
    thresholds,
    metrics,
    notes: [
      "Service token is never written to the summary or stdout.",
      "Infrastructure gates require supplied Prometheus configuration; otherwise attach Grafana snapshots manually.",
    ],
  };
  const lines = [
    `PLN-026 load summary - scenario=${scenarioName} environment=${environment}`,
    ...Object.entries(thresholds).flatMap(([metric, results]) =>
      Object.entries(results).map(([expression, ok]) => `  ${ok ? "PASS" : "FAIL"} ${metric} ${expression}`)
    ),
    `Full JSON: ${summaryPath}`,
  ];
  return {
    [summaryPath]: JSON.stringify(summary, null, 2),
    stdout: `${lines.join("\n")}\n`,
  };
}
