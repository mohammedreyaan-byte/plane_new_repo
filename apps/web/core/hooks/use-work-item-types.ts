/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useMemo } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { workItemTypesService } from "@/services/work-item-types.service";
import type { TWorkItemType } from "@/services/work-item-types.service";

export const PROJECT_WORK_ITEM_TYPES_KEY = (workspaceSlug: string, projectId: string) =>
  `PROJECT_WORK_ITEM_TYPES_${workspaceSlug}_${projectId}`;

/**
 * Work item types enabled in a project. SWR shares one request per project, so list rows,
 * board cards and the detail view can all call this without extra network cost.
 * `isEnabled` is false (and `types` empty) while the project has types switched off.
 */
export const useProjectWorkItemTypes = (projectId: string | null | undefined) => {
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString();
  const { data, mutate, isLoading } = useSWR(
    slug && projectId ? PROJECT_WORK_ITEM_TYPES_KEY(slug, projectId) : null,
    slug && projectId ? () => workItemTypesService.listProjectTypes(slug, projectId) : null,
    { revalidateIfStale: false, revalidateOnFocus: false, dedupingInterval: 60_000 }
  );

  const rows = useMemo(() => data ?? [], [data]);
  const enabledRows = useMemo(() => rows.filter((row) => row.is_enabled), [rows]);
  const types = useMemo(() => enabledRows.map((row) => row.issue_type), [enabledRows]);
  const getTypeById = useCallback(
    (typeId: string | null | undefined): TWorkItemType | undefined =>
      typeId ? rows.find((row) => row.issue_type.id === typeId)?.issue_type : undefined,
    [rows]
  );
  const defaultTypeId = enabledRows.find((row) => row.is_default)?.issue_type.id ?? null;

  return { rows, types, getTypeById, defaultTypeId, isEnabled: enabledRows.length > 0, isLoading, mutate };
};

/** Work item types of the workspace, for filters that span several projects. */
export const useWorkspaceWorkItemTypes = (workspaceSlug: string | null | undefined) => {
  const { data, isLoading } = useSWR(
    workspaceSlug ? `WORKSPACE_WORK_ITEM_TYPES_${workspaceSlug}` : null,
    workspaceSlug ? () => workItemTypesService.listWorkspaceTypes(workspaceSlug) : null,
    { revalidateIfStale: false, revalidateOnFocus: false }
  );
  const types = useMemo(() => (data ?? []).filter((type) => type.is_active), [data]);
  return { types, isLoading };
};
