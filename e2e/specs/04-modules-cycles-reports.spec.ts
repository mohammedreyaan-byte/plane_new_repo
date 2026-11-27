import { expect, test } from "../fixtures";
import { ProjectInsightsPage } from "../pages/project-insights.page";
import { JsonRecord } from "../support/api";

const productionRun = process.env.E2E_ENV === "production";

test.skip(productionRun, "Production runs are limited to the separate read-only smoke suite.");

test.beforeEach(async ({ config }) => {
  test.skip(config.environment === "production", "Production runs are limited to the separate read-only smoke suite.");
});

function isoDate(offsetDays: number): string {
  return new Date(Date.now() + offsetDays * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

test("18. Linking an Epic to a Module updates child completion progress", async ({
  adminApi,
  api,
  catalog,
  cleanup,
  page,
  uniqueName,
}) => {
  const module = await adminApi.createModule(catalog, uniqueName("Module progress"));
  const moduleId = String(module["id"] ?? "");
  expect(moduleId).not.toBe("");
  cleanup("module", moduleId);

  const epic = await adminApi.createIssue(catalog, { name: uniqueName("Module epic"), type: "epic" });
  const epicId = String(epic["id"] ?? "");
  expect(epicId).not.toBe("");
  cleanup("issue", epicId);

  const child = await adminApi.createIssue(catalog, {
    name: uniqueName("Module child"),
    type: "task",
    parentId: epicId,
  });
  const childId = String(child["id"] ?? "");
  expect(childId).not.toBe("");
  cleanup("issue", childId);

  await adminApi.addIssuesToModule(catalog, moduleId, [epicId, childId]);

  const progressForModule = async (): Promise<number> => {
    const report = await adminApi.report(catalog, "module-progress", { module_id: moduleId });
    const rows = Array.isArray(report["rows"]) ? (report["rows"] as JsonRecord[]) : [];
    const row = rows.find((candidate) => String(candidate["module_id"] ?? "") === moduleId);
    return Number(row?.["progress"] ?? -1);
  };

  await expect.poll(progressForModule).toBe(0);

  for (const stateName of ["In Progress", "Closed"]) {
    // Transitions are stateful and must be applied in order.
    // eslint-disable-next-line no-await-in-loop
    const transition = await api.transition(catalog, childId, stateName);
    expect(transition.status).toBe(200);
  }

  await expect.poll(progressForModule).toBe(50);

  const insights = new ProjectInsightsPage(page, catalog);
  await insights.openModule(moduleId);
  await insights.expectText(/progress/i);
});

test("19. Closing a cycle carries open work into the next cycle and records burndown", async ({
  adminApi,
  catalog,
  cleanup,
  page,
  uniqueName,
}) => {
  const current = await adminApi.createCycle(catalog, uniqueName("Cycle current"), isoDate(-7), isoDate(7));
  const next = await adminApi.createCycle(catalog, uniqueName("Cycle next"), isoDate(8), isoDate(21));
  const currentId = String(current["id"] ?? "");
  const nextId = String(next["id"] ?? "");
  expect(currentId && nextId).toBeTruthy();
  cleanup("cycle", currentId);
  cleanup("cycle", nextId);

  const completed = await adminApi.createIssue(catalog, { name: uniqueName("Cycle completed"), type: "task" });
  const carried = await adminApi.createIssue(catalog, { name: uniqueName("Cycle carry over"), type: "task" });
  const completedId = String(completed["id"] ?? "");
  const carriedId = String(carried["id"] ?? "");
  expect(completedId && carriedId).toBeTruthy();
  cleanup("issue", completedId);
  cleanup("issue", carriedId);

  await adminApi.addIssuesToCycle(catalog, currentId, [completedId, carriedId]);

  for (const stateName of ["In Progress", "Closed"]) {
    // Transitions are stateful and must be applied in order.
    // eslint-disable-next-line no-await-in-loop
    expect((await adminApi.transition(catalog, completedId, stateName)).status).toBe(200);
  }

  await adminApi.transferCycleIssues(catalog, currentId, nextId);
  await adminApi.completeCycle(catalog, currentId);

  await expect
    .poll(async () => String((await adminApi.cycleDetail(catalog, currentId))["status"] ?? ""))
    .toBe("completed");

  await expect
    .poll(async () => {
      const issues = await adminApi.cycleIssues(catalog, nextId);
      return issues.map((row) => String(row["issue_id"] ?? row["id"] ?? ""));
    })
    .toContain(carriedId);

  const nextIssues = await adminApi.cycleIssues(catalog, nextId);
  const nextIssueIds = nextIssues.map((row) => String(row["issue_id"] ?? row["id"] ?? ""));
  expect(nextIssueIds).not.toContain(completedId);

  const burndown = await adminApi.report(catalog, "cycle-burndown", { cycle_id: currentId });
  expect(Number(burndown["total"] ?? -1)).toBe(1);
  expect(Array.isArray(burndown["rows"])).toBe(true);

  const insights = new ProjectInsightsPage(page, catalog);
  await insights.openCycle(currentId);
  await insights.expectText(/burndown/i);
});

test("20. Reports match filtered work items and CSV export succeeds", async ({
  adminApi,
  catalog,
  cleanup,
  page,
  uniqueName,
}) => {
  const bugTypeId = catalog.types["bug"]?.id;
  expect(bugTypeId).toBeTruthy();

  const created = await adminApi.createIssue(catalog, {
    name: uniqueName("Report count bug"),
    type: "bug",
    priority: "high",
  });
  const createdId = String(created["id"] ?? "");
  expect(createdId).not.toBe("");
  cleanup("issue", createdId);

  const openStateIds = Object.values(catalog.states)
    .filter((state) => ["backlog", "unstarted", "started"].includes(state.group ?? ""))
    .map((state) => state.id);
  expect(openStateIds.length).toBeGreaterThan(0);

  const listQuery = {
    type_id: bugTypeId,
    priority: "high",
    state_id__in: openStateIds,
    per_page: 1000,
  };
  const rows = await adminApi.listIssues(catalog, listQuery);
  const expectedCount = rows.length;
  expect(expectedCount).toBeGreaterThan(0);

  const report = await adminApi.report(catalog, "bugs-by-state", {
    type_id: bugTypeId,
    priority: "high",
  });
  expect(Number(report["total"] ?? -1)).toBe(expectedCount);

  const exported = await adminApi.exportReport(catalog, "bugs-by-state", {
    type_id: bugTypeId,
    priority: "high",
  });
  expect(exported.status).toBe(200);
  expect(exported.headers["content-disposition"] ?? "").toMatch(/\.csv/i);
  expect(exported.text).toContain("State");

  const insights = new ProjectInsightsPage(page, catalog);
  await insights.openReports();
  await insights.expectText(/report|analytics/i);
});
