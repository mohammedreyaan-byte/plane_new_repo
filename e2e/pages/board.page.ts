import { expect, Page } from "@playwright/test";
import { ProjectCatalog } from "../support/types";
import { projectPath } from "./routes";

export class BoardPage {
  constructor(
    private readonly page: Page,
    private readonly catalog: ProjectCatalog
  ) {}

  async open(typeKey?: string): Promise<void> {
    const query = new URLSearchParams({ layout: "board" });
    if (typeKey) {
      query.set("type_id", this.catalog.types[typeKey]?.id ?? typeKey);
    }
    await this.page.goto(`${projectPath(this.catalog, "issues")}?${query.toString()}`);
  }

  async expectColumns(stateNames: string[]): Promise<void> {
    await Promise.all(
      stateNames.map((stateName) => expect(this.page.getByText(stateName, { exact: true }).first()).toBeVisible())
    );
  }

  async dragCard(cardName: string, columnName: string): Promise<void> {
    await this.page
      .getByText(cardName, { exact: true })
      .first()
      .dragTo(this.page.getByText(columnName, { exact: true }).first());
  }

  async expectCardInColumn(cardName: string, columnName: string): Promise<void> {
    const column = this.page.getByText(columnName, { exact: true }).first();
    await expect(
      column.locator("xpath=ancestor::*[self::div or self::section][1]").getByText(cardName, { exact: true })
    ).toBeVisible();
  }

  async expectBlockReason(reason: string | RegExp): Promise<void> {
    const pattern = reason instanceof RegExp ? reason : new RegExp(reason, "i");
    await expect(this.page.getByText(pattern).first()).toBeVisible();
  }
}
