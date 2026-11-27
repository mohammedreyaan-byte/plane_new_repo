// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

/**
 * Verify a PLN-026 k6 summary and render the performance-diff evidence file.
 *
 * Budgets and thresholds are owned by this verifier (mirroring runner.js).
 * `payload.endpoint_budgets_ms` is never trusted: when present it must match
 * the canonical budgets exactly, otherwise verification fails. Thresholds are
 * stored as `payload.thresholds[metric][expression] -> boolean`; older k6
 * exports may wrap that boolean in `{ ok }`. Both shapes are accepted, but the
 * threshold name/expression set must be exactly the canonical PLN-026 set.
 *
 * Actual metric values are recomputed against the canonical budgets, and the
 * p99/p95 ratio is recomputed rather than inferred from threshold booleans.
 * A missing summary, an unexpected threshold, or an invalid p99/p95 ratio
 * always fails. Secret values are never read, logged, or rendered here.
 */

import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

export const RATIO_LIMIT = 3;
export const FAILURE_RATE_LIMIT = 0.005;
export const FAILURE_RATE_EXPRESSION = "rate<0.005";
export const ERROR_COUNT_EXPRESSION = "count===0";
export const INFRA_GATE_METRIC = "pln026_infra_gate_failures";
export const SERVER_ERROR_METRIC = "pln026_server_errors";
export const AVERAGE_SERVER_ERROR_METRIC = "pln026_server_errors{scenario:average}";
export const ZERO_5XX_SCENARIOS = Object.freeze(["average"]);

// Canonical source of truth. Never derived from the candidate summary.
export const CANONICAL_ENDPOINT_BUDGETS_MS = Object.freeze({
  list: { p95: 400, p99: 1200 },
  detail: { p95: 300, p99: 900 },
  board: { p95: 800, p99: 2400 },
  cycle: { p95: 800, p99: 2400 },
  analytics: { p95: 1200, p99: 3600 },
  create_update: { p95: 500, p99: 1500 },
  transition: { p95: 400, p99: 1200 },
  admin_report_export: { p95: 1200, p99: 3600 },
});

for (const [endpoint, budget] of Object.entries(CANONICAL_ENDPOINT_BUDGETS_MS)) {
  if (budget.p99 !== budget.p95 * RATIO_LIMIT) {
    throw new Error(`PLN-026 canonical budget invariant broken for ${endpoint}: p99 must be exactly 3x p95.`);
  }
}

function endpointMetricName(endpoint) {
  return `http_req_duration{endpoint:${endpoint}}`;
}

// k6 has no cross-percentile threshold expression, so the p99/p95 gate is the
// canonical p99 ceiling (exactly 3x the p95 ceiling) plus the recomputed ratio
// check below. Both are mandatory evidence; the expressions must be exact.
export const CANONICAL_THRESHOLDS = Object.freeze({
  http_req_failed: Object.freeze([FAILURE_RATE_EXPRESSION]),
  [AVERAGE_SERVER_ERROR_METRIC]: Object.freeze([ERROR_COUNT_EXPRESSION]),
  ...Object.fromEntries(
    Object.entries(CANONICAL_ENDPOINT_BUDGETS_MS).map(([endpoint, budget]) => [
      endpointMetricName(endpoint),
      Object.freeze([`p(95)<${budget.p95}`, `p(99)<${budget.p99}`]),
    ])
  ),
});

// These are canonical too, but only become required when the corresponding
// metric or threshold is present in the summary (infra telemetry is optional).
export const OPTIONAL_CANONICAL_THRESHOLDS = Object.freeze({
  [INFRA_GATE_METRIC]: Object.freeze([ERROR_COUNT_EXPRESSION]),
  [SERVER_ERROR_METRIC]: Object.freeze([ERROR_COUNT_EXPRESSION]),
});

function thresholdOk(value) {
  return typeof value === "object" && value !== null ? value.ok === true : value === true;
}

function metricNumber(metrics, metricName, key) {
  const metric = metrics?.[metricName];
  if (!metric || typeof metric !== "object" || Array.isArray(metric)) return null;
  const source =
    metric.values && typeof metric.values === "object" && !Array.isArray(metric.values) ? metric.values : metric;
  const value = source[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function validateBudgetManifest(payload, errors) {
  if (!Object.prototype.hasOwnProperty.call(payload, "endpoint_budgets_ms")) return;
  const supplied = payload.endpoint_budgets_ms;
  if (!supplied || typeof supplied !== "object" || Array.isArray(supplied)) {
    errors.push("endpoint_budgets_ms must be an object matching the canonical budgets.");
    return;
  }
  const canonicalEndpoints = Object.keys(CANONICAL_ENDPOINT_BUDGETS_MS).toSorted();
  const suppliedEndpoints = Object.keys(supplied).toSorted();
  if (suppliedEndpoints.join("\u0000") !== canonicalEndpoints.join("\u0000")) {
    errors.push("endpoint_budgets_ms endpoint set does not match the canonical endpoint set.");
  }
  for (const endpoint of canonicalEndpoints) {
    const budget = supplied[endpoint];
    const canonical = CANONICAL_ENDPOINT_BUDGETS_MS[endpoint];
    if (!budget || typeof budget !== "object" || Array.isArray(budget)) {
      errors.push(`Candidate-supplied budget for ${endpoint} is missing or malformed.`);
      continue;
    }
    if (Object.keys(budget).toSorted().join(",") !== "p95,p99") {
      errors.push(`Candidate-supplied budget for ${endpoint} has unexpected fields; only p95 and p99 are canonical.`);
    }
    if (budget.p95 !== canonical.p95 || budget.p99 !== canonical.p99) {
      errors.push(
        `Candidate-supplied budget for ${endpoint} differs from the canonical budget (p95<${canonical.p95}, p99<${canonical.p99}).`
      );
    }
  }
}

function validateThresholds(payload, errors, thresholdRows) {
  const thresholds = payload.thresholds;
  const metrics = payload.metrics && typeof payload.metrics === "object" ? payload.metrics : {};
  if (!thresholds || typeof thresholds !== "object" || Array.isArray(thresholds)) {
    errors.push("The k6 summary contains no threshold results.");
    for (const [metric, expressions] of Object.entries(CANONICAL_THRESHOLDS)) {
      for (const expression of expressions) {
        thresholdRows.push({ metric, expression, ok: false, expected: true });
      }
    }
    return;
  }

  const allowedEntries = { ...CANONICAL_THRESHOLDS };
  const required = { ...CANONICAL_THRESHOLDS };
  for (const [metric, expressions] of Object.entries(OPTIONAL_CANONICAL_THRESHOLDS)) {
    if (
      !Object.prototype.hasOwnProperty.call(thresholds, metric) &&
      !Object.prototype.hasOwnProperty.call(metrics, metric)
    ) {
      continue;
    }
    allowedEntries[metric] = expressions;
    // The infra gate is expected whenever its metric is reported. A plain
    // pln026_server_errors threshold is canonical if supplied, but runner.js
    // defines the tagged average-scenario gate, so it is not required here.
    if (metric === INFRA_GATE_METRIC) required[metric] = expressions;
  }
  const allowed = new Map(
    Object.entries(allowedEntries).map(([metric, expressions]) => [metric, new Set(expressions)])
  );
  const seen = new Map();

  for (const [metric, entries] of Object.entries(thresholds).toSorted(([a], [b]) => a.localeCompare(b))) {
    if (!entries || typeof entries !== "object" || Array.isArray(entries)) {
      errors.push(`Threshold entry for ${metric} is not an object.`);
      continue;
    }
    for (const expression of Object.keys(entries).toSorted()) {
      const ok = thresholdOk(entries[expression]);
      const expected = allowed.has(metric) && allowed.get(metric).has(expression);
      if (!expected) {
        errors.push(
          `Unexpected threshold ${metric} ${expression}; PLN-026 evidence accepts only canonical threshold names and expressions.`
        );
      }
      if (!ok) errors.push(`Threshold failed: ${metric} ${expression}`);
      thresholdRows.push({ metric, expression, ok: ok && expected, expected });
      if (!seen.has(metric)) seen.set(metric, new Set());
      seen.get(metric).add(expression);
    }
  }

  for (const [metric, expressions] of Object.entries(required)) {
    for (const expression of expressions) {
      if (!seen.get(metric)?.has(expression)) {
        errors.push(`Missing canonical threshold: ${metric} ${expression}`);
        thresholdRows.push({ metric, expression, ok: false, expected: true, missing: true });
      }
    }
  }
}

function verifyActualMetrics(payload, errors, ratioRows) {
  const metrics = payload.metrics && typeof payload.metrics === "object" ? payload.metrics : {};

  for (const [endpoint, budget] of Object.entries(CANONICAL_ENDPOINT_BUDGETS_MS).toSorted(([a], [b]) =>
    a.localeCompare(b)
  )) {
    const metricName = endpointMetricName(endpoint);
    const p95 = metricNumber(metrics, metricName, "p(95)");
    const p99 = metricNumber(metrics, metricName, "p(99)");
    if (p95 === null || p99 === null) {
      errors.push(`Missing or non-numeric p95/p99 samples for ${endpoint}; cannot verify canonical budgets.`);
      continue;
    }
    if (p95 <= 0 || p99 <= 0) {
      errors.push(`p95/p99 samples for ${endpoint} must be positive numbers; cannot verify the p99/p95 ratio.`);
      continue;
    }
    if (p95 >= budget.p95) {
      errors.push(`p95 for ${endpoint} is ${p95}; the canonical budget requires <${budget.p95}.`);
    }
    if (p99 >= budget.p99) {
      errors.push(`p99 for ${endpoint} is ${p99}; the canonical 3x budget requires <${budget.p99}.`);
    }
    const ratio = p99 / p95;
    const expectedCeiling = budget.p95 * RATIO_LIMIT;
    if (!Number.isFinite(ratio) || ratio >= RATIO_LIMIT || p99 >= expectedCeiling) {
      errors.push(`p99/p95 ratio for ${endpoint} is ${ratio.toFixed(3)}; the ceiling is <${RATIO_LIMIT}.`);
    }
    ratioRows.push({
      endpoint,
      p95,
      p99,
      ratio,
      expectedCeiling,
      p95Budget: budget.p95,
      p99Budget: budget.p99,
      p95WithinBudget: p95 < budget.p95,
      p99WithinBudget: p99 < budget.p99,
      ratioWithinLimit: ratio < RATIO_LIMIT && p99 < expectedCeiling,
    });
  }

  const failureRate = metricNumber(metrics, "http_req_failed", "rate");
  if (failureRate !== null && !(failureRate >= 0 && failureRate < FAILURE_RATE_LIMIT)) {
    errors.push(`HTTP failure rate ${failureRate} is not below the canonical rate<${FAILURE_RATE_LIMIT} gate.`);
  }

  const scenario = String(payload.scenario ?? "")
    .trim()
    .toLowerCase();
  const requireZero5xx = ZERO_5XX_SCENARIOS.includes(scenario);
  let checked5xx = false;
  for (const metricName of [AVERAGE_SERVER_ERROR_METRIC, SERVER_ERROR_METRIC]) {
    const count = metricNumber(metrics, metricName, "count");
    if (count === null) continue;
    // The runner defines the zero-5xx gate for the average scenario; the
    // average-tagged metric is checked in every scenario to prevent smuggling.
    if (requireZero5xx || metricName === AVERAGE_SERVER_ERROR_METRIC) {
      checked5xx = true;
      if (count !== 0) {
        errors.push(`5xx count (${metricName}) is ${count}; the canonical average-scenario gate requires exactly 0.`);
      }
    }
  }
  if (requireZero5xx && !checked5xx) {
    errors.push("Missing 5xx count metric; cannot verify the canonical average-scenario zero-5xx gate.");
  }

  const infraCount = metricNumber(metrics, INFRA_GATE_METRIC, "count");
  if (infraCount !== null && infraCount !== 0) {
    errors.push(`Infrastructure gate failure count is ${infraCount}; the canonical gate requires exactly 0.`);
  }
}

export function verifySummary(payload) {
  const errors = [];
  const thresholdRows = [];
  const ratioRows = [];

  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, errors: ["The k6 summary is not a JSON object."], thresholdRows, ratioRows };
  }

  validateBudgetManifest(payload, errors);
  validateThresholds(payload, errors, thresholdRows);
  verifyActualMetrics(payload, errors, ratioRows);

  return { ok: errors.length === 0, errors, thresholdRows, ratioRows, payload };
}

export function renderPerformanceDiff(result, summaryPath) {
  const payload = result.payload ?? {};
  const lines = [
    "# PLN-026 performance diff",
    "",
    `- Scenario: \`${payload.scenario ?? "unknown"}\``,
    `- Environment: \`${payload.environment ?? "unknown"}\``,
    `- Summary: \`${summaryPath}\``,
    "",
    "## Thresholds",
    "",
    "| Threshold | Result |",
    "| --- | --- |",
  ];
  if (result.thresholdRows.length === 0) {
    lines.push("| none | MISSING |");
  } else {
    for (const row of result.thresholdRows) {
      lines.push(`| \`${row.metric} ${row.expression}\` | ${row.ok ? "PASS" : "FAIL"} |`);
    }
  }

  lines.push(
    "",
    "## Canonical budgets (verification source of truth)",
    "",
    "Candidate-supplied `endpoint_budgets_ms` is never trusted; a mismatched manifest fails verification.",
    "",
    "| Endpoint | p95 budget ms | p99 budget ms (3x p95) |",
    "| --- | ---: | ---: |"
  );
  for (const [endpoint, budget] of Object.entries(CANONICAL_ENDPOINT_BUDGETS_MS).toSorted(([a], [b]) =>
    a.localeCompare(b)
  )) {
    lines.push(`| ${endpoint} | ${budget.p95} | ${budget.p99} |`);
  }

  lines.push(
    "",
    "## p99/p95 headroom",
    "",
    "| Endpoint | p95 ms | p95 budget | p99 ms | p99 budget | p99/p95 | Result |",
    "| --- | ---: | ---: | ---: | ---: | ---: | --- |"
  );
  if (result.ratioRows.length === 0) {
    lines.push("| none | — | — | — | — | — | MISSING |");
  } else {
    for (const row of result.ratioRows) {
      const budget = CANONICAL_ENDPOINT_BUDGETS_MS[row.endpoint];
      const p95Budget = row.p95Budget ?? budget?.p95;
      const p99Budget = row.p99Budget ?? budget?.p99;
      const pass = row.p95WithinBudget === true && row.p99WithinBudget === true && row.ratioWithinLimit === true;
      lines.push(
        `| ${row.endpoint} | ${row.p95.toFixed(1)} | ${p95Budget ?? "—"} | ${row.p99.toFixed(1)} | ${p99Budget ?? "—"} | ${row.ratio.toFixed(3)} | ${pass ? "PASS" : "FAIL"} |`
      );
    }
  }

  lines.push(
    "",
    "## Additional canonical gates",
    "",
    `- HTTP failure rate: \`rate<${FAILURE_RATE_LIMIT}\` (actual value recomputed when present).`,
    `- 5xx count: \`count===0\` for the average scenario and the average-tagged metric.`,
    `- Infrastructure gate failures: \`count===0\` when the gate is present.`,
    ""
  );

  if (result.errors.length > 0) {
    lines.push("", "## Verification errors", "");
    for (const error of result.errors) lines.push(`- ${error}`);
  }

  lines.push(
    "",
    "See `docs/testing/performance.md` for the before/after table, slow-query plans and written acceptance policy.",
    ""
  );
  return lines.join("\n");
}

export async function verifySummaryFile(summaryPath, diffPath) {
  let payload;
  try {
    payload = JSON.parse(await readFile(summaryPath, "utf8"));
  } catch (error) {
    const result = {
      ok: false,
      errors: [`Could not read a valid k6 summary from ${summaryPath}: ${error.message}`],
      thresholdRows: [],
      ratioRows: [],
    };
    await writeFile(diffPath, renderPerformanceDiff(result, summaryPath), "utf8");
    return result;
  }

  const result = verifySummary(payload);
  await writeFile(diffPath, renderPerformanceDiff(result, summaryPath), "utf8");
  return result;
}

function isMainModule() {
  const entry = process.argv[1] ? path.resolve(process.argv[1]) : "";
  return entry === path.resolve(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
}

if (isMainModule()) {
  const summaryPath = process.argv[2] ?? process.env.LOAD_SUMMARY_PATH ?? "load-tests/k6-summary.json";
  const diffPath = process.argv[3] ?? process.env.LOAD_DIFF_PATH ?? "load-tests/results/performance-diff.md";
  const result = await verifySummaryFile(summaryPath, diffPath);
  if (!result.ok) {
    for (const error of result.errors) process.stderr.write(`PLN-026 summary verification failed: ${error}\n`);
    process.exitCode = 1;
  } else {
    process.stdout.write(
      `PLN-026 summary verified: ${result.thresholdRows.length} thresholds, ${result.ratioRows.length} endpoint ratios.\n`
    );
  }
}
