import { expect, Page } from "@playwright/test";
import { ProjectCatalog } from "../support/types";
import { projectPath } from "./routes";

export class BacklogPage {
  constructor(
    private readonly page: Page,
    private readonly catalog: ProjectCatalog
  ) {}

  async open(): Promise<void> {
    await this.page.goto(projectPath(this.catalog, "backlog"));
  }

  async rank(firstName: string, secondName: string): Promise<void> {
    await this.page
      .getByText(firstName, { exact: true })
      .first()
      .dragTo(this.page.getByText(secondName, { exact: true }).first());
  }

  async expectOrder(names: string[]): Promise<void> {
    const texts = await this.page.locator("body").innerText();
    const indexes = names.map((name) => texts.indexOf(name));
    expect(indexes.every((index) => index >= 0)).toBeTruthy();
    expect([...indexes].toSorted((left, right) => left - right)).toEqual(indexes);
  }

  async moveToCycle(itemName: string, cycleName: string): Promise<void> {
    await this.page.getByText(itemName, { exact: true }).first().click();
    await this.page
      .getByRole("button", { name: /add to cycle|cycle/i })
      .first()
      .click();
    await this.page.getByText(cycleName, { exact: true }).first().click();
  }
}
