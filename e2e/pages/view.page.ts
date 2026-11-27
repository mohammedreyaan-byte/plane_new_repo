import { expect, Page } from "@playwright/test";
import { ProjectCatalog } from "../support/types";
import { projectPath } from "./routes";

export class ViewPage {
  constructor(
    private readonly page: Page,
    private readonly catalog: ProjectCatalog
  ) {}

  async openList(): Promise<void> {
    await this.page.goto(projectPath(this.catalog, "views"));
  }

  async open(viewId: string): Promise<void> {
    await this.page.goto(projectPath(this.catalog, `views/${viewId}`));
  }

  async expectViewVisible(name: string): Promise<void> {
    await expect(this.page.getByText(name, { exact: true }).first()).toBeVisible();
  }

  async expectResultCount(count: number): Promise<void> {
    await expect(this.page.getByText(new RegExp(`\\b${count}\\b`)).first()).toBeVisible();
  }

  async expectReadOnly(): Promise<void> {
    await expect(this.page.getByRole("button", { name: /edit view|save view|delete view/i })).toHaveCount(0);
  }
}
