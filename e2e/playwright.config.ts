import { defineConfig, devices } from "@playwright/test";

const shardIndex = process.env.E2E_SHARD_INDEX;
const shardTotal = process.env.E2E_SHARD_TOTAL;
const hasValidShard = shardIndex !== undefined && shardTotal !== undefined;
const shard =
  hasValidShard && Number.isInteger(Number(shardIndex)) && Number.isInteger(Number(shardTotal))
    ? { current: Number(shardIndex), total: Number(shardTotal) }
    : undefined;
const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000";
const webServerCommand = process.env.E2E_WEB_SERVER_COMMAND;

export default defineConfig({
  testDir: "./specs",
  outputDir: "test-results",
  globalSetup: "./support/global-setup.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 4 : undefined,
  ...(shard ? { shard } : {}),
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
    ["json", { outputFile: "test-results/results.json" }],
  ],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: process.env.CI ? "retain-on-failure" : "off",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  ...(webServerCommand
    ? {
        webServer: {
          command: webServerCommand,
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 180_000,
        },
      }
    : {}),
});
