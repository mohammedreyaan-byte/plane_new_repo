import { BrowserContext, Page, test as base } from "@playwright/test";
import { PlaneApi } from "./support/api";
import { E2eConfig, Role, loadEnv } from "./support/env";
import { ProjectCatalog } from "./support/types";

type CleanupKind = "issue" | "view" | "cycle" | "module" | "project" | "token";

interface CleanupRecord {
  kind: CleanupKind;
  id: string;
}

type Cleanup = (kind: CleanupKind, id: string) => void;

type CreatedWorkItem = {
  id: string;
  name: string;
  type: string;
};

interface WorkerFixtures {
  config: E2eConfig;
  adminApi: PlaneApi;
  catalog: ProjectCatalog;
}

interface TestFixtures {
  role: Role;
  api: PlaneApi;
  serviceApi: PlaneApi | undefined;
  page: Page;
  anonymousPage: Page;
  cleanup: Cleanup;
  workItem: (type: string, label: string) => Promise<CreatedWorkItem>;
  uniqueName: (label: string) => string;
  environmentGuard: void;
}

export const test = base.extend<TestFixtures, WorkerFixtures>({
  config: [
    // Playwright requires the empty destructuring pattern for fixtures with no inputs.
    // oxlint-disable-next-line no-empty-pattern
    async ({}, use) => {
      await use(loadEnv());
    },
    { scope: "worker" },
  ],

  adminApi: [
    async ({ config }, use) => {
      const api = await PlaneApi.create(config, "admin");
      await use(api);
      await api.close();
    },
    { scope: "worker" },
  ],

  catalog: [
    async ({ adminApi }, use) => {
      await use(await adminApi.loadCatalog());
    },
    { scope: "worker" },
  ],

  role: ["admin", { option: true }],

  environmentGuard: [
    async ({ config }, use, testInfo) => {
      if (
        config.environment === "production" &&
        config.productionSmokeAllowed &&
        !testInfo.tags.includes("@production-smoke")
      ) {
        throw new Error(
          "Production runs are limited to read-only @production-smoke tests; refusing a destructive or state-changing scenario."
        );
      }
      await use();
    },
    { auto: true },
  ],

  api: async ({ config, role }, use) => {
    const api = await PlaneApi.create(config, role);
    await use(api);
    await api.close();
  },

  serviceApi: async ({ config }, use) => {
    if (!config.serviceToken) {
      await use(undefined);
      return;
    }
    const api = await PlaneApi.create(config, "service", config.serviceToken);
    await use(api);
    await api.close();
  },

  page: async ({ browser, config, api }, use) => {
    const context: BrowserContext = await browser.newContext({
      baseURL: config.baseUrl,
      storageState: await api.storageState(),
    });
    const page = await context.newPage();
    await use(page);
    await context.close();
  },

  anonymousPage: async ({ browser, config }, use) => {
    const context = await browser.newContext({ baseURL: config.baseUrl });
    const page = await context.newPage();
    await use(page);
    await context.close();
  },

  cleanup: async ({ adminApi, catalog }, use) => {
    const records: CleanupRecord[] = [];
    await use((kind, id) => {
      records.push({ kind, id });
    });
    // Cleanup must run in reverse creation order so dependent rows are removed first.
    // oxlint-disable no-await-in-loop
    for (const record of records.toReversed()) {
      try {
        if (record.kind === "issue") {
          await adminApi.deleteIssue(catalog, record.id);
        } else if (record.kind === "view") {
          await adminApi.deleteView(catalog, record.id);
        } else if (record.kind === "cycle") {
          await adminApi.deleteCycle(catalog, record.id);
        } else if (record.kind === "module") {
          await adminApi.deleteModule(catalog, record.id);
        } else if (record.kind === "project") {
          await adminApi.deleteProject(record.id);
        } else {
          await adminApi.raw("DELETE", `/api/users/api-tokens/${record.id}/`);
        }
      } catch {
        // Cleanup is best-effort: the seeded workspace is reset before each run.
      }
    }
    // oxlint-enable no-await-in-loop
  },

  uniqueName: async ({ config }, use, testInfo) => {
    const suffix = `${config.runId}-${testInfo.project.name}-${testInfo.workerIndex}`.replace(/[^a-zA-Z0-9-]/g, "-");
    await use((label: string) => `${label} ${suffix}`);
  },

  workItem: async ({ api, catalog, cleanup, uniqueName }, use) => {
    await use(async (type: string, label: string) => {
      const name = uniqueName(label);
      const issue = await api.createIssue(catalog, { name, type });
      const id = String(issue["id"] ?? "");
      if (!id) {
        throw new Error(`Creating ${name} did not return an issue id.`);
      }
      cleanup("issue", id);
      return { id, name, type };
    });
  },
});

export { expect } from "@playwright/test";
