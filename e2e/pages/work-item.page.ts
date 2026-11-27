import { expect, Page } from "@playwright/test";
import { ProjectCatalog } from "../support/types";
import { issuePath, projectPath } from "./routes";

export class WorkItemPage {
  constructor(
    private readonly page: Page,
    private readonly catalog: ProjectCatalog
  ) {}

  async openList(): Promise<void> {
    await this.page.goto(projectPath(this.catalog, "issues"));
  }

  async open(issueId: string): Promise<void> {
    await this.page.goto(issuePath(this.catalog, issueId));
  }

  async createViaUi(name: string, typeLabel: string): Promise<void> {
    await this.openList();
    await this.page
      .getByRole("button", { name: /new work item|new issue|create issue/i })
      .first()
      .click();
    await this.page
      .locator('input[name="name"], input[placeholder*="title" i], textarea[placeholder*="title" i]')
      .first()
      .fill(name);
    const typeOption = this.page.getByRole("button", { name: new RegExp(typeLabel, "i") }).first();
    if ((await typeOption.count()) > 0) {
      await typeOption.click();
    }
    await this.page
      .getByRole("button", { name: /^create$/i })
      .first()
      .click();
    await expect(this.page.getByText(name, { exact: true }).first()).toBeVisible();
  }

  async expectNameVisible(name: string): Promise<void> {
    await expect(this.page.getByText(name, { exact: true }).first()).toBeVisible();
  }

  async expectNameHidden(name: string): Promise<void> {
    await expect(this.page.getByText(name, { exact: true }).first()).toHaveCount(0);
  }

  async expectBadgeVisible(label: string): Promise<void> {
    await expect(this.page.getByText(new RegExp(label, "i")).first()).toBeVisible();
  }

  async expectStateVisible(stateName: string): Promise<void> {
    await expect(this.page.getByText(stateName, { exact: true }).first()).toBeVisible();
  }

  async expectTransitionOptionHidden(stateName: string): Promise<void> {
    await expect(this.page.getByRole("menuitem", { name: stateName, exact: true })).toHaveCount(0);
  }

  async expectReadOnly(): Promise<void> {
    await expect(this.page.getByRole("button", { name: /^edit$/i })).toHaveCount(0);
    await expect(this.page.getByRole("button", { name: /change state/i })).toHaveCount(0);
  }

  async expectActivity(text: string): Promise<void> {
    await expect(this.page.getByText(new RegExp(text, "i")).first()).toBeVisible();
  }
}
