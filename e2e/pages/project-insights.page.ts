import { expect, Page } from "@playwright/test";
import { ProjectCatalog } from "../support/types";
import { projectPath } from "./routes";

export class ProjectInsightsPage {
  constructor(
    private readonly page: Page,
    private readonly catalog: ProjectCatalog
  ) {}

  async openCycle(cycleId: string): Promise<void> {
    await this.page.goto(projectPath(this.catalog, `cycles/${cycleId}`));
  }

  async openModule(moduleId: string): Promise<void> {
    await this.page.goto(projectPath(this.catalog, `modules/${moduleId}`));
  }

  async openReports(): Promise<void> {
    await this.page.goto(projectPath(this.catalog, "reports"));
  }

  async expectText(text: string | RegExp): Promise<void> {
    const pattern = typeof text === "string" ? new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i") : text;
    await expect(this.page.getByText(pattern).first()).toBeVisible();
  }

  async expectProgress(percentage: number): Promise<void> {
    await expect(this.page.getByText(new RegExp(`\\b${percentage}%?\\b`)).first()).toBeVisible();
  }

  async expectDownload(): Promise<void> {
    const downloadPromise = this.page.waitForEvent("download");
    await this.page
      .getByRole("button", { name: /export|download/i })
      .first()
      .click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.csv$/i);
  }
}
