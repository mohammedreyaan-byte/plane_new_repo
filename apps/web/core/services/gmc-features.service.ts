/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";

export type GmcProvider = "github" | "gitlab" | "slack";

export type AppIntegration = {
  id: string;
  provider: GmcProvider;
  title: string;
  description: string;
  network: number;
  verified: boolean;
  configured: boolean;
  scopes: string[];
};

export type WorkspaceIntegration = {
  id: string;
  provider: GmcProvider;
  provider_label: string;
  provider_account_id: string;
  account_name: string;
  host: string;
  scopes: string[];
  metadata: Record<string, unknown>;
  is_active: boolean;
  last_synced_at: string | null;
  created_at: string;
};

export type ExternalRepository = {
  id: string;
  provider: Exclude<GmcProvider, "slack">;
  external_id: string;
  full_name: string;
  url: string;
  is_sync_enabled: boolean;
  last_synced_at: string | null;
  metadata: Record<string, unknown>;
};

export type WebhookEvent = {
  id: string;
  provider: GmcProvider;
  event_type: string;
  delivery_id: string;
  signature_verified: boolean;
  status: string;
  work_item: string | null;
  work_item_identifier: string;
  detail: string;
  created_at: string;
};

export type WorkItemLink = {
  id: string;
  title: string | null;
  url: string;
  metadata: Record<string, unknown>;
  issue_id?: string;
  created_at?: string;
};

export type InitiativeChild = {
  id: string;
  name: string;
  type: "Module" | "Epic";
  owner: string;
  start_date: string | null;
  target_date: string | null;
  completed: boolean;
};

export type InitiativeStatus = "planned" | "active" | "completed" | "cancelled";

export type Initiative = {
  id: string;
  name: string;
  description: string;
  status: InitiativeStatus;
  start_date: string | null;
  target_date: string | null;
  owner: string | null;
  owner_detail: { id: string; display_name: string; email?: string } | null;
  module_ids: string[];
  epic_ids: string[];
  children: InitiativeChild[];
  progress: number;
  created_at: string;
  updated_at: string;
};

export type InitiativeOptions = {
  members: { id: string; display_name: string }[];
  modules: { id: string; name: string }[];
  epics: { id: string; name: string }[];
};

export type AutomationCondition = { field: string; operator: string; value: string };
export type AutomationAction = { type: string; value: string };

export type AutomationRule = {
  id: string;
  name: string;
  description: string;
  trigger: string;
  conditions: AutomationCondition[];
  actions: AutomationAction[];
  is_active: boolean;
  last_evaluated_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AutomationRun = {
  id: string;
  rule: string;
  rule_name: string;
  work_item: string | null;
  work_item_identifier: string;
  trigger: string;
  status: "success" | "failed" | "skipped";
  message: string;
  details: Record<string, unknown>;
  dry_run: boolean;
  created_at: string;
};

export type AutomationOptions = {
  work_items: { id: string; identifier: string; name: string }[];
  states: { id: string; name: string }[];
  labels: { id: string; name: string }[];
  members: { id: string; display_name: string }[];
  priorities: { value: string; label: string }[];
  types: { id: string; name: string }[];
};

export type ImportJob = {
  id: string;
  service: "csv" | "jira" | "github";
  status: "queued" | "processing" | "completed" | "failed";
  file_name: string;
  metadata: Record<string, unknown>;
  config: Record<string, unknown>;
  data: Record<string, unknown>;
  total_count: number;
  created_count: number;
  error_count: number;
  progress: number;
  error_log: string[];
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  initiated_by: string;
  initiated_by_detail: { id: string; display_name: string } | null;
};

export type SlackChannel = {
  id: string;
  channel_id: string;
  channel_name: string;
  member_count: number;
  is_default: boolean;
  events: Record<string, boolean>;
  is_active: boolean;
  last_posted_at: string | null;
  last_error: string;
};

export type SlackMessage = {
  id: string;
  provider: string;
  event_type: string;
  channel: string;
  work_item: string | null;
  work_item_identifier: string;
  status: string;
  provider_message_id: string;
  error: string;
  sent_at: string | null;
  created_at: string;
};

export type SlackSettings = {
  connected: boolean;
  integration?: WorkspaceIntegration;
  team_id?: string;
  team_name?: string;
  default_channel_id: string;
  channels: SlackChannel[];
  events: Record<string, boolean>;
  notifications: SlackMessage[];
  event_catalog: { key: string; label: string }[];
};

const unwrap = <T>(promise: Promise<{ data: T }>): Promise<T> =>
  promise.then((response) => response.data).catch((error) => Promise.reject(error?.response?.data ?? error));

/** Typed client for the five production GMC feature APIs. */
export class GmcFeaturesService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private projectBase(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}`;
  }

  private workspaceBase(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}`;
  }

  getAppIntegrations(workspaceSlug: string): Promise<AppIntegration[]> {
    return unwrap(this.get(`${this.workspaceBase(workspaceSlug)}/integrations/`));
  }

  getWorkspaceIntegrations(workspaceSlug: string): Promise<WorkspaceIntegration[]> {
    return unwrap(this.get(`${this.workspaceBase(workspaceSlug)}/workspace-integrations/`));
  }

  deleteWorkspaceIntegration(workspaceSlug: string, provider: GmcProvider): Promise<void> {
    return unwrap(this.delete(`${this.workspaceBase(workspaceSlug)}/workspace-integrations/${provider}/`));
  }

  authorizeIntegration(
    workspaceSlug: string,
    provider: GmcProvider
  ): Promise<{ authorize_url: string; state: string }> {
    return unwrap(this.post(`${this.workspaceBase(workspaceSlug)}/integrations/${provider}/oauth-authorize/`, {}));
  }

  getRepositories(workspaceSlug: string, provider: Exclude<GmcProvider, "slack">): Promise<ExternalRepository[]> {
    return unwrap(this.get(`${this.workspaceBase(workspaceSlug)}/workspace-integrations/${provider}/repositories/`));
  }

  syncRepositories(workspaceSlug: string, provider: Exclude<GmcProvider, "slack">): Promise<ExternalRepository[]> {
    return unwrap(
      this.post(`${this.workspaceBase(workspaceSlug)}/workspace-integrations/${provider}/repositories/`, {})
    );
  }

  updateRepository(
    workspaceSlug: string,
    provider: Exclude<GmcProvider, "slack">,
    repositoryId: string,
    isSyncEnabled: boolean
  ): Promise<ExternalRepository> {
    return unwrap(
      this.patch(
        `${this.workspaceBase(workspaceSlug)}/workspace-integrations/${provider}/repositories/${repositoryId}/`,
        {
          is_sync_enabled: isSyncEnabled,
        }
      )
    );
  }

  getWebhookEvents(workspaceSlug: string, provider: GmcProvider): Promise<WebhookEvent[]> {
    return unwrap(this.get(`${this.workspaceBase(workspaceSlug)}/workspace-integrations/${provider}/webhook-events/`));
  }

  getIssueLinks(workspaceSlug: string, projectId: string, issueId: string): Promise<WorkItemLink[]> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/issues/${issueId}/issue-links/`));
  }

  createIssueLink(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    data: { title: string; url: string; metadata?: Record<string, unknown> }
  ): Promise<WorkItemLink> {
    return unwrap(this.post(`${this.projectBase(workspaceSlug, projectId)}/issues/${issueId}/issue-links/`, data));
  }

  deleteIssueLink(workspaceSlug: string, projectId: string, issueId: string, linkId: string): Promise<void> {
    return unwrap(
      this.delete(`${this.projectBase(workspaceSlug, projectId)}/issues/${issueId}/issue-links/${linkId}/`)
    );
  }

  getInitiatives(workspaceSlug: string, projectId: string): Promise<Initiative[]> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/initiatives/`));
  }

  getInitiativeOptions(workspaceSlug: string, projectId: string): Promise<InitiativeOptions> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/initiatives/options/`));
  }

  createInitiative(workspaceSlug: string, projectId: string, data: Partial<Initiative>): Promise<Initiative> {
    return unwrap(this.post(`${this.projectBase(workspaceSlug, projectId)}/initiatives/`, data));
  }

  updateInitiative(
    workspaceSlug: string,
    projectId: string,
    initiativeId: string,
    data: Partial<Initiative>
  ): Promise<Initiative> {
    return unwrap(this.patch(`${this.projectBase(workspaceSlug, projectId)}/initiatives/${initiativeId}/`, data));
  }

  deleteInitiative(workspaceSlug: string, projectId: string, initiativeId: string): Promise<void> {
    return unwrap(this.delete(`${this.projectBase(workspaceSlug, projectId)}/initiatives/${initiativeId}/`));
  }

  getAutomationRules(workspaceSlug: string, projectId: string): Promise<AutomationRule[]> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/automation-rules/`));
  }

  createAutomationRule(
    workspaceSlug: string,
    projectId: string,
    data: Partial<AutomationRule>
  ): Promise<AutomationRule> {
    return unwrap(this.post(`${this.projectBase(workspaceSlug, projectId)}/automation-rules/`, data));
  }

  updateAutomationRule(
    workspaceSlug: string,
    projectId: string,
    ruleId: string,
    data: Partial<AutomationRule>
  ): Promise<AutomationRule> {
    return unwrap(this.patch(`${this.projectBase(workspaceSlug, projectId)}/automation-rules/${ruleId}/`, data));
  }

  deleteAutomationRule(workspaceSlug: string, projectId: string, ruleId: string): Promise<void> {
    return unwrap(this.delete(`${this.projectBase(workspaceSlug, projectId)}/automation-rules/${ruleId}/`));
  }

  getAutomationRuns(workspaceSlug: string, projectId: string): Promise<AutomationRun[]> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/automation-runs/`));
  }

  getAutomationOptions(workspaceSlug: string, projectId: string): Promise<AutomationOptions> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/automation-options/`));
  }

  testAutomationRule(
    workspaceSlug: string,
    projectId: string,
    ruleId: string,
    issueId: string
  ): Promise<{ run_ids: string[] }> {
    return unwrap(
      this.post(`${this.projectBase(workspaceSlug, projectId)}/automation-rules/${ruleId}/test/`, { issue_id: issueId })
    );
  }

  getImports(workspaceSlug: string, projectId: string): Promise<ImportJob[]> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/imports/`));
  }

  createCsvImport(workspaceSlug: string, projectId: string, file: File): Promise<ImportJob> {
    const formData = new FormData();
    formData.append("service", "csv");
    formData.append("file", file);
    return unwrap(this.post(`${this.projectBase(workspaceSlug, projectId)}/imports/`, formData));
  }

  createJiraImport(
    workspaceSlug: string,
    projectId: string,
    data: { site_url: string; email: string; api_token: string; project_key: string }
  ): Promise<ImportJob> {
    return unwrap(this.post(`${this.projectBase(workspaceSlug, projectId)}/imports/`, { service: "jira", ...data }));
  }

  createGithubImport(
    workspaceSlug: string,
    projectId: string,
    data: { token: string; owner: string; repo: string; include_issues: boolean; include_prs: boolean }
  ): Promise<ImportJob> {
    return unwrap(this.post(`${this.projectBase(workspaceSlug, projectId)}/imports/`, { service: "github", ...data }));
  }

  getImportErrors(workspaceSlug: string, projectId: string, jobId: string): Promise<string> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/imports/${jobId}/errors/`));
  }

  getSlackSettings(workspaceSlug: string): Promise<SlackSettings> {
    return unwrap(this.get(`${this.workspaceBase(workspaceSlug)}/slack/`));
  }

  updateSlackSettings(
    workspaceSlug: string,
    data: { default_channel_id?: string; events?: Record<string, boolean> }
  ): Promise<SlackSettings> {
    return unwrap(this.patch(`${this.workspaceBase(workspaceSlug)}/slack/`, data));
  }

  refreshSlackChannels(workspaceSlug: string): Promise<SlackChannel[]> {
    return unwrap(this.post(`${this.workspaceBase(workspaceSlug)}/slack/channels/`, {}));
  }

  sendSlackTest(workspaceSlug: string, channelId: string): Promise<{ log_id: string }> {
    return unwrap(this.post(`${this.workspaceBase(workspaceSlug)}/slack/test/`, { channel_id: channelId }));
  }

  disconnectSlack(workspaceSlug: string): Promise<void> {
    return unwrap(this.delete(`${this.workspaceBase(workspaceSlug)}/slack/`));
  }
}

export const gmcFeaturesService = new GmcFeaturesService();

/** Open a provider OAuth popup and resolve when the backend callback reports completion. */
export const startProviderOAuth = (
  workspaceSlug: string,
  provider: GmcProvider,
  service: GmcFeaturesService = gmcFeaturesService
): Promise<boolean> => {
  const popup = window.open("", `plane-${provider}-oauth`, "width=600,height=720,noopener=false");
  if (!popup) {
    return Promise.reject(new Error("Popup was blocked. Allow popups and try again."));
  }

  const apiOrigin = (() => {
    try {
      return new URL(API_BASE_URL).origin;
    } catch {
      return window.location.origin;
    }
  })();

  return new Promise<boolean>((resolve, reject) => {
    let settled = false;
    const finish = (success: boolean, message?: string) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMessage);
      popup.close();
      if (success) resolve(true);
      else reject(new Error(message ?? "Authorization was not completed."));
    };
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== apiOrigin && event.origin !== window.location.origin) return;
      const data = event.data as { success?: boolean; message?: string } | null;
      if (typeof data?.success !== "boolean") return;
      finish(data.success, data.message);
    };

    window.addEventListener("message", onMessage);
    service
      .authorizeIntegration(workspaceSlug, provider)
      .then(({ authorize_url }) => {
        popup.location.href = authorize_url;
        return authorize_url;
      })
      .catch((error) => finish(false, typeof error?.error === "string" ? error.error : undefined));
  });
};
