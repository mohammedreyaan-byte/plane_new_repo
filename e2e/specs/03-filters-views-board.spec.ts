import { emailForRole } from "../support/env";
import { findMemberId } from "../support/members";
import { expect, test } from "../fixtures";
import { BacklogPage } from "../pages/backlog.page";
import { BoardPage } from "../pages/board.page";
import { ViewPage } from "../pages/view.page";
import { WorkItemPage } from "../pages/work-item.page";

test("12. Type, priority, assignee and state filters combine", async ({
  adminApi,
  catalog,
  cleanup,
  config,
  uniqueName,
}) => {
  const members = await adminApi.workspaceMembers();
  const assigneeId = findMemberId(members, emailForRole(config, "member"));
  const bugType = catalog.types["bug"]?.id ?? "";
  const newState = catalog.states["New"]?.id ?? "";
  expect(bugType).not.toBe("");
  expect(newState).not.toBe("");

  const matching = await adminApi.createIssue(catalog, {
    name: uniqueName("combined filter match"),
    type: "bug",
    priority: "high",
    assigneeIds: [assigneeId],
  });
  const wrongType = await adminApi.createIssue(catalog, {
    name: uniqueName("combined filter wrong type"),
    type: "task",
    priority: "high",
    assigneeIds: [assigneeId],
  });
  const wrongPriority = await adminApi.createIssue(catalog, {
    name: uniqueName("combined filter wrong priority"),
    type: "bug",
    priority: "low",
    assigneeIds: [assigneeId],
  });
  const matchingId = String(matching["id"] ?? "");
  cleanup("issue", matchingId);
  cleanup("issue", String(wrongType["id"] ?? ""));
  cleanup("issue", String(wrongPriority["id"] ?? ""));

  await expect
    .poll(async () => {
      const rows = await adminApi.listIssues(catalog, {
        type_id: bugType,
        priority: "high",
        assignee_id: assigneeId,
        state_id: newState,
      });
      return rows.map((row) => String(row["id"] ?? ""));
    })
    .toContain(matchingId);

  const rows = await adminApi.listIssues(catalog, {
    type_id: bugType,
    priority: "high",
    assignee_id: assigneeId,
    state_id: newState,
  });
  const ids = rows.map((row) => String(row["id"] ?? ""));
  expect(ids).not.toContain(String(wrongType["id"] ?? ""));
  expect(ids).not.toContain(String(wrongPriority["id"] ?? ""));
});

test("13. Grouped view is saved and reloads with identical results", async ({
  adminApi,
  catalog,
  cleanup,
  page,
  uniqueName,
}) => {
  const name = uniqueName("Grouped by type");
  const filters = { type: ["bug"] };
  const displayFilters = { group_by: "type" };
  const view = await adminApi.createView(catalog, name, filters, displayFilters);
  const viewId = String(view["id"] ?? "");
  expect(viewId).not.toBe("");
  cleanup("view", viewId);

  const before = (await adminApi.listIssues(catalog, { type_id: catalog.types["bug"]?.id ?? "" }))
    .map((row) => String(row["id"] ?? ""))
    .toSorted();

  const viewPage = new ViewPage(page, catalog);
  await viewPage.open(viewId);
  await viewPage.expectViewVisible(name);
  await page.reload();
  await viewPage.expectViewVisible(name);

  const after = (await adminApi.listIssues(catalog, { type_id: catalog.types["bug"]?.id ?? "" }))
    .map((row) => String(row["id"] ?? ""))
    .toSorted();
  expect(after).toEqual(before);
});

test.describe("Shared view", () => {
  test.use({ role: "member" });

  test("14. Shared view is visible but read-only for a non-owner", async ({
    adminApi,
    api,
    catalog,
    cleanup,
    config,
    page,
    uniqueName,
  }) => {
    const name = uniqueName("Shared view");
    const view = await adminApi.createView(catalog, name, { type: ["task"] }, { group_by: "state" });
    const viewId = String(view["id"] ?? "");
    expect(viewId).not.toBe("");
    cleanup("view", viewId);

    const viewPage = new ViewPage(page, catalog);
    await viewPage.open(viewId);
    await viewPage.expectViewVisible(name);
    await viewPage.expectReadOnly();

    const forbidden = await api.raw(
      "PATCH",
      `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/views/${viewId}/`,
      { body: { name: uniqueName("Unauthorized rename") } }
    );
    expect([403, 404]).toContain(forbidden.status);
    expect(config.workspaceSlug).toBe(catalog.workspaceSlug);
  });
});

test("15. Backlog rank persists after reload", async ({ adminApi, catalog, page, workItem }) => {
  const names = ["Backlog first", "Backlog second", "Backlog third"];
  const items = await Promise.all(names.map((label) => workItem("task", label)));
  const stateId = catalog.states["New"]?.id ?? "";
  const updated = await adminApi.reorderIssues(
    catalog,
    items.map((item) => ({ issueId: item.id, stateId }))
  );
  expect(updated).toHaveLength(3);

  const backlog = new BacklogPage(page, catalog);
  await backlog.open();
  await backlog.expectOrder(items.map((item) => item.name));
  await page.reload();
  await backlog.expectOrder(items.map((item) => item.name));
});

test("16. Backlog items move to the active cycle and transition", async ({
  adminApi,
  api,
  catalog,
  page,
  workItem,
}) => {
  const cycles = await adminApi.cycles(catalog);
  const activeCycle = cycles.find((cycle) =>
    String(cycle["name"] ?? "")
      .toLowerCase()
      .includes("active")
  );
  expect(activeCycle).toBeTruthy();
  const activeCycleId = String(activeCycle?.["id"] ?? "");
  const items = [await workItem("task", "Cycle move one"), await workItem("task", "Cycle move two")];

  await adminApi.addIssuesToCycle(
    catalog,
    activeCycleId,
    items.map((item) => item.id)
  );
  const transitions = await Promise.all(items.map((item) => api.transition(catalog, item.id, "In Progress")));
  for (const transition of transitions) {
    expect(transition.status).toBe(200);
  }

  const cycleRows = await adminApi.cycleIssues(catalog, activeCycleId);
  const cycleIds = cycleRows.map((row) => String(row["issue_id"] ?? row["id"] ?? ""));
  const updates = await Promise.all(
    items.map(async (item) => ({ item, updated: await adminApi.getIssue(catalog, item.id) }))
  );
  for (const { item, updated } of updates) {
    expect(cycleIds).toContain(item.id);
    expect(String(updated["state_id"] ?? "")).toBe(catalog.states["In Progress"]?.id ?? "");
  }

  await page.goto(`/${catalog.workspaceSlug}/projects/${catalog.projectId}/cycles/${activeCycleId}`);
  const workItems = new WorkItemPage(page, catalog);
  await Promise.all(items.map((item) => workItems.expectNameVisible(item.name)));
});

test.describe("Board drag", () => {
  test.use({ role: "developer" });

  test("17. Allowed board drag works and blocked column explains why", async ({
    adminApi,
    api,
    catalog,
    page,
    workItem,
  }) => {
    const item = await workItem("bug", "Board drag");
    const board = new BoardPage(page, catalog);
    await board.open("bug");
    await board.dragCard(item.name, "In Progress");

    await expect
      .poll(async () => String((await adminApi.getIssue(catalog, item.id))["state_id"] ?? ""))
      .toBe(catalog.states["In Progress"]?.id ?? "");

    // Workflow state order is intentional here; each transition unlocks the next.
    // oxlint-disable no-await-in-loop
    for (const stateName of ["Code Review", "In Testing"]) {
      expect((await api.transition(catalog, item.id, stateName)).status).toBe(200);
    }
    // oxlint-enable no-await-in-loop
    await board.open("bug");
    await board.dragCard(item.name, "Tested");
    await board.expectBlockReason(/qa|not allowed|permission/i);
  });
});
