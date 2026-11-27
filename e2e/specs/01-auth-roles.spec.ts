import { expect, test } from "../fixtures";
import { AuthPage } from "../pages/auth.page";
import { WorkItemPage } from "../pages/work-item.page";
import { WorkspacePage } from "../pages/workspace.page";
import { emailForRole } from "../support/env";
import { findMemberId } from "../support/members";

test("1. Admin signs in and sees workspace settings @smoke @production-smoke", async ({
  anonymousPage,
  catalog,
  config,
  page,
}) => {
  const auth = new AuthPage(anonymousPage);
  await auth.signIn(emailForRole(config, "admin"), config.password);
  await auth.expectSignedIn();

  const workspace = new WorkspacePage(page, catalog);
  await workspace.openWorkspaceSettings();
  await workspace.expectWorkspaceSettingsVisible();
});

test.describe("Developer role", () => {
  test.use({ role: "developer" });

  test("2. Developer cannot see admin-only settings", async ({ catalog, page }) => {
    const workspace = new WorkspacePage(page, catalog);
    await workspace.openWorkspaceSettings();
    await workspace.expectRestrictedSettingsHidden();
  });
});

test.describe("QA role", () => {
  test.use({ role: "qa" });

  test("3. QA can reach the Bug workflow states", async ({ catalog, page }) => {
    const workspace = new WorkspacePage(page, catalog);
    await workspace.openWorkflowSettings();
    await workspace.expectWorkflowStatesVisible([
      "New",
      "In Progress",
      "Code Review",
      "In Testing",
      "Tested",
      "Closed",
    ]);
  });
});

test.describe("Viewer role", () => {
  test.use({ role: "viewer" });

  test("4. Viewer sees read-only work items and direct writes fail", async ({
    adminApi,
    api,
    catalog,
    page,
    workItem,
  }) => {
    const item = await workItem("bug", "Viewer readonly");
    const workItems = new WorkItemPage(page, catalog);
    await workItems.open(item.id);
    await workItems.expectReadOnly();

    const directWrite = await api.raw(
      "PATCH",
      `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/work-items/${item.id}/`,
      { body: { name: "Viewer must not write" } }
    );
    expect(directWrite.status).toBe(403);
    const unchanged = await adminApi.getIssue(catalog, item.id);
    expect(unchanged["name"]).toBe(item.name);
  });
});

test.describe("Guest role", () => {
  test.use({ role: "guest" });

  test("5. Guest sees only assigned work items", async ({ adminApi, api, catalog, config, page }) => {
    const members = await adminApi.workspaceMembers();
    const guestId = findMemberId(members, emailForRole(config, "guest"));
    const adminId = findMemberId(members, emailForRole(config, "admin"));
    const guestItem = await adminApi.createIssue(catalog, {
      name: `${config.runId} guest assigned`,
      type: "task",
      assigneeIds: [guestId],
    });
    const otherItem = await adminApi.createIssue(catalog, {
      name: `${config.runId} not for guest`,
      type: "task",
      assigneeIds: [adminId],
    });
    const guestItemId = String(guestItem["id"] ?? "");
    const otherItemId = String(otherItem["id"] ?? "");

    try {
      const visibleIds = (await api.listIssues(catalog, { per_page: 100 })).map((row) => String(row["id"] ?? ""));
      expect(visibleIds).toContain(guestItemId);
      expect(visibleIds).not.toContain(otherItemId);
      const workItems = new WorkItemPage(page, catalog);
      await workItems.openList();
      await workItems.expectNameVisible(String(guestItem["name"] ?? ""));
      await workItems.expectNameHidden(String(otherItem["name"] ?? ""));
    } finally {
      await adminApi.deleteIssue(catalog, guestItemId);
      await adminApi.deleteIssue(catalog, otherItemId);
    }
  });
});
