// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

/**
 * PLN-026 mutation check.
 *
 * Copies the load-test verifier into a temporary directory, deliberately breaks
 * its safety rules, and requires the Node test suite to fail. The repository
 * source is never mutated. This provides repeatable evidence that at least
 * three tests detect a broken rule instead of silently passing.
 */

import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..", "..");
const loadTestsDir = path.join(repoRoot, "load-tests");
const verifierName = "verify-summary.js";
const testName = "verify-summary.test.mjs";
const minimumFailures = 3;

function copyVerifierSuite(destination) {
  cpSync(path.join(loadTestsDir, verifierName), path.join(destination, verifierName));
  cpSync(path.join(loadTestsDir, testName), path.join(destination, testName));
}

function applyMutation(directory, mutation) {
  const target = path.join(directory, verifierName);
  let text = readFileSync(target, "utf8");
  for (const replacement of mutation.replacements) {
    if (!text.includes(replacement.from)) {
      throw new Error(`Mutation anchor not found: ${replacement.id}`);
    }
    text = text.replace(replacement.from, replacement.to);
  }
  writeFileSync(target, text, "utf8");
}

function runNodeTests(directory) {
  const result = spawnSync(process.execPath, ["--test", testName], {
    cwd: directory,
    encoding: "utf8",
    timeout: 120000,
  });
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  const failedTests = Array.from(
    output.matchAll(/^(?:not ok \d+ - |[✖x]\s+(?!failing tests:))(.+?)(?:\s+\(\d+(?:\.\d+)?(?:ms|s)\))?$/gm),
    (match) => match[1].trim()
  );
  const summaryMatch = output.match(/^\s*(?:ℹ|#)\s*fail\s+(\d+)\s*$/m);
  const failedCount = summaryMatch ? Number(summaryMatch[1]) : failedTests.length;
  return {
    exitCode: result.status ?? 1,
    failedCount,
    failedTests,
    output,
  };
}

function main() {
  const tempRoot = mkdtempSync(path.join(tmpdir(), "pln026-mutation-"));
  const baselineDir = path.join(tempRoot, "baseline");
  const mutantDir = path.join(tempRoot, "mutant");
  const evidencePath =
    process.env.PLN026_MUTATION_EVIDENCE ??
    path.join(repoRoot, "..", ".playwright-mcp", "pln026-mutation-check-result.json");

  try {
    mkdirSync(baselineDir, { recursive: true });
    mkdirSync(mutantDir, { recursive: true });
    copyVerifierSuite(baselineDir);
    copyVerifierSuite(mutantDir);

    const baseline = runNodeTests(baselineDir);
    if (baseline.exitCode !== 0 || baseline.failedCount !== 0) {
      throw new Error(`Baseline PLN-026 verifier tests must pass before mutation (failures=${baseline.failedCount}).`);
    }

    const mutation = {
      id: "disable-threshold-and-missing-summary-failures",
      description: "Force threshold and missing-summary verification to report success even when errors are found.",
      replacements: [
        {
          id: "threshold-ok-always-true",
          from: "return { ok: errors.length === 0, errors, thresholdRows, ratioRows, payload };",
          to: "return { ok: true, errors, thresholdRows, ratioRows, payload };",
        },
        {
          id: "missing-summary-ok-true",
          from: [
            "const result = {",
            "      ok: false,",
            "      errors: [`Could not read a valid k6 summary from ${summaryPath}: ${error.message}`],",
          ].join("\n"),
          to: [
            "const result = {",
            "      ok: true,",
            "      errors: [`Could not read a valid k6 summary from ${summaryPath}: ${error.message}`],",
          ].join("\n"),
        },
      ],
    };
    applyMutation(mutantDir, mutation);
    const mutated = runNodeTests(mutantDir);

    const evidence = {
      ticket: "PLN-026",
      generated_at_utc: new Date().toISOString(),
      command: "node --test verify-summary.test.mjs",
      baseline: {
        exit_code: baseline.exitCode,
        failed_tests: baseline.failedCount,
      },
      mutation,
      mutated: {
        exit_code: mutated.exitCode,
        failed_tests: mutated.failedCount,
        failed_test_names: mutated.failedTests,
        output_excerpt: mutated.output.slice(0, 4000),
      },
      required_minimum_failures: minimumFailures,
      result: mutated.exitCode !== 0 && mutated.failedCount >= minimumFailures ? "PASS" : "FAIL",
      limitations: [
        "The mutation runs in a temporary copy; repository source is unchanged.",
        "Evidence covers the automated summary-verification rules only; live E2E and k6 results remain environment-dependent.",
      ],
    };

    mkdirSync(path.dirname(evidencePath), { recursive: true });
    writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
    process.stdout.write(
      `PLN-026 mutation check ${evidence.result}: ${mutated.failedCount} tests failed after mutation; evidence=${evidencePath}\n`
    );
    if (evidence.result !== "PASS") process.exitCode = 1;
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
}

main();
