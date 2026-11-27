// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  CANONICAL_ENDPOINT_BUDGETS_MS,
  CANONICAL_THRESHOLDS,
  ERROR_COUNT_EXPRESSION,
  FAILURE_RATE_EXPRESSION,
  INFRA_GATE_METRIC,
  OPTIONAL_CANONICAL_THRESHOLDS,
  renderPerformanceDiff,
  verifySummary,
  verifySummaryFile,
} from "./verify-summary.js";

function endpointMetric(endpoint) {
  return `http_req_duration{endpoint:${endpoint}}`;
}

function canonicalThresholdCount() {
  return Object.values(CANONICAL_THRESHOLDS).flat().length + OPTIONAL_CANONICAL_THRESHOLDS[INFRA_GATE_METRIC].length;
}

function samplePayload() {
  const thresholds = {};
  for (const [metric, expressions] of Object.entries(CANONICAL_THRESHOLDS)) {
    thresholds[metric] = Object.fromEntries(expressions.map((expression) => [expression, true]));
  }
  // The runner always defines the infra gate; include its canonical entry.
  thresholds[INFRA_GATE_METRIC] = Object.fromEntries(
    OPTIONAL_CANONICAL_THRESHOLDS[INFRA_GATE_METRIC].map((expression) => [expression, true])
  );

  const metrics = {};
  for (const [endpoint, budget] of Object.entries(CANONICAL_ENDPOINT_BUDGETS_MS)) {
    const p95 = budget.p95 / 2;
    metrics[endpointMetric(endpoint)] = { "p(95)": p95, "p(99)": p95 * 1.5 };
  }
  metrics.http_req_failed = { rate: 0.001 };
  metrics.pln026_server_errors = { count: 0 };
  metrics["pln026_server_errors{scenario:average}"] = { count: 0 };
  metrics[INFRA_GATE_METRIC] = { count: 0 };

  return {
    suite: "PLN-026",
    scenario: "average",
    environment: "staging",
    thresholds,
    metrics,
    endpoint_budgets_ms: Object.fromEntries(
      Object.entries(CANONICAL_ENDPOINT_BUDGETS_MS).map(([endpoint, budget]) => [
        endpoint,
        { p95: budget.p95, p99: budget.p99 },
      ])
    ),
  };
}

function assertRejected(payload, pattern) {
  const result = verifySummary(payload);
  assert.equal(result.ok, false, `expected rejection; errors=${result.errors.join(" | ")}`);
  const errors = result.errors.join("\n");
  assert.match(errors, pattern);
  assert.match(renderPerformanceDiff(result, "summary.json"), /## Verification errors/);
  return result;
}

test("accepts a canonical summary with all eight endpoints and 3x p99 ceilings", () => {
  const result = verifySummary(samplePayload());
  assert.equal(result.ok, true);
  assert.deepEqual(result.errors, []);
  assert.equal(result.thresholdRows.length, canonicalThresholdCount());
  assert.equal(result.ratioRows.length, 8);
  assert.equal(result.ratioRows.find((row) => row.endpoint === "list").ratio, 1.5);

  const diff = renderPerformanceDiff(result, "summary.json");
  assert.match(diff, /\| `http_req_failed rate<0\.005` \| PASS \|/);
  assert.match(diff, /\| list \| 400 \| 1200 \|/);
  assert.match(diff, /\| admin_report_export \| 1200 \| 3600 \|/);
  assert.match(diff, /\| list \| 200\.0 \| 400 \| 300\.0 \| 1200 \| 1\.500 \| PASS \|/);
});

test("accepts threshold results wrapped in { ok }", () => {
  const payload = samplePayload();
  for (const metric of Object.keys(payload.thresholds)) {
    payload.thresholds[metric] = Object.fromEntries(
      Object.entries(payload.thresholds[metric]).map(([expression, ok]) => [expression, { ok }])
    );
  }
  assert.equal(verifySummary(payload).ok, true);
});

test("rejects a failed threshold without weakening the report", () => {
  const payload = samplePayload();
  payload.thresholds.http_req_failed[FAILURE_RATE_EXPRESSION] = false;
  const result = assertRejected(payload, /Threshold failed: http_req_failed rate<0\.005/);
  assert.match(renderPerformanceDiff(result, "summary.json"), /FAIL/);
});

test("rejects altered candidate budget values", () => {
  const payload = samplePayload();
  payload.endpoint_budgets_ms.detail.p95 = 301;
  assertRejected(payload, /Candidate-supplied budget for detail differs from the canonical budget/);
});

test("rejects an altered candidate budget endpoint set", () => {
  const payload = samplePayload();
  payload.endpoint_budgets_ms.fake = { p95: 1, p99: 3 };
  assertRejected(payload, /endpoint_budgets_ms endpoint set does not match/);
});

test("rejects an altered threshold expression such as rate<0.01", () => {
  const payload = samplePayload();
  delete payload.thresholds.http_req_failed[FAILURE_RATE_EXPRESSION];
  payload.thresholds.http_req_failed["rate<0.01"] = true;
  const result = assertRejected(payload, /Unexpected threshold http_req_failed rate<0\.01/);
  assert.match(
    result.errors.join("\n"),
    new RegExp(`Missing canonical threshold: http_req_failed ${FAILURE_RATE_EXPRESSION.replace(".", "\\.")}`)
  );
});

test("rejects a missing endpoint metric", () => {
  const payload = samplePayload();
  delete payload.metrics[endpointMetric("board")];
  assertRejected(payload, /Missing or non-numeric p95\/p99 samples for board/);
});

test("rejects a missing canonical threshold", () => {
  const payload = samplePayload();
  delete payload.thresholds[endpointMetric("cycle")]["p(99)<2400"];
  assertRejected(payload, /Missing canonical threshold: http_req_duration\{endpoint:cycle\} p\(99\)<2400/);
});

test("rejects an arbitrary extra threshold name", () => {
  const payload = samplePayload();
  payload.thresholds.custom_gate = { [ERROR_COUNT_EXPRESSION]: true };
  assertRejected(payload, /Unexpected threshold custom_gate count===0/);
});

test("rejects an arbitrary extra expression on a canonical threshold metric", () => {
  const payload = samplePayload();
  payload.thresholds[endpointMetric("list")]["p(99)<=1200"] = true;
  assertRejected(payload, /Unexpected threshold http_req_duration\{endpoint:list\} p\(99\)<=1200/);
});

test("rejects a p95 above the canonical budget even when its threshold says true", () => {
  const payload = samplePayload();
  payload.metrics[endpointMetric("list")]["p(95)"] = 450;
  payload.metrics[endpointMetric("list")]["p(99)"] = 600;
  assertRejected(payload, /p95 for list is 450; the canonical budget requires <400/);
});

test("rejects p99 at or above 3x p95", () => {
  const payload = samplePayload();
  payload.metrics[endpointMetric("list")]["p(95)"] = 100;
  payload.metrics[endpointMetric("list")]["p(99)"] = 300;
  assertRejected(payload, /p99\/p95 ratio for list is 3\.000; the ceiling is <3/);
});

test("rejects a nonzero 5xx count even when its threshold says true", () => {
  const payload = samplePayload();
  payload.metrics.pln026_server_errors = { count: 1 };
  payload.metrics["pln026_server_errors{scenario:average}"] = { count: 1 };
  assertRejected(
    payload,
    /5xx count \(pln026_server_errors\{scenario:average\}\) is 1; the canonical average-scenario gate requires exactly 0/
  );
});

test("rejects an HTTP failure rate at the canonical ceiling", () => {
  const payload = samplePayload();
  payload.metrics.http_req_failed = { rate: 0.005 };
  assertRejected(payload, /HTTP failure rate 0\.005 is not below the canonical rate<0\.005 gate/);
});

test("writes canonical evidence for a summary file", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "pln026-verify-ok-"));
  const summaryPath = path.join(directory, "summary.json");
  const diffPath = path.join(directory, "performance-diff.md");
  try {
    await writeFile(summaryPath, JSON.stringify(samplePayload()));
    const result = await verifySummaryFile(summaryPath, diffPath);
    assert.equal(result.ok, true);
    assert.deepEqual(result.errors, []);
    assert.match(await readFile(diffPath, "utf8"), /## Canonical budgets/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("fails when the summary file is missing and still writes evidence", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "pln026-verify-"));
  const summaryPath = path.join(directory, "missing.json");
  const diffPath = path.join(directory, "performance-diff.md");
  try {
    const result = await verifySummaryFile(summaryPath, diffPath);
    assert.equal(result.ok, false);
    assert.match(result.errors.join("\n"), /Could not read a valid k6 summary/);
    assert.match(await readFile(diffPath, "utf8"), /Verification errors/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
