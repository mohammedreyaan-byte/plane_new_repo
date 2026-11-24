/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TIssueTypeIconKey =
  | "epic"
  | "story"
  | "task"
  | "bug"
  | "subtask"
  | "improvement"
  | "feature"
  | "spike"
  | "test"
  | "incident"
  | "support";

export type TWorkspaceIssueType = {
  id: string;
  name: string;
  description: string;
  logo_props: {
    in_use?: string;
    icon?: { name?: TIssueTypeIconKey; color?: string };
  };
  is_epic: boolean;
  is_default: boolean;
  level: number;
};

export class IssueTypeService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async getWorkspaceIssueTypes(workspaceSlug: string): Promise<TWorkspaceIssueType[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/issue-types/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
