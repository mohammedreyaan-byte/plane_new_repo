import { expect, Page } from "@playwright/test";
import { ProjectCatalog } from "../support/types";
import { projectSettingsPath, settingsPath } from "./routes";

export class WorkspacePage {
  constructor(
    private readonly page: Page,
    private readonly catalog: ProjectCatalog
  ) {}

  async openWorkspaceSettings(): Promise<void> {
    await this.page.goto(settingsPath(this.catalog));
  }

  async expectWorkspaceSettingsVisible(): Promise<void> {
    await expect(this.page.getByRole("link", { name: /members/i }).first()).toBeVisible();
    await expect(this.page.getByRole("link", { name: /work item types/i }).first()).toBeVisible();
  }

  async expectRestrictedSettingsHidden(): Promise<void> {
    const labels = [/members/i, /work item types/i, /workflows/i, /service tokens/i, /integrations/i];
    await Promise.all(
      labels.map((label) => expect(this.page.getByRole("link", { name: label }).first()).toHaveCount(0))
    );
  }

  async openWorkflowSettings(): Promise<void> {
    await this.page.goto(projectSettingsPath(this.catalog, "workflows"));
  }

  async expectWorkflowStatesVisible(stateNames: string[]): Promise<void> {
    await Promise.all(
      stateNames.map((stateName) => expect(this.page.getByText(stateName, { exact: true }).first()).toBeVisible())
    );
  }
}
