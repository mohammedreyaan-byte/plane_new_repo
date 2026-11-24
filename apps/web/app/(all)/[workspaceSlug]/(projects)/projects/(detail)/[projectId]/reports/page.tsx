/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useMemo } from "react";
import { observer } from "mobx-react";
import { useSearchParams } from "react-router";
import { EUserPermissionsLevel } from "@plane/constants";
import { EUserProjectRoles } from "@plane/types";
import { PageHead } from "@/components/core/page-title";
import {
  BUILT_IN_REPORTS,
  REPORT_FILTER_KEYS,
  ReportCanvas,
  ReportsSidebar,
  getBuiltInReport,
} from "@/components/reports";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useReportData, useSavedReports } from "@/hooks/use-reports";
import { reportsService } from "@/services/reports.service";
import type { TReportChartType, TReportFilters, TReportType } from "@/services/reports.service";
import type { Route } from "./+types/page";

const DEFAULT_REPORT: TReportType = "bugs_by_state";

function ProjectReportsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const [searchParams, setSearchParams] = useSearchParams();
  const { getProjectById } = useProject();
  const { allowPermissions } = useUserPermissions();
  const { reports: savedReports, getById, mutate: mutateSaved, isLoading: savedLoading } = useSavedReports(
    workspaceSlug,
    projectId
  );

  // The URL is the report: same link, same numbers for every member.
  const savedId = searchParams.get("saved");
  const saved = getById(savedId);
  const reportType = ((saved?.report_type ?? searchParams.get("report")) as TReportType | null) ?? DEFAULT_REPORT;
  const report = getBuiltInReport(reportType) ?? BUILT_IN_REPORTS[0];

  const urlFilters = useMemo(() => {
    const out: Record<string, string> = {};
    REPORT_FILTER_KEYS.forEach((key) => {
      const value = searchParams.get(key);
      if (value) out[key] = value;
    });
    return out as TReportFilters;
  }, [searchParams]);
  const filters = saved ? saved.filters : urlFilters;
  const chartType = ((searchParams.get("chart") as TReportChartType | null) ??
    saved?.chart_type ??
    report.defaultChart) as TReportChartType;

  const { data, error, isLoading } = useReportData({
    workspaceSlug,
    projectId,
    savedId: saved ? saved.id : null,
    reportType: report.type,
    filters: urlFilters,
  });

  const project = getProjectById(projectId);
  const canExport = allowPermissions([EUserProjectRoles.ADMIN, EUserProjectRoles.MEMBER], EUserPermissionsLevel.PROJECT);
  const canSave = canExport;
  const isProjectAdmin = allowPermissions([EUserProjectRoles.ADMIN], EUserPermissionsLevel.PROJECT);

  const writeParams = useCallback(
    (next: { report?: TReportType; saved?: string | null; filters?: TReportFilters; chart?: TReportChartType | null }) => {
      const sp = new URLSearchParams();
      if (next.saved) sp.set("saved", next.saved);
      else sp.set("report", next.report ?? DEFAULT_REPORT);
      Object.entries(next.filters ?? {}).forEach(([key, value]) => {
        if (value) sp.set(key, String(value));
      });
      if (next.chart) sp.set("chart", next.chart);
      setSearchParams(sp, { replace: true });
    },
    [setSearchParams]
  );

  const exportUrl = saved
    ? reportsService.savedExportUrl(workspaceSlug, projectId, saved.id)
    : reportsService.builtInExportUrl(workspaceSlug, projectId, report.type, urlFilters);

  return (
    <>
      <PageHead title={project?.name ? `${project.name} - Reports` : undefined} />
      <div className="flex flex-col gap-6 md:flex-row">
        <ReportsSidebar
          activeBuiltIn={report.type}
          activeSavedId={saved?.id ?? null}
          saved={savedReports}
          isLoading={savedLoading}
          onSelectBuiltIn={(type) => writeParams({ report: type })}
          onSelectSaved={(id) => writeParams({ saved: id })}
        />
        <ReportCanvas
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          report={report}
          title={saved?.name ?? report.title}
          saved={saved}
          filters={filters}
          chartType={chartType}
          result={data}
          error={error}
          isLoading={isLoading}
          canExport={canExport}
          canSave={canSave}
          canManageSaved={Boolean(saved && (saved.is_owner || isProjectAdmin))}
          exportUrl={exportUrl}
          onFiltersChange={(next) => writeParams({ report: report.type, filters: next, chart: chartType })}
          onClearFilters={() => writeParams({ report: report.type, chart: chartType })}
          onChartTypeChange={(type) =>
            writeParams({ report: report.type, saved: saved?.id ?? null, filters: saved ? undefined : urlFilters, chart: type })
          }
          onSave={async (payload) => {
            const created = await reportsService.createSaved(workspaceSlug, projectId, {
              ...payload,
              report_type: report.type,
              filters: urlFilters,
            });
            await mutateSaved();
            writeParams({ saved: created.id });
          }}
          onToggleShare={async (shared) => {
            if (!saved) return;
            await reportsService.updateSaved(workspaceSlug, projectId, saved.id, { is_shared: shared });
            await mutateSaved();
          }}
          onDelete={async () => {
            if (!saved) return;
            await reportsService.deleteSaved(workspaceSlug, projectId, saved.id);
            await mutateSaved();
            writeParams({ report: saved.report_type });
          }}
        />
      </div>
    </>
  );
}

export default observer(ProjectReportsPage);
