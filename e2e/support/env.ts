export const ROLE_KEYS = ["admin", "member", "developer", "qa", "viewer", "guest"] as const;

export type Role = (typeof ROLE_KEYS)[number];
export type EnvironmentName = "local" | "staging" | "production";

export interface E2eConfig {
  baseUrl: string;
  environment: EnvironmentName;
  workspaceSlug: string;
  projectName: string;
  projectIdentifier: string;
  password: string;
  serviceToken?: string;
  webhookReceiverUrl: string;
  webhookSecret?: string;
  githubMockUrl?: string;
  githubWebhookSecret?: string;
  slackMockUrl?: string;
  mailpitUrl?: string;
  runId: string;
  productionSmokeAllowed: boolean;
}

const ENVIRONMENTS: readonly EnvironmentName[] = ["local", "staging", "production"];

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} must be set for the PLN-026 suite.`);
  }
  return value;
}

function requiredUrl(name: string): string {
  const value = required(name);
  try {
    return new URL(value).toString().replace(/\/+$/, "");
  } catch {
    throw new Error(`${name} must be an absolute URL.`);
  }
}

function optional(name: string): string | undefined {
  const value = process.env[name];
  return value && value.length > 0 ? value : undefined;
}

function isEnvironmentName(value: string): value is EnvironmentName {
  return ENVIRONMENTS.includes(value as EnvironmentName);
}

function normalizeUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

function optionalUrl(name: string): string | undefined {
  const value = optional(name);
  return value ? normalizeUrl(value) : undefined;
}

export function loadEnv(): E2eConfig {
  const environment = process.env.E2E_ENV ?? "local";
  if (!isEnvironmentName(environment)) {
    throw new Error(`E2E_ENV must be one of ${ENVIRONMENTS.join(", ")}; received ${environment}.`);
  }

  if (environment === "production" && process.env.E2E_ALLOW_PRODUCTION_SMOKE !== "1") {
    throw new Error(
      "Refusing to run the PLN-026 suite against production. Set E2E_ALLOW_PRODUCTION_SMOKE=1 only for the read-only production smoke subset."
    );
  }

  // Staging and explicitly marked full runs must fail on missing configuration.
  // Silent skips are not acceptable for release evidence. Production smoke only
  // needs the base URL and password because destructive scenarios are blocked.
  const nonLocalRun = environment !== "local";
  const fullIntegrationRun = environment === "staging" || process.env.E2E_REQUIRE_FULL_CONFIG === "1";

  return {
    baseUrl: nonLocalRun
      ? requiredUrl("E2E_BASE_URL")
      : normalizeUrl(process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000"),
    environment,
    workspaceSlug: process.env.E2E_WORKSPACE_SLUG ?? "e2e",
    projectName: process.env.E2E_PROJECT_NAME ?? "E2E",
    projectIdentifier: process.env.E2E_PROJECT_IDENTIFIER ?? "E2E",
    password: required("E2E_TEST_PASSWORD"),
    serviceToken: fullIntegrationRun ? required("E2E_SERVICE_TOKEN") : optional("E2E_SERVICE_TOKEN"),
    webhookReceiverUrl: normalizeUrl(process.env.E2E_WEBHOOK_RECEIVER_URL ?? "http://127.0.0.1:8787"),
    webhookSecret: fullIntegrationRun ? required("E2E_WEBHOOK_SECRET") : optional("E2E_WEBHOOK_SECRET"),
    githubMockUrl: fullIntegrationRun ? requiredUrl("E2E_GITHUB_MOCK_URL") : optionalUrl("E2E_GITHUB_MOCK_URL"),
    githubWebhookSecret: fullIntegrationRun
      ? required("E2E_GITHUB_WEBHOOK_SECRET")
      : optional("E2E_GITHUB_WEBHOOK_SECRET"),
    slackMockUrl: fullIntegrationRun ? requiredUrl("E2E_SLACK_MOCK_URL") : optionalUrl("E2E_SLACK_MOCK_URL"),
    mailpitUrl: fullIntegrationRun ? requiredUrl("E2E_MAILPIT_URL") : optionalUrl("E2E_MAILPIT_URL"),
    runId: process.env.E2E_RUN_ID ?? `run-${Date.now()}`,
    productionSmokeAllowed: process.env.E2E_ALLOW_PRODUCTION_SMOKE === "1",
  };
}

export function emailForRole(config: E2eConfig, role: Role): string {
  return `e2e-${role}@${config.workspaceSlug}.example.invalid`;
}
