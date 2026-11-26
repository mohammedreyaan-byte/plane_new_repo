/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";

export type WorkItemTemplateData = {
  title_template?: string;
  description_template?: string;
  priority?: string;
  label_ids?: string[];
  assignee_id?: string | null;
  type_id?: string | null;
  state_id?: string | null;
  module_id?: string | null;
  cycle_id?: string | null;
};

export type WorkItemTemplate = {
  id: string;
  name: string;
  description: string;
  template_data: WorkItemTemplateData;
  is_public: boolean;
  scope: "workspace" | "project";
  workspace_id: string;
  project_id: string | null;
  created_by: { id: string; display_name: string } | null;
  created_at: string;
  updated_at: string;
};

export type WorkItemTemplatePayload = {
  name: string;
  description?: string;
  template_data: WorkItemTemplateData;
  is_public?: boolean;
};

export type TemplateOption = { id: string; name: string };
export type TemplateMemberOption = { id: string; display_name: string };
export type TemplatePriorityOption = { value: string; label: string };

export type WorkItemTemplateOptions = {
  states: TemplateOption[];
  labels: TemplateOption[];
  members: TemplateMemberOption[];
  types: TemplateOption[];
  modules: TemplateOption[];
  cycles: TemplateOption[];
  priorities: TemplatePriorityOption[];
};

const unwrap = <T>(promise: Promise<{ data: T }>): Promise<T> =>
  promise.then((response) => response.data).catch((error) => Promise.reject(error?.response?.data ?? error));

const asOptions = (value: unknown): TemplateOption[] =>
  Array.isArray(value)
    ? value
        .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
        .map((item) => ({ id: String(item.id ?? ""), name: String(item.name ?? "") }))
        .filter((item) => item.id && item.name)
    : [];

const normalizeOptions = (value: unknown): unknown[] =>
  Array.isArray(value) ? value : ((value as { results?: unknown[] })?.results ?? []);

/** Typed client for the work item template APIs. */
export class WorkItemTemplatesService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private workspaceBase(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}`;
  }

  private projectBase(workspaceSlug: string, projectId: string) {
    return `${this.workspaceBase(workspaceSlug)}/projects/${projectId}`;
  }

  getWorkspaceTemplates(workspaceSlug: string): Promise<WorkItemTemplate[]> {
    return unwrap(this.get(`${this.workspaceBase(workspaceSlug)}/templates/`));
  }

  createWorkspaceTemplate(workspaceSlug: string, data: WorkItemTemplatePayload): Promise<WorkItemTemplate> {
    return unwrap(this.post(`${this.workspaceBase(workspaceSlug)}/templates/`, data));
  }

  updateWorkspaceTemplate(
    workspaceSlug: string,
    templateId: string,
    data: Partial<WorkItemTemplatePayload>
  ): Promise<WorkItemTemplate> {
    return unwrap(this.patch(`${this.workspaceBase(workspaceSlug)}/templates/${templateId}/`, data));
  }

  getWorkspaceTemplate(workspaceSlug: string, templateId: string): Promise<WorkItemTemplate> {
    return unwrap(this.get(`${this.workspaceBase(workspaceSlug)}/templates/${templateId}/`));
  }

  deleteWorkspaceTemplate(workspaceSlug: string, templateId: string): Promise<void> {
    return unwrap(this.delete(`${this.workspaceBase(workspaceSlug)}/templates/${templateId}/`));
  }

  getProjectTemplates(workspaceSlug: string, projectId: string): Promise<WorkItemTemplate[]> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/templates/`));
  }

  createProjectTemplate(
    workspaceSlug: string,
    projectId: string,
    data: WorkItemTemplatePayload
  ): Promise<WorkItemTemplate> {
    return unwrap(this.post(`${this.projectBase(workspaceSlug, projectId)}/templates/`, data));
  }

  updateProjectTemplate(
    workspaceSlug: string,
    projectId: string,
    templateId: string,
    data: Partial<WorkItemTemplatePayload>
  ): Promise<WorkItemTemplate> {
    return unwrap(this.patch(`${this.projectBase(workspaceSlug, projectId)}/templates/${templateId}/`, data));
  }

  getProjectTemplate(workspaceSlug: string, projectId: string, templateId: string): Promise<WorkItemTemplate> {
    return unwrap(this.get(`${this.projectBase(workspaceSlug, projectId)}/templates/${templateId}/`));
  }

  deleteProjectTemplate(workspaceSlug: string, projectId: string, templateId: string): Promise<void> {
    return unwrap(this.delete(`${this.projectBase(workspaceSlug, projectId)}/templates/${templateId}/`));
  }

  async getWorkspaceOptions(workspaceSlug: string): Promise<WorkItemTemplateOptions> {
    const options = await unwrap<{
      states?: TemplateOption[];
      labels?: TemplateOption[];
      members?: TemplateMemberOption[];
      types?: TemplateOption[];
      modules?: TemplateOption[];
      cycles?: TemplateOption[];
      priorities?: TemplatePriorityOption[];
    }>(this.get(`${this.workspaceBase(workspaceSlug)}/template-options/`));
    return {
      states: options.states ?? [],
      labels: options.labels ?? [],
      members: options.members ?? [],
      types: options.types ?? [],
      modules: options.modules ?? [],
      cycles: options.cycles ?? [],
      priorities: options.priorities ?? [],
    };
  }

  async getProjectOptions(workspaceSlug: string, projectId: string): Promise<WorkItemTemplateOptions> {
    const [options, modules, cycles] = await Promise.all([
      unwrap<{
        states: TemplateOption[];
        labels: TemplateOption[];
        members: TemplateMemberOption[];
        types: TemplateOption[];
        priorities: TemplatePriorityOption[];
      }>(this.get(`${this.projectBase(workspaceSlug, projectId)}/automation-options/`)),
      unwrap<unknown>(this.get(`${this.projectBase(workspaceSlug, projectId)}/modules/`)).catch(() => []),
      unwrap<unknown>(this.get(`${this.projectBase(workspaceSlug, projectId)}/cycles/`)).catch(() => []),
    ]);
    return {
      states: options.states ?? [],
      labels: options.labels ?? [],
      members: options.members ?? [],
      types: options.types ?? [],
      priorities: options.priorities ?? [],
      modules: asOptions(normalizeOptions(modules)),
      cycles: asOptions(normalizeOptions(cycles)),
    };
  }
}

export const workItemTemplatesService = new WorkItemTemplatesService();
