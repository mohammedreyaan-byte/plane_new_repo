/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { Button } from "@plane/propel/button";
import type {
  TReportChartType,
  TReportDefinition,
  TReportErrorBody,
  TReportFilters,
  TReportResult,
} from "@/services/reports.service";
import { ChartShell } from "./chart-shell";
import { CHART_TYPE_LABELS } from "./constants";
import type { TBuiltInReport } from "./constants";
import { ReportCard } from "./report-card";
import { ReportFilters } from "./report-filters";
import { ReportTable } from "./report-table";
import { SaveReportModal } from "./save-report-modal";

type Props = {
  workspaceSlug: string;
  projectId: string;
  report: TBuiltInReport;
  title: string;
  saved: TReportDefinition | undefined;
  filters: TReportFilters;
  chartType: TReportChartType;
  result: TReportResult | undefined;
  error: unknown;
  isLoading: boolean;
  canExport: boolean;
  canSave: boolean;
  canManageSaved: boolean;
  exportUrl: string;
  onFiltersChange: (next: TReportFilters) => void;
  onClearFilters: () => void;
  onChartTypeChange: (type: TReportChartType) => void;
  onSave: (data: { name: string; is_shared: boolean; chart_type: TReportChartType }) => Promise<void>;
  onToggleShare: (shared: boolean) => Promise<void>;
  onDelete: () => Promise<void>;
};

const isEmpty = (result: TReportResult) => {
  if (result.rows.length === 0) return true;
  switch (result.report) {
    case "bugs_by_state":
    case "bugs_by_priority":
      return result.total === 0;
    case "created_vs_resolved":
      return result.rows.every((row) => Number(row.created) === 0 && Number(row.resolved) === 0);
    default:
      return false;
  }
};

const errorText = (error: unknown): string => {
  const body = error as TReportErrorBody | undefined;
  return body?.error?.message ?? body?.detail ?? "This report could not be loaded.";
};

export function ReportCanvas(props: Props) {
  const {
    workspaceSlug,
    projectId,
    report,
    title,
    saved,
    filters,
    chartType,
    result,
    error,
    isLoading,
    canExport,
    canSave,
    canManageSaved,
    exportUrl,
    onFiltersChange,
    onClearFilters,
    onChartTypeChange,
    onSave,
    onToggleShare,
    onDelete,
  } = props;
  const [saveOpen, setSaveOpen] = useState(false);
  const missingCycle = Boolean(report.needsCycle && !filters.cycle_id && !saved);
  const empty = useMemo(() => (result ? isEmpty(result) : false), [result]);
  const note = result?.meta.deprecation_note ?? (result?.meta.note as string | undefined | null);

  return (
    <section aria-labelledby="report-title" className="min-w-0 flex-1 space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 id="report-title" className="truncate text-18 font-semibold text-primary">
            {title}
          </h1>
          <p className="mt-1 text-13 text-secondary">{saved?.description || report.description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="report-chart-type">
            Chart type
          </label>
          <select
            id="report-chart-type"
            value={chartType}
            onChange={(e) => onChartTypeChange(e.target.value as TReportChartType)}
            className="h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-primary"
          >
            {report.charts.map((type) => (
              <option key={type} value={type}>
                {CHART_TYPE_LABELS[type]}
              </option>
            ))}
          </select>
          {canExport ? (
            <a
              href={exportUrl}
              download
              className="inline-flex h-8 items-center rounded-md border border-subtle bg-surface-1 px-3 text-13 text-primary hover:bg-layer-1"
            >
              Export CSV
            </a>
          ) : (
            <span className="text-11 text-tertiary" title="Your role can view reports but not export them">
              Export not available for your role
            </span>
          )}
          {canSave && !saved && (
            <Button variant="primary" size="sm" onClick={() => setSaveOpen(true)}>
              Save as report
            </Button>
          )}
        </div>
      </header>

      {saved && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-subtle bg-layer-1 px-3 py-2 text-13 text-secondary">
          <span>
            Saved report · {saved.is_shared ? "shared with the project" : "only you can see it"}. Changing a filter
            opens an unsaved copy.
          </span>
          {canManageSaved && (
            <>
              <label className="flex items-center gap-1 text-primary">
                <input
                  type="checkbox"
                  checked={saved.is_shared}
                  onChange={(e) => void onToggleShare(e.target.checked)}
                />
                Shared
              </label>
              <Button variant="secondary" size="sm" onClick={() => void onDelete()}>
                Delete
              </Button>
            </>
          )}
        </div>
      )}

      <ReportFilters
        report={report}
        filters={saved ? { ...saved.filters } : filters}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        onChange={onFiltersChange}
        onClear={onClearFilters}
      />

      {note && (
        <p role="note" className="rounded-md border border-subtle bg-layer-1 px-3 py-2 text-13 text-secondary">
          {note}
        </p>
      )}

      {missingCycle ? (
        <p className="rounded-md border border-dashed border-subtle p-6 text-center text-13 text-secondary">
          Choose a cycle to see this report.
        </p>
      ) : isLoading && !result ? (
        <p className="p-6 text-center text-13 text-secondary" aria-live="polite">
          Loading report…
        </p>
      ) : error ? (
        <p role="alert" className="rounded-md border border-subtle p-4 text-13 text-danger-primary">
          {errorText(error)}
        </p>
      ) : result ? (
        <div className="space-y-4">
          <ReportCard summary={result.meta.summary} />
          {empty ? (
            <div className="rounded-md border border-dashed border-subtle p-6 text-center">
              <p className="text-13 text-secondary">No data for these filters.</p>
              <Button variant="secondary" size="sm" className="mt-3" onClick={onClearFilters}>
                Clear filters
              </Button>
            </div>
          ) : (
            <>
              <ChartShell result={result} chartType={chartType} />
              <ReportTable result={result} caption={`${title}: data table`} />
            </>
          )}
          <p className="text-11 text-tertiary">
            Time zone {result.meta.timezone}. Generated {new Date(result.generated_at).toLocaleString()}.
            {result.report.startsWith("bugs") ? ` ${result.meta.open_definition}` : ""}
          </p>
        </div>
      ) : null}

      <SaveReportModal
        key={saveOpen ? "open" : "closed"}
        isOpen={saveOpen}
        defaultName={title}
        chartTypes={report.charts}
        initialChartType={chartType}
        onClose={() => setSaveOpen(false)}
        onSubmit={onSave}
      />
    </section>
  );
}
