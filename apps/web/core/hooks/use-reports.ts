/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import type { TReportFilters, TReportResult, TReportType } from "@/services/reports.service";
import { reportsService } from "@/services/reports.service";

export const SAVED_REPORTS_KEY = (workspaceSlug: string, projectId: string) =>
  `PROJECT_SAVED_REPORTS_${workspaceSlug}_${projectId}`;

/** Saved reports the current user can see (their own plus shared ones). */
export const useSavedReports = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const key = workspaceSlug && projectId ? SAVED_REPORTS_KEY(workspaceSlug, projectId) : null;
  const { data, mutate, isLoading, error } = useSWR(
    key,
    key && workspaceSlug && projectId ? () => reportsService.listSaved(workspaceSlug, projectId) : null
  );
  const getById = useCallback((id: string | null | undefined) => (data ?? []).find((r) => r.id === id), [data]);
  return { reports: useMemo(() => data ?? [], [data]), getById, mutate, isLoading, error };
};

type TRunArgs = {
  workspaceSlug: string | undefined;
  projectId: string | undefined;
  /** Saved report id. When set, the saved definition decides the filters. */
  savedId?: string | null;
  reportType: TReportType | null;
  filters: TReportFilters;
};

/** Numbers for either a saved report or an ad-hoc built-in report. The cache key is the full request. */
export const useReportData = ({ workspaceSlug, projectId, savedId, reportType, filters }: TRunArgs) => {
  const ready = Boolean(workspaceSlug && projectId && (savedId || reportType));
  const key = ready ? ["PROJECT_REPORT", workspaceSlug, projectId, savedId ?? reportType, JSON.stringify(filters)] : null;
  const { data, error, isLoading, mutate } = useSWR<TReportResult>(
    key,
    key && workspaceSlug && projectId
      ? () =>
          savedId
            ? reportsService.getSavedData(workspaceSlug, projectId, savedId)
            : reportsService.getBuiltIn(workspaceSlug, projectId, reportType as TReportType, filters)
      : null,
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
  return { data, error, isLoading, mutate };
};
