import { expect, Page } from "@playwright/test";

export class AuthPage {
  constructor(private readonly page: Page) {}

  async goto(nextPath?: string): Promise<void> {
    const query = nextPath ? `?next=${encodeURIComponent(nextPath)}` : "";
    await this.page.goto(`/sign-in${query}`);
  }

  async signIn(email: string, password: string, nextPath?: string): Promise<void> {
    await this.goto(nextPath);
    await this.page.locator('input[name="email"]').first().fill(email);
    await this.page
      .getByRole("button", { name: /continue|sign in/i })
      .first()
      .click();
    await this.page.locator('input[name="password"]').first().fill(password);
    await this.page
      .getByRole("button", { name: /continue|sign in/i })
      .last()
      .click();
  }

  async expectSignedIn(): Promise<void> {
    await expect(this.page).not.toHaveURL(/\/sign-in/);
    await expect(this.page.getByRole("button", { name: /sign out|profile|account/i }).first()).toBeVisible();
  }

  async expectSignInPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/sign-in/);
    await expect(this.page.locator('input[name="password"]').first()).toBeVisible();
  }
}
