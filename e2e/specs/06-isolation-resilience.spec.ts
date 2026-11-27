import { type Page } from "@playwright/test";
import { expect, test } from "../fixtures";
import { BoardPage } from "../pages/board.page";
import { WorkItemPage } from "../pages/work-item.page";
import { PlaneApi } from "../support/api";
import { emailForRole } from "../support/env";
import { ProjectCatalog } from "../support/types";

const productionRun = process.env.E2E_ENV === "production";

test.skip(productionRun, "Production runs are limited to the separate read-only smoke suite.");

test.beforeEach(async ({ config }) => {
  test.skip(config.environment === "production", "Production runs are limited to the separate read-only smoke suite.");
});

function projectCatalogFor(
  catalog: ProjectCatalog,
  projectId: string,
  name: string,
  identifier: string
): ProjectCatalog {
  return {
    ...catalog,
    projectId,
    projectName: name,
    identifier,
  };
}

async function signInPreservingNextPath(page: Page, email: string, password: string): Promise<void> {
  const emailInput = page.locator('input[name="email"]').first();
  await expect(emailInput).toBeVisible();
  await emailInput.fill(email);
  await page
    .getByRole("button", { name: /continue|sign in/i })
    .first()
    .click();

  const passwordInput = page.locator('input[name="password"]').first();
  await expect(passwordInput).toBeVisible();
  await passwordInput.fill(password);
  await page
    .getByRole("button", { name: /continue|sign in/i })
    .last()
    .click();
}

test.describe("Project A member isolation", () => {
  test.use({ role: "member" });

  test("26. Project A member cannot open project B by URL or API", async ({
    adminApi,
    api,
    catalog,
    cleanup,
    page,
    uniqueName,
  }) => {
    const projectBName = uniqueName("Isolated project");
    const projectB = await adminApi.createProject(projectBName, `B${Date.now().toString().slice(-5)}`);
    const projectBId = String(projectB["id"] ?? "");
    expect(projectBId).not.toBe("");
    cleanup("project", projectBId);

    const projectResponse = await api.raw("GET", `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${projectBId}/`);
    expect(projectResponse.status).toBe(404);

    const workItemsResponse = await api.raw(
      "GET",
      `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${projectBId}/work-items/`
    );
    expect([403, 404]).toContain(workItemsResponse.status);

    await page.goto(`/${catalog.workspaceSlug}/projects/${projectBId}/issues`);
    await expect(page.getByText(/not found|404|access denied|forbidden/i).first()).toBeVisible();
  });

  test("27. Project B search term is hidden from a project A member", async ({
    adminApi,
    api,
    catalog,
    cleanup,
    uniqueName,
  }) => {
    const projectBName = uniqueName("Search isolated");
    const projectB = await adminApi.createProject(projectBName, `B${Date.now().toString().slice(-5)}`);
    const projectBId = String(projectB["id"] ?? "");
    expect(projectBId).not.toBe("");
    cleanup("project", projectBId);

    const catalogB = projectCatalogFor(catalog, projectBId, projectBName, "SEARCH-B");
    const term = uniqueName("secret-search-term");
    const issue = await adminApi.createIssue(catalogB, { name: term, type: "task" });
    const issueId = String(issue["id"] ?? "");
    expect(issueId).not.toBe("");

    try {
      const globalSearch = await api.raw("GET", `/api/workspaces/${catalog.workspaceSlug}/search/`, {
        query: { search: term, workspace_search: true },
      });
      expect(globalSearch.status).toBe(200);
      expect(JSON.stringify(globalSearch.data ?? globalSearch.text ?? "")).not.toContain(term);

      const projectSearch = await api.raw(
        "GET",
        `/api/workspaces/${catalog.workspaceSlug}/projects/${projectBId}/search-issues/`,
        { query: { search: term, workspace_search: false } }
      );
      expect(projectSearch.status).toBe(200);
      expect(JSON.stringify(projectSearch.data ?? projectSearch.text ?? "")).not.toContain(term);
    } finally {
      await adminApi.deleteIssue(catalogB, issueId);
    }
  });
});

test("28. Refresh during a drag does not lose the work item transition", async ({
  adminApi,
  catalog,
  page,
  workItem,
}) => {
  const item = await workItem("bug", "Refresh during drag");
  const board = new BoardPage(page, catalog);
  await board.open("bug");
  await board.dragCard(item.name, "In Progress");
  await page.reload();

  await expect
    .poll(async () => String((await adminApi.getIssue(catalog, item.id))["state_id"] ?? ""))
    .toBe(catalog.states["In Progress"]?.id ?? "");

  const workItems = new WorkItemPage(page, catalog);
  await workItems.expectNameVisible(item.name);
});

test("29. Concurrent edits end in a conflict or a clean last-write result", async ({
  adminApi,
  catalog,
  config,
  page,
  workItem,
}) => {
  const item = await workItem("task", "Concurrent edit");
  const memberApi = await PlaneApi.create(config, "member");
  try {
    const firstName = `${item.name} admin edit`;
    const secondName = `${item.name} member edit`;
    await adminApi.patchIssue(catalog, item.id, { name: firstName });

    const second = await memberApi.raw("PATCH", `${adminApi.workItemBase(catalog)}/${item.id}/`, {
      body: { name: secondName },
    });
    expect([200, 409]).toContain(second.status);

    await expect
      .poll(async () => String((await adminApi.getIssue(catalog, item.id))["name"] ?? ""))
      .toBe(second.status === 200 ? secondName : firstName);

    const workItems = new WorkItemPage(page, catalog);
    await workItems.open(item.id);
    await expect(page.getByText(/application error|something went wrong/i).first()).toHaveCount(0);
  } finally {
    await memberApi.close();
  }
});

test("30. Expired session redirects to sign-in and returns to the same work item", async ({
  catalog,
  config,
  page,
  workItem,
}) => {
  const item = await workItem("task", "Session expiry");
  const originalPath = `/${catalog.workspaceSlug}/projects/${catalog.projectId}/issues/${item.id}`;
  await page.goto(originalPath);

  await page.context().clearCookies();
  await page.reload();

  await expect.poll(() => new URL(page.url()).searchParams.get("next_path") ?? "").toBe(originalPath);
  await signInPreservingNextPath(page, emailForRole(config, "admin"), config.password);

  await expect.poll(() => new URL(page.url()).pathname).toBe(originalPath);

  const workItems = new WorkItemPage(page, catalog);
  await workItems.expectNameVisible(item.name);
});
