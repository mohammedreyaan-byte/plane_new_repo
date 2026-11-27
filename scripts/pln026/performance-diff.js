#!/usr/bin/env node
"use strict";

// Builds a before/after performance report from k6 summary JSON files.
// Canonical budgets and thresholds are defined here and in load-tests/verify-summary.js;
// candidate-supplied `endpoint_budgets_ms` is ignored for calculations and rejected
// when it differs. The script only reads metric values; it never reads or prints credentials.

const fs = require("node:fs");
const path = require("node:path");

const RATIO_LIMIT = 3;
const FAILURE_RATE_LIMIT = 0.005;
const ZERO_COUNT = 0;

// Canonical PLN-026 budgets. p99 ceilings are exactly 3x the p95 ceilings.
const CANONICAL_BUDGETS = Object.freeze({
  list: { p95: 400, p99: 1200 },
  detail: { p95: 300, p99: 900 },
  board: { p95: 800, p99: 2400 },
  cycle: { p95: 800, p99: 2400 },
  analytics: { p95: 1200, p99: 3600 },
  create_update: { p95: 500, p99: 1500 },
  transition: { p95: 400, p99: 1200 },
  admin_report_export: { p95: 1200, p99: 3600 },
});

function parseArgs(argv) {
  const options = {
    baseline: null,
    candidate: null,
    output: "performance-diff.md",
    scenario: "unknown",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === "--baseline") {
      options.baseline = value;
      index += 1;
    } else if (flag === "--candidate") {
      options.candidate = value;
      index += 1;
    } else if (flag === "--output") {
      options.output = value;
      index += 1;
    } else if (flag === "--scenario") {
      options.scenario = value;
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${flag}`);
    }
  }
  if (!options.candidate) {
    throw new Error("--candidate k6 summary JSON is required.");
  }
  return options;
}

function readSummary(file) {
  if (!file || !fs.existsSync(file)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function metricValue(summary, name, key) {
  const metric = summary && summary.metrics && summary.metrics[name];
  // handleSummary() writes summarized values at the metric root; raw k6 JSON
  // keeps them under `values`. Accept both so CI evidence uses real numbers.
  const value = metric && (metric[key] ?? metric.values?.[key]);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function display(value, digits = 1) {
  return value === null || value === undefined ? "not measured" : value.toFixed(digits);
}

function delta(before, after) {
  if (before === null || after === null) {
    return "not measured";
  }
  const change = after - before;
  const sign = change > 0 ? "+" : "";
  return `${sign}${change.toFixed(1)}`;
}

function statusFor(after, limit, mode = "less") {
  if (after === null || limit === null) {
    return "not measured";
  }
  if (mode === "exact") {
    return after === limit ? "PASS" : "FAIL";
  }
  return after < limit ? "PASS" : "FAIL";
}

function budgetManifestProblem(summary) {
  if (!summary || !Object.prototype.hasOwnProperty.call(summary, "endpoint_budgets_ms")) {
    return null;
  }
  const supplied = summary.endpoint_budgets_ms;
  if (!supplied || typeof supplied !== "object" || Array.isArray(supplied)) {
    return "endpoint_budgets_ms must be an object";
  }
  const canonicalEndpoints = Object.keys(CANONICAL_BUDGETS).toSorted();
  if (Object.keys(supplied).toSorted().join("\u0000") !== canonicalEndpoints.join("\u0000")) {
    return "endpoint_budgets_ms endpoint set differs from the canonical set";
  }
  for (const endpoint of canonicalEndpoints) {
    const budget = supplied[endpoint];
    const canonical = CANONICAL_BUDGETS[endpoint];
    if (!budget || typeof budget !== "object" || Array.isArray(budget)) {
      return `endpoint_budgets_ms.${endpoint} is missing or malformed`;
    }
    if (Object.keys(budget).toSorted().join(",") !== "p95,p99") {
      return `endpoint_budgets_ms.${endpoint} has unexpected fields`;
    }
    if (budget.p95 !== canonical.p95 || budget.p99 !== canonical.p99) {
      return `endpoint_budgets_ms.${endpoint} differs from the canonical budget`;
    }
  }
  return null;
}

function ratioFor(summary, metricName) {
  const p95 = metricValue(summary, metricName, "p(95)");
  const p99 = metricValue(summary, metricName, "p(99)");
  return p95 !== null && p95 > 0 && p99 !== null ? p99 / p95 : null;
}

function buildRows(baseline, candidate) {
  const endpoints = Object.keys(CANONICAL_BUDGETS).toSorted();
  const rows = [];
  const budgetProblem = budgetManifestProblem(candidate);
  rows.push({
    metric: "Budget manifest integrity",
    before: "—",
    after: budgetProblem
      ? "rejected"
      : candidate && Object.prototype.hasOwnProperty.call(candidate, "endpoint_budgets_ms")
        ? "canonical"
        : "not supplied",
    delta: "—",
    threshold: "canonical budgets only",
    status: budgetProblem ? "FAIL" : "PASS",
    detail: budgetProblem,
  });

  for (const endpoint of endpoints) {
    const budget = CANONICAL_BUDGETS[endpoint];
    const metricName = `http_req_duration{endpoint:${endpoint}}`;
    const before = metricValue(baseline, metricName, "p(95)");
    const after = metricValue(candidate, metricName, "p(95)");
    rows.push({
      metric: `p95 ${endpoint} (ms)`,
      before: display(before),
      after: display(after),
      delta: delta(before, after),
      threshold: `< ${budget.p95}`,
      status: statusFor(after, budget.p95),
    });

    const before99 = metricValue(baseline, metricName, "p(99)");
    const after99 = metricValue(candidate, metricName, "p(99)");
    rows.push({
      metric: `p99 ${endpoint} (ms)`,
      before: display(before99),
      after: display(after99),
      delta: delta(before99, after99),
      threshold: `< ${budget.p99} (3x p95)`,
      status: statusFor(after99, budget.p99),
    });

    const ratioBefore = ratioFor(baseline, metricName);
    const ratioAfter = ratioFor(candidate, metricName);
    rows.push({
      metric: `p99/p95 ratio ${endpoint}`,
      before: display(ratioBefore, 3),
      after: display(ratioAfter, 3),
      delta:
        ratioBefore === null || ratioAfter === null
          ? "not measured"
          : `${ratioAfter - ratioBefore > 0 ? "+" : ""}${(ratioAfter - ratioBefore).toFixed(3)}`,
      threshold: `< ${RATIO_LIMIT}`,
      status: statusFor(ratioAfter, RATIO_LIMIT),
    });
  }

  const failureBefore = metricValue(baseline, "http_req_failed", "rate");
  const failureAfter = metricValue(candidate, "http_req_failed", "rate");
  rows.push({
    metric: "HTTP failure rate",
    before: display(failureBefore === null ? null : failureBefore * 100, 3),
    after: display(failureAfter === null ? null : failureAfter * 100, 3),
    delta:
      failureBefore === null || failureAfter === null
        ? "not measured"
        : `${((failureAfter - failureBefore) * 100).toFixed(3)} pp`,
    threshold: `rate<${FAILURE_RATE_LIMIT}`,
    status: statusFor(failureAfter, FAILURE_RATE_LIMIT),
  });

  const errorsBefore = metricValue(baseline, "pln026_server_errors", "count");
  const errorsAfter = metricValue(candidate, "pln026_server_errors", "count");
  rows.push({
    metric: "5xx count",
    before: display(errorsBefore, 0),
    after: display(errorsAfter, 0),
    delta: errorsBefore === null || errorsAfter === null ? "not measured" : (errorsAfter - errorsBefore).toFixed(0),
    threshold: "count===0 (average scenario)",
    status: statusFor(errorsAfter, ZERO_COUNT, "exact"),
  });

  const infraAfter = metricValue(candidate, "pln026_infra_gate_failures", "count");
  if (infraAfter !== null) {
    const infraBefore = metricValue(baseline, "pln026_infra_gate_failures", "count");
    rows.push({
      metric: "Infrastructure gate failures",
      before: display(infraBefore, 0),
      after: display(infraAfter, 0),
      delta: infraBefore === null ? "not measured" : (infraAfter - infraBefore).toFixed(0),
      threshold: "count===0",
      status: statusFor(infraAfter, ZERO_COUNT, "exact"),
    });
  }

  return rows;
}

function buildMarkdown(options, baseline, candidate, rows) {
  const lines = [
    `# PLN-026 performance diff - ${options.scenario}`,
    "",
    `Generated: ${new Date().toISOString()}`,
    "",
    `- Baseline: ${options.baseline || "not supplied"}`,
    `- Candidate: ${options.candidate}`,
    `- Environment: ${(candidate && candidate.environment) || "not recorded"}`,
    "",
    "Budgets and thresholds below are canonical; candidate-supplied budget manifests are never used as evidence.",
    "",
    "| Metric | Before | After | Delta | Threshold | Status |",
    "| --- | ---: | ---: | ---: | --- | --- |",
  ];
  for (const row of rows) {
    lines.push(`| ${row.metric} | ${row.before} | ${row.after} | ${row.delta} | ${row.threshold} | ${row.status} |`);
  }
  const details = rows.filter((row) => row.detail);
  if (details.length > 0) {
    lines.push("", "## Rejected evidence", "");
    for (const row of details) lines.push(`- ${row.metric}: ${row.detail}`);
  }
  lines.push(
    "",
    "Infrastructure gates (queue drain within 5 minutes, DB connections below 80%, and stable soak memory) require Grafana/Prometheus evidence attached to the run; this table does not infer those results.",
    ""
  );
  if (!baseline) {
    lines.push("> Baseline summary was not available. Values above are first-run observations only.", "");
  }
  return lines.join("\n");
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const baseline = readSummary(options.baseline);
  const candidate = readSummary(options.candidate);
  if (!candidate) {
    throw new Error(`Candidate summary ${options.candidate} could not be read.`);
  }
  const rows = buildRows(baseline, candidate);
  const outputPath = path.resolve(options.output);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, buildMarkdown(options, baseline, candidate, rows));
  const blockingRows = rows.filter((row) => row.status === "FAIL" || row.status === "not measured");
  process.exitCode = blockingRows.length > 0 ? 1 : 0;
  process.stdout.write(
    `Performance diff written: ${outputPath} (${blockingRows.length} threshold rows failed or not measured).\n`
  );
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
