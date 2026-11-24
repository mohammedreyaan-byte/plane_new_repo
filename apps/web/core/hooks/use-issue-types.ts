/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// services
import { IssueTypeService } from "@/services/issue/issue_type.service";
import type { TWorkspaceIssueType } from "@/services/issue/issue_type.service";

const issueTypeService = new IssueTypeService();

/**
 * Workspace issue types (Epic, Story, Task, Bug, Sub-task). Fetched once per workspace and
 * shared through the SWR cache, so every issue row can look its type up without extra requests.
 */
export const useIssueTypes = () => {
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString();

  const { data } = useSWR(slug ? `WORKSPACE_ISSUE_TYPES_${slug}` : null, slug ? () => issueTypeService.getWorkspaceIssueTypes(slug) : null, {
    revalidateOnFocus: false,
    dedupingInterval: 5 * 60 * 1000,
  });

  const issueTypes = useMemo<TWorkspaceIssueType[]>(() => data ?? [], [data]);
  const defaultIssueType = useMemo(() => issueTypes.find((type) => type.is_default), [issueTypes]);

  const getIssueTypeById = (typeId: string | null | undefined): TWorkspaceIssueType | undefined =>
    // issues created before issue types existed have no type, so show them as the default (Task)
    typeId ? issueTypes.find((type) => type.id === typeId) : defaultIssueType;

  return { issueTypes, defaultIssueType, getIssueTypeById };
};
