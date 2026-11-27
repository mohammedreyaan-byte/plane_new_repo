#!/usr/bin/env node
"use strict";

// Aggregates Playwright JSON results into a 14-day flake dashboard.
// Input files are produced by the canonical @plane/e2e runner; no credentials
// are read, printed, or written by this script.

const fs = require("node:fs");
const path = require("node:path");

const FAILURE_STATUSES = new Set(["failed", "unexpected", "timedout", "timedOut"]);
const FLAKE_STATUSES = new Set(["flaky"]);

function parseArgs(argv) {
  const options = {
    inputs: [],
    outputJson: "flake-dashboard.json",
    outputMarkdown: "flake-dashboard.md",
    days: 14,
    threshold: 2,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === "--input" || flag === "-i") {
      options.inputs.push(value);
      index += 1;
    } else if (flag === "--output-json") {
      options.outputJson = value;
      index += 1;
    } else if (flag === "--output-markdown") {
      options.outputMarkdown = value;
      index += 1;
    } else if (flag === "--days") {
      options.days = Number(value);
      index += 1;
    } else if (flag === "--threshold") {
      options.threshold = Number(value);
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${flag}`);
    }
  }
  return options;
}

function walkFiles(directory) {
  if (!fs.existsSync(directory)) {
    return [];
  }
  const stat = fs.statSync(directory);
  if (!stat.isDirectory()) {
    return [directory];
  }
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === "node_modules" || entry.name === ".git") {
      return [];
    }
    return walkFiles(path.join(directory, entry.name));
  });
}

function findResultFiles(inputs) {
  const files = [];
  for (const input of inputs) {
    for (const candidate of walkFiles(input)) {
      if (path.basename(candidate) === "results.json") {
        files.push(candidate);
      }
    }
  }
  return [...new Set(files)].toSorted();
}

function addScenario(map, key) {
  if (!map.has(key)) {
    map.set(key, { title: key, runs: 0, failures: 0, flakes: 0, lastSeen: null });
  }
  return map.get(key);
}

function collectSuite(suite, ancestors, scenarioMap, observedAt) {
  const titles = suite.title && !suite.title.startsWith("playwright") ? [...ancestors, suite.title] : ancestors;

  for (const spec of suite.specs || []) {
    const key = [...titles, spec.title].join(" > ");
    for (const test of spec.tests || []) {
      const results = test.results || [];
      if (results.length === 0) {
        continue;
      }
      const scenario = addScenario(scenarioMap, key);
      scenario.runs += 1;
      if (!scenario.lastSeen || observedAt > scenario.lastSeen) {
        scenario.lastSeen = observedAt;
      }
      for (const result of results) {
        const status = String(result.status || "");
        if (FAILURE_STATUSES.has(status)) {
          scenario.failures += 1;
        } else if (FLAKE_STATUSES.has(status)) {
          scenario.flakes += 1;
        }
      }
    }
  }

  for (const child of suite.suites || []) {
    collectSuite(child, titles, scenarioMap, observedAt);
  }
}

function buildMarkdown(report, scenarios) {
  const lines = [
    `# PLN-026 flake dashboard (${report.window_days} days)`,
    "",
    `Generated: ${report.generated_at}`,
    "",
    `A scenario is quarantined when it fails more than ${report.threshold} times in the window.`,
    "Quarantine is tracking metadata only; role, workflow, and isolation scenarios are never skipped on a release branch.",
    "",
    "| Scenario | Runs | Failures | Flakes | Last seen | Status |",
    "| --- | ---: | ---: | ---: | --- | --- |",
  ];
  if (scenarios.length === 0) {
    lines.push("| no results found | 0 | 0 | 0 | — | no data |");
  }
  for (const scenario of scenarios) {
    const status = scenario.failures > report.threshold ? "QUARANTINED" : "tracked";
    lines.push(
      `| ${scenario.title.replaceAll("|", "\\|")} | ${scenario.runs} | ${scenario.failures} | ${scenario.flakes} | ${scenario.lastSeen ?? "unknown"} | ${status} |`
    );
  }
  lines.push("", "## Sources", "");
  for (const source of report.sources) {
    lines.push(`- \`${source}\``);
  }
  lines.push("");
  return lines.join("\n");
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  if (!options.inputs.length) {
    throw new Error("At least one --input directory or results.json file is required.");
  }
  if (!Number.isFinite(options.days) || options.days <= 0) {
    throw new Error("--days must be a positive number.");
  }
  if (!Number.isFinite(options.threshold) || options.threshold < 0) {
    throw new Error("--threshold must be zero or greater.");
  }

  const files = findResultFiles(options.inputs);
  const cutoff = Date.now() - options.days * 24 * 60 * 60 * 1000;
  const scenarioMap = new Map();
  const sources = [];

  for (const file of files) {
    const observedAt = fs.statSync(file).mtime.toISOString();
    if (Date.parse(observedAt) < cutoff) {
      continue;
    }
    let report;
    try {
      report = JSON.parse(fs.readFileSync(file, "utf8"));
    } catch (error) {
      process.stderr.write(`Skipping unreadable result ${file}: ${error.message}\n`);
      continue;
    }
    sources.push(file);
    for (const suite of report.suites || []) {
      collectSuite(suite, [], scenarioMap, observedAt);
    }
  }

  const scenarios = [...scenarioMap.values()].toSorted(
    (left, right) => right.failures - left.failures || left.title.localeCompare(right.title)
  );
  const report = {
    generated_at: new Date().toISOString(),
    window_days: options.days,
    failure_threshold: options.threshold,
    sources,
    scenarios,
    quarantined: scenarios
      .filter((scenario) => scenario.failures > options.threshold)
      .map((scenario) => scenario.title),
  };

  fs.mkdirSync(path.dirname(path.resolve(options.outputJson)), { recursive: true });
  fs.mkdirSync(path.dirname(path.resolve(options.outputMarkdown)), { recursive: true });
  fs.writeFileSync(path.resolve(options.outputJson), `${JSON.stringify(report, null, 2)}\n`);
  fs.writeFileSync(path.resolve(options.outputMarkdown), buildMarkdown(report, scenarios));
  process.stdout.write(
    `Flake report written: ${sources.length} result files, ${scenarios.length} scenarios, ${report.quarantined.length} quarantined.\n`
  );
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
