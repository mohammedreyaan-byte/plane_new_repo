#!/usr/bin/env node
"use strict";

// Release gate check: no open P0/P1 bugs. Reads GitHub issues with the
// workflow token supplied through the environment; no credentials are logged.

const fs = require("node:fs");
const path = require("node:path");

function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} must be set for the PLN-026 release gate.`);
  }
  return value;
}

async function searchOpenIssues(apiUrl, repository, token, label) {
  const query = `repo:${repository} is:issue is:open label:"${label}"`;
  const response = await fetch(`${apiUrl}/search/issues?q=${encodeURIComponent(query)}&per_page=100`, {
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
  if (!response.ok) {
    throw new Error(`GitHub issue search for label ${label} returned HTTP ${response.status}.`);
  }
  const payload = await response.json();
  return {
    label,
    total_count: payload.total_count,
    issues: (payload.items || []).map((issue) => ({
      number: issue.number,
      title: issue.title,
      html_url: issue.html_url,
    })),
  };
}

async function main() {
  const token = required("GITHUB_TOKEN");
  const repository = required("GITHUB_REPOSITORY");
  const apiUrl = (process.env.GITHUB_API_URL || "https://api.github.com").replace(/\/$/, "");
  const labels = [process.env.PLN026_P0_LABEL || "P0", process.env.PLN026_P1_LABEL || "P1"];
  const results = await Promise.all(labels.map((label) => searchOpenIssues(apiUrl, repository, token, label)));

  const openBugs = results.flatMap((result) => result.issues.map((issue) => ({ ...issue, label: result.label })));
  const report = {
    generated_at: new Date().toISOString(),
    repository,
    labels,
    results,
    open_bugs: openBugs,
    passed: openBugs.length === 0,
  };

  const output = process.env.PLN026_GATE_OUTPUT || "pln026-release-gate.json";
  const outputPath = path.resolve(output);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`);

  for (const bug of openBugs) {
    process.stdout.write(`Open ${bug.label} bug #${bug.number}: ${bug.title}\n`);
  }
  process.stdout.write(`Release gate bug check: ${report.passed ? "PASS" : "FAIL"}.\n`);
  if (!report.passed) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
