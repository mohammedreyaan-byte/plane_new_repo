import { expect, test } from "../fixtures";
import { BoardPage } from "../pages/board.page";
import { WorkItemPage } from "../pages/work-item.page";
import { JsonRecord, PlaneApi, QueryValue } from "../support/api";
import { ProjectCatalog } from "../support/types";

type CleanupKind = "issue" | "view" | "project" | "token";
type Cleanup = (kind: CleanupKind, id: string) => void;

function asRecord(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function str(row: JsonRecord, key: string): string {
  return String(row[key] ?? "");
}

function requireType(catalog: ProjectCatalog, key: string): string {
  const id = catalog.types[key]?.id;
  expect(id, `Seeded work item type ${key} is missing.`).toBeTruthy();
  return id ?? "";
}

function requireState(catalog: ProjectCatalog, name: string): string {
  const id = catalog.states[name]?.id;
  expect(id, `Seeded state ${name} is missing.`).toBeTruthy();
  return id ?? "";
}

function appBase(catalog: ProjectCatalog): string {
  return `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}`;
}

async function boardColumns(api: PlaneApi, catalog: ProjectCatalog, typeKey: string): Promise<string[]> {
  const result = await api.json<JsonRecord>("GET", `${appBase(catalog)}/issues/`, {
    query: {
      layout: "board",
      group_by: "state_id",
      type_id: requireType(catalog, typeKey),
      per_page: 1,
    } satisfies Record<string, QueryValue>,
  });
  const stats = asRecord(result.data["extra_stats"]);
  const columns = Array.isArray(stats["columns"]) ? (stats["columns"] as JsonRecord[]) : [];
  return columns.map((column) => str(column, "name")).filter(Boolean);
}

async function createIssue(
  api: PlaneApi,
  catalog: ProjectCatalog,
  cleanup: Cleanup,
  name: string,
  typeKey: string,
  extra: JsonRecord = {}
): Promise<{ id: string; name: string }> {
  const created = await api.json<JsonRecord>("POST", api.workItemBase(catalog), {
    body: { name, type_id: requireType(catalog, typeKey), ...extra },
  });
  const id = str(created.data, "id");
  expect(id, `Creating ${name} did not return an id.`).not.toBe("");
  cleanup("issue", id);
  return { id, name };
}

function errorCode(value: unknown): string {
  return str(asRecord(asRecord(value)["error"]), "code");
}

test("6. Bug type badge is visible in list, board and detail @smoke", async ({ adminApi, catalog, page, workItem }) => {
  const item = await workItem("bug", "Bug badge");
  const typeId = requireType(catalog, "bug");
  const typeName = catalog.types["bug"]?.name ?? "Bug";

  expect(str(await adminApi.getIssue(catalog, item.id), "type_id")).toBe(typeId);

  const workItems = new WorkItemPage(page, catalog);
  await workItems.openList();
  await workItems.expectNameVisible(item.name);
  await workItems.expectBadgeVisible(typeName);

  const board = new BoardPage(page, catalog);
  await board.open(typeId);
  await expect(page.getByText(item.name, { exact: true }).first()).toBeVisible();
  await board.expectColumns(["New", "In Progress", "Code Review", "In Testing", "Tested", "Closed"]);
  await workItems.expectBadgeVisible(typeName);

  await workItems.open(item.id);
  await workItems.expectBadgeVisible(typeName);
});

test.describe("QA workflow walk", () => {
  test.use({ role: "qa" });

  test("7. QA walks a Bug from New through Tested to Closed", async ({
    adminApi,
    api,
    catalog,
    cleanup,
    page,
    uniqueName,
  }) => {
    const item = await createIssue(adminApi, catalog, cleanup, uniqueName("QA bug walk"), "bug");
    expect(str(await adminApi.getIssue(catalog, item.id), "state_id")).toBe(requireState(catalog, "New"));

    // The QA walk must follow the workflow order; each state is verified before the next.
    // oxlint-disable no-await-in-loop
    for (const stateName of ["In Progress", "Code Review", "In Testing", "Tested", "Closed"]) {
      const result = await api.transition(catalog, item.id, stateName);
      expect(result.status, `QA transition to ${stateName}`).toBe(200);
      await expect
        .poll(async () => str(await adminApi.getIssue(catalog, item.id), "state_id"), { timeout: 15_000 })
        .toBe(requireState(catalog, stateName));
    }
    // oxlint-enable no-await-in-loop

    const activities = await adminApi.activities(catalog, item.id);
    expect(
      activities.some(
        (row) => str(row, "field") === "state" && str(row, "new_value") === requireState(catalog, "Closed")
      )
    ).toBeTruthy();

    const workItems = new WorkItemPage(page, catalog);
    await workItems.open(item.id);
    await workItems.expectStateVisible("Closed");
  });
});

test.describe("Developer workflow restrictions", () => {
  test.use({ role: "developer" });

  test("8. Developer is blocked from In Testing to Tested in menu and API", async ({
    adminApi,
    api,
    catalog,
    cleanup,
    page,
    uniqueName,
  }) => {
    const item = await createIssue(adminApi, catalog, cleanup, uniqueName("Developer blocked bug"), "bug");
    // Workflow state order is intentional; the final state is the one under test.
    // oxlint-disable no-await-in-loop
    for (const stateName of ["In Progress", "Code Review", "In Testing"]) {
      const setup = await adminApi.transition(catalog, item.id, stateName);
      expect(setup.status, `Seeding state ${stateName}`).toBe(200);
    }
    // oxlint-enable no-await-in-loop
    await expect
      .poll(async () => str(await adminApi.getIssue(catalog, item.id), "state_id"))
      .toBe(requireState(catalog, "In Testing"));

    const allowed = await api.allowedTransitions(catalog, item.id);
    expect(allowed.status).toBe(200);
    const payload = asRecord(allowed.data);
    const transitions = Array.isArray(payload["transitions"]) ? (payload["transitions"] as JsonRecord[]) : [];
    const targets = transitions.map((row) => str(row, "to_state_name"));
    expect(targets).toContain("In Progress");
    expect(targets).not.toContain("Tested");

    const workItems = new WorkItemPage(page, catalog);
    await workItems.open(item.id);
    const stateButton = page.getByRole("button", { name: /In Testing/i }).first();
    await expect(stateButton).toBeVisible();
    await stateButton.click();
    await expect(page.getByRole("menuitem", { name: "In Progress", exact: true })).toBeVisible();
    await workItems.expectTransitionOptionHidden("Tested");

    const denied = await api.transition(catalog, item.id, "Tested");
    expect(denied.status).toBe(403);
    expect(errorCode(denied.data)).toBe("transition_forbidden");
    expect(str(await adminApi.getIssue(catalog, item.id), "state_id")).toBe(requireState(catalog, "In Testing"));
  });
});

test("9. Task, Story and Epic each show their own columns and states", async ({ adminApi, catalog, page }) => {
  const expectedColumns: Record<string, string[]> = {
    task: ["New", "In Progress", "Closed"],
    story: ["New", "In Progress", "Code Review", "Closed"],
    epic: ["New", "In Progress", "Closed"],
  };
  const board = new BoardPage(page, catalog);

  // Each type is checked in turn so board navigation stays deterministic.
  // oxlint-disable no-await-in-loop
  for (const [typeKey, expected] of Object.entries(expectedColumns)) {
    const workflowId = catalog.workflows[typeKey]?.id;
    expect(workflowId, `Seeded ${typeKey} workflow is missing.`).toBeTruthy();
    const workflow = await adminApi.json<JsonRecord>("GET", `${appBase(catalog)}/workflows/${workflowId ?? ""}/`);
    const states = Array.isArray(workflow.data["states"]) ? (workflow.data["states"] as JsonRecord[]) : [];
    expect(states.map((state) => str(state, "name"))).toEqual(expected);
    expect(await boardColumns(adminApi, catalog, typeKey)).toEqual(expected);

    await board.open(requireType(catalog, typeKey));
    await board.expectColumns(expected);
  }
  // oxlint-enable no-await-in-loop

  expect(await boardColumns(adminApi, catalog, "story")).toContain("Code Review");
  expect(await boardColumns(adminApi, catalog, "task")).not.toContain("Code Review");
});

test("10. Type change resets the state and records activity", async ({
  adminApi,
  catalog,
  cleanup,
  page,
  uniqueName,
}) => {
  const item = await createIssue(adminApi, catalog, cleanup, uniqueName("Type change bug"), "bug");
  // Workflow state order is intentional; the type change must reset from In Testing.
  // oxlint-disable no-await-in-loop
  for (const stateName of ["In Progress", "Code Review", "In Testing"]) {
    const result = await adminApi.transition(catalog, item.id, stateName);
    expect(result.status, `Seeding state ${stateName}`).toBe(200);
  }
  // oxlint-enable no-await-in-loop
  expect(str(await adminApi.getIssue(catalog, item.id), "state_id")).toBe(requireState(catalog, "In Testing"));

  await adminApi.changeType(catalog, item.id, "task");
  await expect
    .poll(async () => str(await adminApi.getIssue(catalog, item.id), "state_id"), { timeout: 15_000 })
    .toBe(requireState(catalog, "New"));
  expect(str(await adminApi.getIssue(catalog, item.id), "type_id")).toBe(requireType(catalog, "task"));

  const activities = await adminApi.activities(catalog, item.id);
  expect(
    activities.some(
      (row) =>
        str(row, "field") === "type" &&
        /Type changed from/i.test(str(row, "comment")) &&
        /state reset to New/i.test(str(row, "comment"))
    )
  ).toBeTruthy();

  const workItems = new WorkItemPage(page, catalog);
  await workItems.open(item.id);
  await workItems.expectStateVisible("New");
  await workItems.expectActivity("Type changed");
});

test("11. Epic with open children cannot be completed without force and a comment", async ({
  adminApi,
  catalog,
  cleanup,
  uniqueName,
}) => {
  const epic = await createIssue(adminApi, catalog, cleanup, uniqueName("Guarded epic"), "epic");
  const child = await createIssue(adminApi, catalog, cleanup, uniqueName("Open epic child"), "bug", {
    parent: epic.id,
  });
  expect(str(await adminApi.getIssue(catalog, child.id), "parent_id")).toBe(epic.id);

  const start = await adminApi.transition(catalog, epic.id, "In Progress");
  expect(start.status).toBe(200);

  const blocked = await adminApi.transition(catalog, epic.id, "Closed");
  expect(blocked.status).toBe(400);
  expect(errorCode(blocked.data)).toBe("epic_has_open_children");

  const forceOnly = await adminApi.transition(catalog, epic.id, "Closed", { force: true });
  expect(forceOnly.status).toBe(400);
  expect(errorCode(forceOnly.data)).toBe("epic_has_open_children");

  const comment = uniqueName("Force complete audit");
  const commentOnly = await adminApi.transition(catalog, epic.id, "Closed", { comment });
  expect(commentOnly.status).toBe(400);
  expect(errorCode(commentOnly.data)).toBe("epic_has_open_children");

  const forced = await adminApi.transition(catalog, epic.id, "Closed", { force: true, comment });
  expect(forced.status).toBe(200);
  await expect
    .poll(async () => str(await adminApi.getIssue(catalog, epic.id), "state_id"), { timeout: 15_000 })
    .toBe(requireState(catalog, "Closed"));

  const activities = await adminApi.activities(catalog, epic.id);
  expect(
    activities.some(
      (row) =>
        str(row, "field") === "workflow.epic_force_complete" &&
        /force=true/i.test(str(row, "comment")) &&
        str(row, "comment").includes(comment)
    )
  ).toBeTruthy();
  const comments = await adminApi.comments(catalog, epic.id);
  expect(comments.some((row) => JSON.stringify(row).includes(comment))).toBeTruthy();
});
