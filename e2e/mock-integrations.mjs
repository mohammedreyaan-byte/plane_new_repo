// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

/**
 * Credential-free in-process mock for PLN-026 integration scenarios.
 *
 * It records webhook/message payloads in memory so the GitHub and Slack E2E
 * scenarios can assert delivery without contacting a real provider. It does
 * not contain provider credentials or generate secret-looking values.
 */

import { createHmac, timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";

const port = Number(process.env.MOCK_INTEGRATIONS_PORT ?? 8787);
const webhookSecret = process.env.MOCK_WEBHOOK_SECRET ?? "";
const stores = { events: [], messages: [], webhooks: [], links: [], records: [] };
const seenDeliveries = new Set();
const maxBodyBytes = 1024 * 1024;

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  response.end(body);
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > maxBodyBytes) {
        reject(new Error("request body too large"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    request.on("error", reject);
  });
}

async function parseBody(request) {
  const raw = await readBody(request);
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return { raw };
  }
}

function signatureIsValid(rawBody, header) {
  if (!webhookSecret) return false;
  if (typeof header !== "string" || header.length === 0) return false;
  const expected = createHmac("sha256", webhookSecret).update(rawBody).digest();
  const provided = Buffer.from(header, "hex");
  return expected.length === provided.length && timingSafeEqual(expected, provided);
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (request.method === "GET" && path === "/health") {
    sendJson(response, 200, { status: "ok" });
    return;
  }

  if (request.method === "GET" && path === "/favicon.ico") {
    response.writeHead(204);
    response.end();
    return;
  }

  if (path === "/events" || path === "/messages" || path === "/webhooks") {
    const store = stores[path.slice(1)];
    if (request.method === "GET") {
      sendJson(response, 200, store);
      return;
    }
    if (request.method === "POST") {
      const record = await parseBody(request);
      store.push({ ...record, received_at: new Date().toISOString() });
      sendJson(response, 201, { recorded: true });
      return;
    }
  }

  if (path === "/links" && request.method === "GET") {
    const issueId = url.searchParams.get("issue_id");
    const links = issueId ? stores.links.filter((link) => String(link.issue_id) === issueId) : stores.links;
    sendJson(response, 200, links);
    return;
  }

  if (path === "/records" && request.method === "GET") {
    sendJson(response, 200, stores.records);
    return;
  }

  if (request.method === "POST" && path === "/receiver/e2e/01") {
    const raw = await readBody(request);
    let record = {};
    try {
      record = raw ? JSON.parse(raw) : {};
    } catch {
      sendJson(response, 400, { error: "invalid json" });
      return;
    }
    const deliveryId = String(request.headers["x-plane-delivery"] ?? record["delivery_id"] ?? "");
    const signatureVerified = signatureIsValid(raw, request.headers["x-plane-signature"]);
    if (webhookSecret && !signatureVerified) {
      sendJson(response, 401, { error: "invalid signature" });
      return;
    }
    const stored = {
      ...record,
      delivery_id: deliveryId || null,
      deliveryId: deliveryId || null,
      event: request.headers["x-plane-event"] ?? record["event"] ?? null,
      issue_id: record["issue_id"] ?? null,
      signature_verified: signatureVerified,
      received_at: new Date().toISOString(),
    };
    const duplicate = seenDeliveries.has(deliveryId);
    if (!duplicate) {
      seenDeliveries.add(deliveryId);
      stores.webhooks.push(stored);
      stores.records.push(stored);
      if (record["issue_id"] && record["event"]) {
        stores.links.push({
          issue_id: record["issue_id"],
          event: record["event"],
          delivery_id: deliveryId,
          received_at: stored.received_at,
        });
      }
    }
    sendJson(response, 200, { received: true, duplicate });
    return;
  }

  sendJson(response, 404, { error: "not found" });
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`PLN-026 mock integrations listening on http://127.0.0.1:${port}\n`);
});
