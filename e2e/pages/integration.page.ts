import { expect, Page } from "@playwright/test";
import { ProjectCatalog } from "../support/types";
import { settingsPath } from "./routes";

export class IntegrationPage {
  constructor(
    private readonly page: Page,
    private readonly catalog: ProjectCatalog
  ) {}

  async openIntegrations(): Promise<void> {
    await this.page.goto(settingsPath(this.catalog, "integrations"));
  }

  async openApiTokens(): Promise<void> {
    await this.page.goto("/settings/profile/api-tokens");
  }

  async expectGitLinkedReference(identifier: string): Promise<void> {
    await expect(this.page.getByTestId("git-linked-reference").getByText(identifier, { exact: false })).toBeVisible();
  }

  async expectGitEvent(identifier: string): Promise<void> {
    await expect(this.page.getByTestId("git-webhook-event").getByText(identifier, { exact: false })).toBeVisible();
  }

  async expectSlackMessage(text: string): Promise<void> {
    await expect(this.page.getByTestId("slack-notification").getByText(text, { exact: false })).toBeVisible();
  }

  async expectNoSlackMessage(text: string): Promise<void> {
    await expect(this.page.getByTestId("slack-notification").getByText(text, { exact: false })).toHaveCount(0);
  }
}
