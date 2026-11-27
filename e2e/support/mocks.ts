import { createHmac } from "node:crypto";
import { expect, request as playwrightRequest } from "@playwright/test";
import { JsonRecord, rowsOf } from "./api";

export function githubSignature(secret: string, body: string): string {
  return `sha256=${createHmac("sha256", secret).update(body).digest("hex")}`;
}

export interface MockWebhookEvent {
  deliveryId: string;
  event: string;
  issueId: string;
}

export async function sendMockWebhookEvent(
  baseUrl: string,
  secret: string | undefined,
  webhookEvent: MockWebhookEvent
): Promise<void> {
  const body = JSON.stringify({
    delivery_id: webhookEvent.deliveryId,
    event: webhookEvent.event,
    issue_id: webhookEvent.issueId,
  });
  const headers: Record<string, string> = {
    "X-Plane-Delivery": webhookEvent.deliveryId,
    "X-Plane-Event": webhookEvent.event,
  };
  if (secret) {
    headers["X-Plane-Signature"] = createHmac("sha256", secret).update(body).digest("hex");
  }
  const context = await playwrightRequest.newContext({ baseURL: baseUrl });
  try {
    const response = await context.post("/receiver/e2e/01", { data: body, headers });
    expect(response.ok(), `Webhook receiver returned HTTP ${response.status()}.`).toBeTruthy();
  } finally {
    await context.dispose();
  }
}

async function fetchJson(baseUrl: string, path: string): Promise<JsonRecord[]> {
  const context = await playwrightRequest.newContext({ baseURL: baseUrl });
  try {
    const response = await context.get(path);
    expect(response.ok(), `Mock endpoint ${baseUrl}${path} returned HTTP ${response.status()}.`).toBeTruthy();
    return rowsOf(await response.json());
  } finally {
    await context.dispose();
  }
}

export async function postMockRecord(baseUrl: string, path: string, record: JsonRecord): Promise<void> {
  const context = await playwrightRequest.newContext({ baseURL: baseUrl });
  try {
    const response = await context.post(path, { data: record });
    expect(response.ok(), `Mock endpoint ${baseUrl}${path} returned HTTP ${response.status()}.`).toBeTruthy();
  } finally {
    await context.dispose();
  }
}

export async function expectMockRecord(
  baseUrl: string,
  path: string,
  predicate: (record: JsonRecord) => boolean
): Promise<JsonRecord> {
  let match: JsonRecord | undefined;
  await expect
    .poll(
      async () => {
        const records = await fetchJson(baseUrl, path);
        match = records.find(predicate);
        return Boolean(match);
      },
      { message: `Expected a matching record from ${baseUrl}${path}` }
    )
    .toBe(true);
  if (!match) {
    throw new Error(`Mock endpoint ${baseUrl}${path} did not return a matching record.`);
  }
  return match;
}

export async function expectMockRecordCount(
  baseUrl: string,
  path: string,
  predicate: (record: JsonRecord) => boolean,
  expected: number
): Promise<void> {
  await expect.poll(async () => (await fetchJson(baseUrl, path)).filter(predicate).length).toBe(expected);
}

export async function expectMailpitMessage(mailpitUrl: string, recipient: string, subjectPart: string): Promise<void> {
  await expect
    .poll(async () => {
      const context = await playwrightRequest.newContext({ baseURL: mailpitUrl });
      try {
        const response = await context.get("/api/v1/messages");
        if (!response.ok()) {
          return false;
        }
        const messages = rowsOf(await response.json());
        return messages.some((message) => {
          const to = JSON.stringify(message["To"] ?? message["to"] ?? "");
          const subject = JSON.stringify(message["Subject"] ?? message["subject"] ?? "");
          return to.includes(recipient) && subject.toLowerCase().includes(subjectPart.toLowerCase());
        });
      } finally {
        await context.dispose();
      }
    })
    .toBe(true);
}
