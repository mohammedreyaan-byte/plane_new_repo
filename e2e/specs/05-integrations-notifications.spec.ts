import { request as playwrightRequest } from "@playwright/test";
import { expect, test } from "../fixtures";
import { NotificationPage } from "../pages/notification.page";
import { WorkItemPage } from "../pages/work-item.page";
import { JsonRecord, rowsOf } from "../support/api";
import { emailForRole } from "../support/env";
import { findMemberId } from "../support/members";
import {
  expectMailpitMessage,
  expectMockRecord,
  expectMockRecordCount,
  githubSignature,
  sendMockWebhookEvent,
} from "../support/mocks";

const productionRun = process.env.E2E_ENV === "production";

test.skip(productionRun, "Production runs are limited to the separate read-only smoke suite.");

function requiredConfig(value: string | undefined, name: string): string {
  if (!value) {
    throw new Error(`${name} is required for this PLN-026 scenario; missing configuration must fail the run.`);
  }
  return value;
}

test.beforeEach(async ({ config }) => {
  test.skip(config.environment === "production", "Production runs are limited to the separate read-only smoke suite.");
});

async function countMailpitMessages(baseUrl: string, recipient: string, subjectPart: string): Promise<number> {
  const context = await playwrightRequest.newContext({ baseURL: baseUrl });
  try {
    const response = await context.get("/api/v1/messages");
    if (!response.ok()) {
      return 0;
    }
    const messages = rowsOf(await response.json());
    return messages.filter((message) => {
      const to = JSON.stringify(message["To"] ?? message["to"] ?? "");
      const subject = JSON.stringify(message["Subject"] ?? message["subject"] ?? "");
      return to.includes(recipient) && subject.toLowerCase().includes(subjectPart.toLowerCase());
    }).length;
  } finally {
    await context.dispose();
  }
}

test("21. Service token changes and comments on a scoped item and rejects project B", async ({
  adminApi,
  catalog,
  cleanup,
  config,
  serviceApi,
  uniqueName,
}) => {
  requiredConfig(config.serviceToken, "E2E_SERVICE_TOKEN");
  if (!serviceApi) {
    throw new Error(
      "The service API fixture is unavailable; E2E_SERVICE_TOKEN must be provisioned outside the seed command."
    );
  }

  const item = await adminApi.createIssue(catalog, { name: uniqueName("Service token item"), type: "bug" });
  const issueId = String(item["id"] ?? "");
  expect(issueId).not.toBe("");
  cleanup("issue", issueId);

  const transition = await serviceApi.transition(catalog, issueId, "In Progress");
  expect(transition.status).toBe(200);

  const comment = uniqueName("Service token comment");
  const commentResult = await serviceApi.addComment(catalog, issueId, comment);
  expect(String(commentResult["id"] ?? "")).not.toBe("");

  await expect
    .poll(async () => String((await adminApi.getIssue(catalog, issueId))["state_id"] ?? ""))
    .toBe(catalog.states["In Progress"]?.id ?? "");
  await expect.poll(async () => JSON.stringify(await adminApi.comments(catalog, issueId))).toContain(comment);

  const projectBName = uniqueName("Project B");
  const projectB = await adminApi.createProject(projectBName, `B${Date.now().toString().slice(-5)}`);
  const projectBId = String(projectB["id"] ?? "");
  expect(projectBId).not.toBe("");
  cleanup("project", projectBId);

  const crossProject = await serviceApi.raw(
    "GET",
    `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${projectBId}/work-items/`
  );
  expect(crossProject.status).toBe(403);
});

test("22. Signed GitHub PR links to the referenced work item", async ({
  adminApi,
  catalog,
  cleanup,
  config,
  page,
  uniqueName,
}) => {
  const githubUrl = requiredConfig(config.githubMockUrl, "E2E_GITHUB_MOCK_URL");
  const secret = requiredConfig(config.githubWebhookSecret, "E2E_GITHUB_WEBHOOK_SECRET");
  const issue = await adminApi.createIssue(catalog, { name: uniqueName("GitHub link"), type: "story" });
  const issueId = String(issue["id"] ?? "");
  expect(issueId).not.toBe("");
  cleanup("issue", issueId);

  const reference = `${catalog.identifier}-${String(issue["sequence_id"] ?? "1")}`;
  const prUrl = `${githubUrl}/pull/${String(issue["sequence_id"] ?? "1")}`;
  const deliveryId = `e2e-github-${config.runId}-${issueId}`;
  const title = `${reference} E2E-1 GitHub link`;
  const payload = JSON.stringify({
    action: "opened",
    title,
    body: `Implements ${reference}`,
    html_url: prUrl,
    pull_request: { title, html_url: prUrl },
  });
  const response = await adminApi.postRaw(`/api/webhooks/github/?workspace=${catalog.workspaceSlug}`, payload, {
    "X-Hub-Signature-256": githubSignature(secret, payload),
    "X-GitHub-Event": "pull_request",
    "X-GitHub-Delivery": deliveryId,
  });
  expect(response.status).toBe(202);

  await expectMockRecord(githubUrl, "/events", (record) => JSON.stringify(record).includes(deliveryId));

  const linksPath = `${adminApi.workItemBase(catalog)}/${issueId}/links/`;
  await expect
    .poll(async () => {
      const links = await adminApi.raw("GET", linksPath);
      return JSON.stringify(links.data ?? links.text ?? "");
    })
    .toContain(prUrl);

  const workItems = new WorkItemPage(page, catalog);
  await workItems.open(issueId);
  await expect(page.getByTestId("git-linked-reference").locator(`a[href="${prUrl}"]`)).toBeVisible();
});

test("23. Slack posts a selected state change but not an unselected comment event", async ({
  adminApi,
  api,
  catalog,
  cleanup,
  config,
  uniqueName,
}) => {
  const slackUrl = requiredConfig(config.slackMockUrl, "E2E_SLACK_MOCK_URL");
  const slackPath = `/api/workspaces/${catalog.workspaceSlug}/slack/`;
  const settings = (await adminApi.json<JsonRecord>("GET", slackPath)).data;
  const channels = Array.isArray(settings["channels"]) ? (settings["channels"] as JsonRecord[]) : [];
  if (settings["connected"] !== true || channels.length === 0) {
    throw new Error("An active local Slack mock integration with a channel is required; seed_e2e must provision it.");
  }

  const originalEvents: JsonRecord =
    settings["events"] && typeof settings["events"] === "object" ? (settings["events"] as JsonRecord) : {};
  const selectedEvents: JsonRecord = {};
  for (const key of Object.keys(originalEvents)) {
    selectedEvents[key] = false;
  }
  selectedEvents["work_item.state_changed"] = true;

  const selectedIssue = async (label: string): Promise<{ id: string; reference: string }> => {
    const issue = await adminApi.createIssue(catalog, { name: uniqueName(label), type: "task" });
    const id = String(issue["id"] ?? "");
    expect(id).not.toBe("");
    cleanup("issue", id);
    return { id, reference: `${catalog.identifier}-${String(issue["sequence_id"] ?? "1")}` };
  };

  try {
    await adminApi.json("PATCH", slackPath, { body: { events: selectedEvents } });

    const first = await selectedIssue("Slack state event");
    expect((await api.transition(catalog, first.id, "In Progress")).status).toBe(200);

    const firstStateMessage = (record: JsonRecord): boolean => {
      const serialized = JSON.stringify(record);
      return serialized.includes(first.reference) && serialized.includes("work_item.state_changed");
    };
    await expectMockRecord(slackUrl, "/messages", firstStateMessage);
    await expectMockRecordCount(slackUrl, "/messages", firstStateMessage, 1);

    await adminApi.addComment(catalog, first.id, uniqueName("Slack unselected event"));
    await expect.poll(async () => (await adminApi.comments(catalog, first.id)).length).toBeGreaterThan(0);

    // A second selected event lets the worker queue finish before asserting the
    // unselected event produced nothing for the first work item.
    const second = await selectedIssue("Slack queue marker");
    expect((await api.transition(catalog, second.id, "In Progress")).status).toBe(200);
    await expectMockRecord(
      slackUrl,
      "/messages",
      (record) =>
        JSON.stringify(record).includes(second.reference) && JSON.stringify(record).includes("work_item.state_changed")
    );

    await expectMockRecordCount(
      slackUrl,
      "/messages",
      (record) =>
        JSON.stringify(record).includes(first.reference) && JSON.stringify(record).includes("work_item.commented"),
      0
    );
    await expectMockRecordCount(slackUrl, "/messages", firstStateMessage, 1);
  } finally {
    await adminApi.json("PATCH", slackPath, { body: { events: originalEvents } });
  }
});

test.describe("Assignment notifications", () => {
  test.use({ role: "member" });

  test("24. Assignee receives in-app and email notification while the actor receives neither", async ({
    adminApi,
    api,
    catalog,
    cleanup,
    config,
    page,
    uniqueName,
  }) => {
    const mailpitUrl = requiredConfig(config.mailpitUrl, "E2E_MAILPIT_URL");
    const memberEmail = emailForRole(config, "member");
    const actorEmail = emailForRole(config, "admin");
    const memberId = findMemberId(await adminApi.workspaceMembers(), memberEmail);
    const name = uniqueName("Assigned notification");
    const issue = await adminApi.createIssue(catalog, { name, type: "task" });
    const issueId = String(issue["id"] ?? "");
    expect(issueId).not.toBe("");
    cleanup("issue", issueId);

    await adminApi.patchIssue(catalog, issueId, { assignee_ids: [memberId] });

    await expect.poll(async () => JSON.stringify(await api.notifications())).toContain(name);
    expect(JSON.stringify(await adminApi.notifications())).not.toContain(name);

    const notifications = new NotificationPage(page);
    await notifications.openInApp();
    await notifications.expectNotification(name);

    await expectMailpitMessage(mailpitUrl, memberEmail, name);
    await expect.poll(async () => countMailpitMessages(mailpitUrl, actorEmail, name)).toBe(0);
  });
});

test("25. Signed webhook event is received once despite duplicate delivery", async ({
  adminApi,
  catalog,
  cleanup,
  config,
  uniqueName,
}) => {
  const webhookSecret = requiredConfig(config.webhookSecret, "E2E_WEBHOOK_SECRET");
  const issue = await adminApi.createIssue(catalog, { name: uniqueName("Webhook event"), type: "bug" });
  const issueId = String(issue["id"] ?? "");
  expect(issueId).not.toBe("");
  cleanup("issue", issueId);

  const deliveryId = `e2e-webhook-${config.runId}-${issueId}`;
  const signedEvent = { deliveryId, event: "issue.updated", issueId };
  await sendMockWebhookEvent(config.webhookReceiverUrl, webhookSecret, signedEvent);
  await sendMockWebhookEvent(config.webhookReceiverUrl, webhookSecret, signedEvent);

  await expectMockRecordCount(
    config.webhookReceiverUrl,
    `/links?issue_id=${encodeURIComponent(issueId)}`,
    (record) => String(record["issue_id"] ?? "") === issueId,
    1
  );

  await adminApi.patchIssue(catalog, issueId, { name: uniqueName("Webhook event updated") });
  await expectMockRecord(
    config.webhookReceiverUrl,
    "/records",
    (record) =>
      String(record["issue_id"] ?? "") === issueId &&
      record["signature_verified"] === true &&
      String(record["delivery_id"] ?? record["deliveryId"] ?? "") === deliveryId
  );
});
