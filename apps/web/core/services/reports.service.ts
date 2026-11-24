/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";

export type TReportType =
  | "bugs_by_state"
  | "bugs_by_priority"
  | "created_vs_resolved"
  | "cycle_burndown"
  | "cycle_scope"
  | "module_progress";

export type TReportChartType = "bar" | "line" | "table" | "donut";

export type TReportFilters = {
  cycle_id?: string | null;
  module_id?: string | null;
  assignee_id?: string | null;
  label_id?: string | null;
  priority?: string | null;
  /** A work item type id, or "all". Leave empty for the report's default (bugs). */
  type_id?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  interval?: "week" | "month" | null;
  plot?: "issues" | "points" | null;
};

export type TReportColumn = { key: string; label: string };
export type TReportRow = Record<string, string | number | null>;

export type TReportResult = {
  report: TReportType;
  title?: string;
  generated_at: string;
  filters: TReportFilters;
  total: number;
  columns: TReportColumn[];
  rows: TReportRow[];
  meta: {
    timezone: string;
    open_definition: string;
    deprecation_note?: string;
    note?: string | null;
    summary?: { open?: number; resolved?: number; cancelled?: number; [key: string]: number | undefined };
    [key: string]: unknown;
  };
  definition?: { id: string; name: string; chart_type: TReportChartType; group_by: string };
};

export type TReportDefinition = {
  id: string;
  name: string;
  description: string;
  report_type: TReportType;
  filters: TReportFilters & { schema_version?: number };
  group_by: string;
  chart_type: TReportChartType;
  is_shared: boolean;
  owned_by: string;
  is_owner: boolean;
  created_at: string;
  updated_at: string;
};

export type TReportDefinitionPayload = Partial<
  Pick<TReportDefinition, "name" | "description" | "report_type" | "filters" | "group_by" | "chart_type" | "is_shared">
>;

/** Error body used by the reports API: { error: { code, message, details } }. */
export type TReportErrorBody = { error?: { code?: string; message?: string }; detail?: string };

export const BUILT_IN_SLUGS: Record<TReportType, string> = {
  bugs_by_state: "bugs-by-state",
  bugs_by_priority: "bugs-by-priority",
  created_vs_resolved: "created-vs-resolved",
  cycle_burndown: "cycle-burndown",
  cycle_scope: "cycle-scope",
  module_progress: "module-progress",
};

const cleanParams = (filters: TReportFilters) => {
  const out: Record<string, string> = {};
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") out[key] = String(value);
  });
  return out;
};

export class ReportsService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/reports`;
  }

  async listSaved(workspaceSlug: string, projectId: string): Promise<TReportDefinition[]> {
    return this.get(`${this.base(workspaceSlug, projectId)}/`)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async createSaved(
    workspaceSlug: string,
    projectId: string,
    data: TReportDefinitionPayload
  ): Promise<TReportDefinition> {
    return this.post(`${this.base(workspaceSlug, projectId)}/`, data)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async updateSaved(
    workspaceSlug: string,
    projectId: string,
    reportId: string,
    data: TReportDefinitionPayload
  ): Promise<TReportDefinition> {
    return this.patch(`${this.base(workspaceSlug, projectId)}/${reportId}/`, data)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async deleteSaved(workspaceSlug: string, projectId: string, reportId: string): Promise<void> {
    return this.delete(`${this.base(workspaceSlug, projectId)}/${reportId}/`)
      .then(() => undefined)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async getBuiltIn(
    workspaceSlug: string,
    projectId: string,
    reportType: TReportType,
    filters: TReportFilters
  ): Promise<TReportResult> {
    return this.get(`${this.base(workspaceSlug, projectId)}/${BUILT_IN_SLUGS[reportType]}/`, {
      params: cleanParams(filters),
    })
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async getSavedData(workspaceSlug: string, projectId: string, reportId: string): Promise<TReportResult> {
    return this.get(`${this.base(workspaceSlug, projectId)}/${reportId}/data/`)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  /** Same-origin download link (the session cookie authenticates it). */
  builtInExportUrl(workspaceSlug: string, projectId: string, reportType: TReportType, filters: TReportFilters) {
    const query = new URLSearchParams(cleanParams(filters)).toString();
    return `${API_BASE_URL}${this.base(workspaceSlug, projectId)}/${BUILT_IN_SLUGS[reportType]}/export/${query ? `?${query}` : ""}`;
  }

  savedExportUrl(workspaceSlug: string, projectId: string, reportId: string) {
    return `${API_BASE_URL}${this.base(workspaceSlug, projectId)}/${reportId}/export/`;
  }
}

export const reportsService = new ReportsService();
