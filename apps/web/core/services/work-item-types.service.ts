/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";

export type TWorkItemType = {
  id: string;
  key: string | null;
  name: string;
  description: string;
  logo_props: { in_use?: string; icon?: { name?: string; color?: string } } | null;
  is_epic: boolean;
  is_default: boolean;
  is_active: boolean;
  level: number;
  projects_count?: number;
};

export type TProjectWorkItemType = {
  id: string;
  issue_type: TWorkItemType;
  is_enabled: boolean;
  is_default: boolean;
  level: number;
};

export type TWorkflowTransition = {
  id: string;
  from_state_id: string;
  to_state_id: string;
  allowed_roles: string[];
  requires_comment: boolean;
  required_fields: string[];
  admin_override: boolean;
  is_active: boolean;
};

export type TWorkflowState = {
  id: string;
  state_id: string;
  name: string;
  group: string;
  sequence: number;
  is_initial: boolean;
  is_final: boolean;
};

export type TWorkflow = {
  id: string;
  name: string;
  description: string;
  issue_type: string | null;
  issue_type_key: string | null;
  is_default: boolean;
  is_active: boolean;
  states?: TWorkflowState[];
  transitions?: TWorkflowTransition[];
};

export type TAllowedTransition = {
  transition_id: string;
  to_state_id: string;
  to_state_name: string;
  to_state_group: string;
  requires_comment: boolean;
  required_fields: string[];
  allowed: boolean;
  reason: string | null;
  required_roles?: string[];
};

export type TAllowedTransitions = {
  issue_id: string;
  current_state_id: string | null;
  workflow_id: string | null;
  transitions: TAllowedTransition[];
  denied?: TAllowedTransition[];
};

export type TWorkflowHealthIssue = { code: string; workflow_id: string; message?: string; [key: string]: unknown };

/** Error body returned by the workflow engine: { error: { code, message, details } }. */
export type TWorkflowErrorBody = { error: { code: string; message: string; details?: Record<string, unknown> } };

export type TEpicOption = { id: string; name: string; sequence_id: number };

export type TEpicModules = {
  epic_id: string;
  modules: {
    id: string;
    name: string;
    status: string;
    start_date: string | null;
    target_date: string | null;
    total_issues: number;
    completed_issues: number;
  }[];
  total_issues: number;
  completed_issues: number;
  progress: number;
};

export class WorkItemTypesService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private project(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}`;
  }

  async listWorkspaceTypes(workspaceSlug: string): Promise<TWorkItemType[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/work-item-types/`)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async createWorkspaceType(workspaceSlug: string, data: Partial<TWorkItemType>): Promise<TWorkItemType> {
    return this.post(`/api/workspaces/${workspaceSlug}/work-item-types/`, data)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async updateWorkspaceType(
    workspaceSlug: string,
    typeId: string,
    data: Partial<TWorkItemType>
  ): Promise<TWorkItemType> {
    return this.patch(`/api/workspaces/${workspaceSlug}/work-item-types/${typeId}/`, data)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async deleteWorkspaceType(workspaceSlug: string, typeId: string, force = false): Promise<void> {
    return this.delete(`/api/workspaces/${workspaceSlug}/work-item-types/${typeId}/${force ? "?force=true" : ""}`)
      .then(() => undefined)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async listProjectTypes(workspaceSlug: string, projectId: string): Promise<TProjectWorkItemType[]> {
    return this.get(`${this.project(workspaceSlug, projectId)}/work-item-types/`)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async enableProjectTypes(workspaceSlug: string, projectId: string, enable: boolean): Promise<void> {
    return this.post(`${this.project(workspaceSlug, projectId)}/work-item-types/${enable ? "enable" : "disable"}/`)
      .then(() => undefined)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async addProjectType(workspaceSlug: string, projectId: string, issueTypeId: string): Promise<TProjectWorkItemType> {
    return this.post(`${this.project(workspaceSlug, projectId)}/work-item-types/`, { issue_type_id: issueTypeId })
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async updateProjectType(
    workspaceSlug: string,
    projectId: string,
    rowId: string,
    data: Partial<Pick<TProjectWorkItemType, "is_default" | "is_enabled">>
  ): Promise<TProjectWorkItemType> {
    return this.patch(`${this.project(workspaceSlug, projectId)}/work-item-types/${rowId}/`, data)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async disableProjectType(workspaceSlug: string, projectId: string, rowId: string): Promise<void> {
    return this.delete(`${this.project(workspaceSlug, projectId)}/work-item-types/${rowId}/`)
      .then(() => undefined)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  // epics ---------------------------------------------------------------

  /** Epics of a project, for linking to a module. */
  async listProjectEpics(workspaceSlug: string, projectId: string, epicTypeId: string): Promise<TEpicOption[]> {
    return this.get(`${this.project(workspaceSlug, projectId)}/issues/?issue_type=${epicTypeId}&per_page=100`)
      .then((r) => {
        const results = r?.data?.results;
        return Array.isArray(results) ? results : [];
      })
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async getEpicModules(workspaceSlug: string, projectId: string, epicId: string): Promise<TEpicModules> {
    return this.get(`${this.project(workspaceSlug, projectId)}/work-items/${epicId}/epic-modules/`)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  // workflows -------------------------------------------------------------

  async listWorkflows(workspaceSlug: string, projectId: string): Promise<TWorkflow[]> {
    return this.get(`${this.project(workspaceSlug, projectId)}/workflows/`)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async getWorkflow(workspaceSlug: string, projectId: string, workflowId: string): Promise<TWorkflow> {
    return this.get(`${this.project(workspaceSlug, projectId)}/workflows/${workflowId}/`)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async createTransition(
    workspaceSlug: string,
    projectId: string,
    workflowId: string,
    data: Partial<TWorkflowTransition>
  ): Promise<TWorkflowTransition> {
    return this.post(`${this.project(workspaceSlug, projectId)}/workflows/${workflowId}/transitions/`, data)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async updateTransition(
    workspaceSlug: string,
    projectId: string,
    workflowId: string,
    transitionId: string,
    data: Partial<TWorkflowTransition>
  ): Promise<TWorkflowTransition> {
    return this.patch(
      `${this.project(workspaceSlug, projectId)}/workflows/${workflowId}/transitions/${transitionId}/`,
      data
    )
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async deleteTransition(
    workspaceSlug: string,
    projectId: string,
    workflowId: string,
    transitionId: string
  ): Promise<void> {
    return this.delete(`${this.project(workspaceSlug, projectId)}/workflows/${workflowId}/transitions/${transitionId}/`)
      .then(() => undefined)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async resetWorkflow(workspaceSlug: string, projectId: string, workflowId: string): Promise<void> {
    return this.post(`${this.project(workspaceSlug, projectId)}/workflows/${workflowId}/reset/`)
      .then(() => undefined)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async getWorkflowHealth(workspaceSlug: string, projectId: string): Promise<{ issues: TWorkflowHealthIssue[] }> {
    return this.get(`${this.project(workspaceSlug, projectId)}/workflows/health/`)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async getAllowedTransitions(workspaceSlug: string, projectId: string, issueId: string): Promise<TAllowedTransitions> {
    return this.get(`${this.project(workspaceSlug, projectId)}/work-items/${issueId}/allowed-transitions/`)
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }

  async transitionWorkItem(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    toStateId: string,
    comment?: string
  ): Promise<{ issue_id: string; state_id: string; previous_state_id: string }> {
    return this.post(`${this.project(workspaceSlug, projectId)}/work-items/${issueId}/transition/`, {
      to_state_id: toStateId,
      comment: comment ?? "",
    })
      .then((r) => r?.data)
      .catch((e) => {
        throw e?.response?.data;
      });
  }
}

export const workItemTypesService = new WorkItemTypesService();
