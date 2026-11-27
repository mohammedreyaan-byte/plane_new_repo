import { expect, Page } from "@playwright/test";

export class NotificationPage {
  constructor(private readonly page: Page) {}

  async openInApp(): Promise<void> {
    await this.page.goto("/notifications");
  }

  async expectNotification(text: string): Promise<void> {
    await expect(this.page.getByText(new RegExp(text, "i")).first()).toBeVisible();
  }

  async expectNoNotification(text: string): Promise<void> {
    await expect(this.page.getByText(new RegExp(text, "i")).first()).toHaveCount(0);
  }
}
