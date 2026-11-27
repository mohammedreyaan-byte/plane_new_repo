import { APIRequestContext, request as playwrightRequest } from "@playwright/test";
import { E2eConfig, Role, emailForRole } from "./env";
import { ProjectCatalog, StateRecord, TypeRecord, WorkflowRecord } from "./types";

export type JsonRecord = Record<string, unknown>;
export type QueryValue = string | number | boolean | string[] | undefined;
export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export interface ApiResult<T = unknown> {
  status: number;
  headers: Record<string, string>;
  data: T;
  text: string;
}

interface RequestOptions {
  body?: JsonRecord;
  rawBody?: string;
  query?: Record<string, QueryValue>;
  headers?: Record<string, string>;
  maxRedirects?: number;
}

export interface CreateIssueOptions {
  name: string;
  type: string;
  priority?: string;
  assigneeIds?: string[];
  parentId?: string;
  description?: string;
}

function asRecord(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

export function rowsOf(data: unknown): JsonRecord[] {
  if (Array.isArray(data)) {
    return data.map(asRecord);
  }
  const record = asRecord(data);
  if (Array.isArray(record["results"])) {
    return (record["results"] as unknown[]).map(asRecord);
  }
  return Object.values(record)
    .filter((value): value is unknown[] => Array.isArray(value))
    .flat()
    .map(asRecord);
}

function idOf(row: JsonRecord): string {
  const value = row["id"];
  return String(value ?? "");
}

function queryString(query?: Record<string, QueryValue>): string {
  if (!query) {
    return "";
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        params.append(key, item);
      }
    } else {
      params.set(key, String(value));
    }
  }
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

export class PlaneApi {
  private constructor(
    readonly config: E2eConfig,
    readonly role: Role | "service",
    private readonly context: APIRequestContext,
    private readonly token?: string
  ) {}

  static async create(config: E2eConfig, role: Role | "service", token?: string): Promise<PlaneApi> {
    const context = await playwrightRequest.newContext({
      baseURL: config.baseUrl,
      extraHTTPHeaders: token ? { "X-Api-Key": token } : {},
    });
    const api = new PlaneApi(config, role, context, token);
    if (!token && role !== "service") {
      await api.signIn(role);
    }
    return api;
  }

  private async csrfHeaders(): Promise<Record<string, string>> {
    if (this.token) {
      return {};
    }
    const response = await this.context.get("/auth/get-csrf-token/");
    const data = asRecord(await response.json());
    const csrfToken = asString(data["csrf_token"]);
    return csrfToken ? { "X-CSRFToken": csrfToken } : {};
  }

  private async signIn(role: Role): Promise<void> {
    const csrf = await this.csrfHeaders();
    const response = await this.context.post("/auth/sign-in/", {
      form: {
        email: emailForRole(this.config, role),
        password: this.config.password,
        next_path: "/",
      },
      headers: csrf,
      maxRedirects: 0,
    });
    if (response.status() !== 302) {
      throw new Error(`Sign-in failed for role ${role} with HTTP ${response.status()}.`);
    }
    const cookies = await this.context.cookies();
    if (!cookies.some((cookie) => cookie.name === "sessionid" || cookie.name === "session")) {
      throw new Error(`Sign-in for role ${role} did not establish a session cookie.`);
    }
  }

  storageState() {
    return this.context.storageState();
  }

  async raw<T = unknown>(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
    const headers: Record<string, string> = { ...options.headers };
    if (options.body !== undefined || options.rawBody !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    if (method !== "GET" && method !== "DELETE" && !this.token) {
      Object.assign(headers, await this.csrfHeaders());
    }
    const response = await this.context.fetch(`${path}${queryString(options.query)}`, {
      method,
      headers,
      data: options.rawBody ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
      maxRedirects: options.maxRedirects ?? 0,
    });
    const text = await response.text();
    const contentType = response.headers()["content-type"] ?? "";
    let data: unknown = undefined;
    if (text && contentType.includes("json")) {
      data = JSON.parse(text) as unknown;
    }
    return {
      status: response.status(),
      headers: response.headers(),
      data: data as T,
      text,
    };
  }

  async json<T = unknown>(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
    const result = await this.raw<T>(method, path, options);
    if (result.status < 200 || result.status >= 300) {
      throw new Error(`${method} ${path} returned HTTP ${result.status}.`);
    }
    return result;
  }

  async me(): Promise<JsonRecord> {
    return asRecord((await this.json<unknown>("GET", "/api/v1/users/me/")).data);
  }

  async workspaceMembers(): Promise<JsonRecord[]> {
    return rowsOf((await this.json<unknown>("GET", `/api/v1/workspaces/${this.config.workspaceSlug}/members/`)).data);
  }

  async loadCatalog(): Promise<ProjectCatalog> {
    const { workspaceSlug, projectName, projectIdentifier } = this.config;
    const projects = rowsOf((await this.json<unknown>("GET", `/api/v1/workspaces/${workspaceSlug}/projects/`)).data);
    const project = projects.find((row) => asString(row["name"]) === projectName);
    if (!project) {
      throw new Error(`Seeded project ${projectName} was not found in workspace ${workspaceSlug}.`);
    }
    const projectId = idOf(project);

    const stateRows = rowsOf(
      (await this.json<unknown>("GET", `/api/v1/workspaces/${workspaceSlug}/projects/${projectId}/states/`)).data
    );
    const typeRows = rowsOf(
      (await this.json<unknown>("GET", `/api/workspaces/${workspaceSlug}/work-item-types/`)).data
    );
    const workflowRows = rowsOf(
      (await this.json<unknown>("GET", `/api/workspaces/${workspaceSlug}/projects/${projectId}/workflows/`)).data
    );

    const states: Record<string, StateRecord> = {};
    for (const row of stateRows) {
      const name = asString(row["name"]);
      if (name) {
        states[name] = { id: idOf(row), name, group: asString(row["group"]) };
      }
    }

    const types: Record<string, TypeRecord> = {};
    for (const row of typeRows) {
      const key = asString(row["key"]);
      if (key) {
        types[key] = { id: idOf(row), key, name: asString(row["name"]) ?? key };
      }
    }

    const workflows: Record<string, WorkflowRecord> = {};
    for (const row of workflowRows) {
      const nestedType = asRecord(row["issue_type"]);
      const key = asString(nestedType["key"]);
      const issueTypeId = asString(row["issue_type_id"]) ?? idOf(nestedType);
      const matchedKey =
        key ?? Object.keys(types).find((candidate) => types[candidate]?.id === issueTypeId) ?? "unknown";
      workflows[matchedKey] = {
        id: idOf(row),
        issueTypeId,
        name: asString(row["name"]) ?? `${matchedKey} workflow`,
      };
    }

    return {
      workspaceSlug,
      projectId,
      projectName,
      identifier: asString(project["identifier"]) ?? projectIdentifier,
      states,
      types,
      workflows,
    };
  }

  workItemBase(catalog: ProjectCatalog): string {
    return `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/work-items`;
  }

  appWorkItemBase(catalog: ProjectCatalog): string {
    return `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/work-items`;
  }

  async createIssue(catalog: ProjectCatalog, options: CreateIssueOptions): Promise<JsonRecord> {
    const typeId = catalog.types[options.type]?.id;
    if (!typeId) {
      throw new Error(`Unknown work item type ${options.type}.`);
    }
    const body: JsonRecord = { name: options.name, type_id: typeId };
    if (options.priority) {
      body["priority"] = options.priority;
    }
    if (options.assigneeIds) {
      body["assignee_ids"] = options.assigneeIds;
    }
    if (options.parentId) {
      body["parent_id"] = options.parentId;
    }
    if (options.description) {
      body["description_html"] = options.description;
    }
    return asRecord((await this.json<unknown>("POST", this.workItemBase(catalog), { body })).data);
  }

  async getIssue(catalog: ProjectCatalog, issueId: string): Promise<JsonRecord> {
    return asRecord((await this.json<unknown>("GET", `${this.workItemBase(catalog)}/${issueId}/`)).data);
  }

  async patchIssue(catalog: ProjectCatalog, issueId: string, body: JsonRecord): Promise<void> {
    await this.json("PATCH", `${this.workItemBase(catalog)}/${issueId}/`, { body });
  }

  async deleteIssue(catalog: ProjectCatalog, issueId: string): Promise<void> {
    await this.json("DELETE", `${this.workItemBase(catalog)}/${issueId}/`);
  }

  async allowedTransitions(catalog: ProjectCatalog, issueId: string): Promise<ApiResult<unknown>> {
    return this.raw("GET", `${this.appWorkItemBase(catalog)}/${issueId}/allowed-transitions/`);
  }

  async transition(
    catalog: ProjectCatalog,
    issueId: string,
    stateName: string,
    options: { comment?: string; force?: boolean } = {}
  ): Promise<ApiResult<unknown>> {
    const stateId = catalog.states[stateName]?.id;
    if (!stateId) {
      throw new Error(`Unknown state ${stateName}.`);
    }
    const query = options.force ? { force: "true" } : undefined;
    const body: JsonRecord = { to_state_id: stateId };
    if (options.comment) {
      body["comment"] = options.comment;
    }
    return this.raw("POST", `${this.appWorkItemBase(catalog)}/${issueId}/transition/`, { body, query });
  }

  async activities(catalog: ProjectCatalog, issueId: string): Promise<JsonRecord[]> {
    return rowsOf((await this.json<unknown>("GET", `${this.appWorkItemBase(catalog)}/${issueId}/activities/`)).data);
  }

  async comments(catalog: ProjectCatalog, issueId: string): Promise<JsonRecord[]> {
    return rowsOf((await this.json<unknown>("GET", `${this.appWorkItemBase(catalog)}/${issueId}/comments/`)).data);
  }

  async addComment(catalog: ProjectCatalog, issueId: string, comment: string): Promise<JsonRecord> {
    return asRecord(
      (
        await this.json<unknown>("POST", `${this.appWorkItemBase(catalog)}/${issueId}/comments/`, {
          body: { comment_html: `<p>${comment}</p>` },
        })
      ).data
    );
  }

  async listIssues(catalog: ProjectCatalog, query?: Record<string, QueryValue>): Promise<JsonRecord[]> {
    return rowsOf((await this.json<unknown>("GET", this.workItemBase(catalog), { query })).data);
  }

  async searchIssues(catalog: ProjectCatalog, term: string): Promise<JsonRecord[]> {
    return rowsOf(
      (
        await this.json<unknown>(
          "GET",
          `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/search-issues/`,
          {
            query: { query: term },
          }
        )
      ).data
    );
  }

  async createView(
    catalog: ProjectCatalog,
    name: string,
    filters: JsonRecord,
    displayFilters: JsonRecord
  ): Promise<JsonRecord> {
    return asRecord(
      (
        await this.json<unknown>(
          "POST",
          `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/views/`,
          {
            body: { name, filters, display_filters: displayFilters, access: 1 },
          }
        )
      ).data
    );
  }

  async deleteView(catalog: ProjectCatalog, viewId: string): Promise<void> {
    await this.json(
      "DELETE",
      `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/views/${viewId}/`
    );
  }

  async cycles(catalog: ProjectCatalog): Promise<JsonRecord[]> {
    return rowsOf(
      (
        await this.json<unknown>(
          "GET",
          `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/cycles/`
        )
      ).data
    );
  }

  async addIssuesToCycle(catalog: ProjectCatalog, cycleId: string, issueIds: string[]): Promise<void> {
    await this.json(
      "POST",
      `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/cycles/${cycleId}/cycle-issues/`,
      { body: { issues: issueIds } }
    );
  }

  async completeCycle(catalog: ProjectCatalog, cycleId: string): Promise<void> {
    await this.json(
      "PATCH",
      `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/cycles/${cycleId}/`,
      { body: { status: "completed" } }
    );
  }

  async transferCycleIssues(catalog: ProjectCatalog, cycleId: string, newCycleId: string): Promise<void> {
    await this.json(
      "POST",
      `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/cycles/${cycleId}/transfer-issues/`,
      { body: { new_cycle_id: newCycleId } }
    );
  }

  async modules(catalog: ProjectCatalog): Promise<JsonRecord[]> {
    return rowsOf(
      (
        await this.json<unknown>(
          "GET",
          `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/modules/`
        )
      ).data
    );
  }

  async addIssuesToModule(catalog: ProjectCatalog, moduleId: string, issueIds: string[]): Promise<void> {
    await this.json(
      "POST",
      `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/modules/${moduleId}/module-issues/`,
      { body: { issues: issueIds } }
    );
  }

  async createModule(catalog: ProjectCatalog, name: string, status = "planned"): Promise<JsonRecord> {
    return asRecord(
      (
        await this.json<unknown>(
          "POST",
          `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/modules/`,
          {
            body: { name, status },
          }
        )
      ).data
    );
  }

  async deleteModule(catalog: ProjectCatalog, moduleId: string): Promise<void> {
    await this.json(
      "DELETE",
      `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/modules/${moduleId}/`
    );
  }

  async moduleDetail(catalog: ProjectCatalog, moduleId: string): Promise<JsonRecord> {
    return asRecord(
      (
        await this.json<unknown>(
          "GET",
          `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/modules/${moduleId}/`
        )
      ).data
    );
  }

  async report(catalog: ProjectCatalog, slug: string, query?: Record<string, QueryValue>): Promise<JsonRecord> {
    return asRecord(
      (
        await this.json<unknown>(
          "GET",
          `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/reports/${slug}/`,
          { query }
        )
      ).data
    );
  }

  async exportReport(
    catalog: ProjectCatalog,
    slug: string,
    query?: Record<string, QueryValue>
  ): Promise<ApiResult<unknown>> {
    return this.json(
      "GET",
      `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/reports/${slug}/export/`,
      { query }
    );
  }

  async notifications(): Promise<JsonRecord[]> {
    return rowsOf(
      (await this.json<unknown>("GET", `/api/workspaces/${this.config.workspaceSlug}/users/notifications/`)).data
    );
  }

  async createProject(name: string, identifier: string): Promise<JsonRecord> {
    return asRecord(
      (
        await this.json<unknown>("POST", `/api/v1/workspaces/${this.config.workspaceSlug}/projects/`, {
          body: { name, identifier },
        })
      ).data
    );
  }

  async deleteProject(projectId: string): Promise<void> {
    await this.json("DELETE", `/api/v1/workspaces/${this.config.workspaceSlug}/projects/${projectId}/`);
  }

  async webhookLogs(webhookId: string): Promise<JsonRecord[]> {
    return rowsOf(
      (await this.json<unknown>("GET", `/api/workspaces/${this.config.workspaceSlug}/webhook-logs/${webhookId}/`)).data
    );
  }

  async changeType(catalog: ProjectCatalog, issueId: string, typeKey: string): Promise<void> {
    const typeId = catalog.types[typeKey]?.id;
    if (!typeId) {
      throw new Error(`Unknown work item type ${typeKey}.`);
    }
    await this.patchIssue(catalog, issueId, { type_id: typeId });
  }

  async reorderIssues(
    catalog: ProjectCatalog,
    items: Array<{ issueId: string; stateId: string; beforeId?: string; afterId?: string }>
  ): Promise<JsonRecord[]> {
    const result = await this.json<unknown>(
      "POST",
      `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/board/reorder/`,
      {
        body: {
          items: items.map((item) => ({
            issue_id: item.issueId,
            state_id: item.stateId,
            before_id: item.beforeId,
            after_id: item.afterId,
          })),
        },
      }
    );
    const record = asRecord(result.data);
    return Array.isArray(record["updated"]) ? (record["updated"] as unknown[]).map(asRecord) : [];
  }

  async cycleIssues(catalog: ProjectCatalog, cycleId: string): Promise<JsonRecord[]> {
    return rowsOf(
      (
        await this.json<unknown>(
          "GET",
          `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/cycles/${cycleId}/cycle-issues/`
        )
      ).data
    );
  }

  async cycleDetail(catalog: ProjectCatalog, cycleId: string): Promise<JsonRecord> {
    return asRecord(
      (
        await this.json<unknown>(
          "GET",
          `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/cycles/${cycleId}/`
        )
      ).data
    );
  }

  async createCycle(catalog: ProjectCatalog, name: string, startDate: string, endDate: string): Promise<JsonRecord> {
    return asRecord(
      (
        await this.json<unknown>(
          "POST",
          `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/cycles/`,
          {
            body: { name, start_date: startDate, end_date: endDate },
          }
        )
      ).data
    );
  }

  async deleteCycle(catalog: ProjectCatalog, cycleId: string): Promise<void> {
    await this.json(
      "DELETE",
      `/api/v1/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/cycles/${cycleId}/`
    );
  }

  async patchView(catalog: ProjectCatalog, viewId: string, body: JsonRecord): Promise<void> {
    await this.json(
      "PATCH",
      `/api/workspaces/${catalog.workspaceSlug}/projects/${catalog.projectId}/views/${viewId}/`,
      { body }
    );
  }

  async postRaw(path: string, body: string, headers: Record<string, string>): Promise<ApiResult<unknown>> {
    return this.raw("POST", path, { rawBody: body, headers });
  }

  async close(): Promise<void> {
    await this.context.dispose();
  }
}
