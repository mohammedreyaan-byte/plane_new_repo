/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TReportChartType, TReportResult, TReportRow } from "@/services/reports.service";

// Colours are never the only signal: every bar/point also has a value label and the table below
// the chart repeats the numbers.
const GROUP_COLORS: Record<string, string> = {
  backlog: "#94a3b8",
  unstarted: "#60a5fa",
  started: "#f59e0b",
  completed: "#22c55e",
  cancelled: "#ef4444",
};
const PRIORITY_COLORS: Record<string, string> = {
  urgent: "#dc2626",
  high: "#f97316",
  medium: "#eab308",
  low: "#3b82f6",
  none: "#94a3b8",
};
const SERIES_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ef4444"];

type TSeries = { key: string; label: string; color: string; dashed?: boolean };
type TShape = { xKey: string; series: TSeries[]; stacked?: boolean; rows: TReportRow[] };

const shapeFor = (result: TReportResult): TShape => {
  switch (result.report) {
    case "bugs_by_state":
      return {
        xKey: "state",
        series: [{ key: "count", label: "Open items", color: SERIES_COLORS[0] }],
        rows: result.rows,
      };
    case "bugs_by_priority":
      return {
        xKey: "label",
        series: [{ key: "count", label: "Open items", color: SERIES_COLORS[0] }],
        rows: result.rows,
      };
    case "created_vs_resolved":
      return {
        xKey: "period",
        series: [
          { key: "created", label: "Created", color: "#ef4444" },
          { key: "resolved", label: "Resolved", color: "#22c55e" },
        ],
        rows: result.rows,
      };
    case "cycle_burndown":
      return {
        xKey: "date",
        series: [
          { key: "remaining", label: "Remaining", color: "#3b82f6" },
          { key: "ideal", label: "Ideal", color: "#94a3b8", dashed: true },
        ],
        rows: result.rows,
      };
    case "cycle_scope":
      return {
        xKey: "date",
        series: [
          { key: "added", label: "Added", color: "#f59e0b" },
          { key: "removed", label: "Removed", color: "#ef4444" },
        ],
        rows: result.rows,
      };
    case "module_progress":
      return {
        xKey: "module",
        stacked: true,
        series: [
          { key: "completed", label: "Completed", color: "#22c55e" },
          { key: "open", label: "Not done", color: "#60a5fa" },
          { key: "cancelled", label: "Cancelled", color: "#ef4444" },
        ],
        rows: result.rows.map((row) => ({
          ...row,
          open: Math.max(0, Number(row.total ?? 0) - Number(row.completed ?? 0) - Number(row.cancelled ?? 0)),
        })),
      };
    default:
      return { xKey: result.columns[0]?.key ?? "", series: [], rows: result.rows };
  }
};

const colorForRow = (report: TReportResult["report"], row: TReportRow, fallback: string) => {
  if (report === "bugs_by_state") return GROUP_COLORS[String(row.group)] ?? fallback;
  if (report === "bugs_by_priority") return PRIORITY_COLORS[String(row.priority)] ?? fallback;
  return fallback;
};

/** One or two sentences that say what the chart shows, for people who cannot see it. */
export const summarizeReport = (result: TReportResult): string => {
  const { report, rows, total, meta } = result;
  if (rows.length === 0) return "No data for these filters.";
  switch (report) {
    case "bugs_by_state":
    case "bugs_by_priority": {
      const top = rows.reduce((best, row) => (Number(row.count) > Number(best.count) ? row : best), rows[0]);
      const name = String(report === "bugs_by_state" ? top.state : top.label);
      const summary = meta.summary;
      const tail = summary ? ` ${summary.resolved ?? 0} resolved and ${summary.cancelled ?? 0} cancelled.` : "";
      return `${total} open. The largest group is ${name} with ${top.count}.${tail}`;
    }
    case "created_vs_resolved": {
      const created = rows.reduce((sum, row) => sum + Number(row.created ?? 0), 0);
      const resolved = rows.reduce((sum, row) => sum + Number(row.resolved ?? 0), 0);
      return `${created} created and ${resolved} resolved between ${rows[0].period} and ${rows[rows.length - 1].period}.`;
    }
    case "cycle_burndown": {
      const last = rows.reduce<TReportRow | undefined>((acc, row) => (row.remaining !== null ? row : acc), undefined);
      return `${total} items in the cycle. ${last ? `${last.remaining} remaining on ${last.date}.` : "Nothing plotted yet."}`;
    }
    case "cycle_scope": {
      const summary = meta.summary;
      return `${summary?.added ?? 0} added and ${summary?.removed ?? 0} removed after the cycle started; ${summary?.initial ?? 0} items at the start.`;
    }
    case "module_progress":
      return `${rows.length} modules. ${rows.filter((row) => Number(row.progress) >= 100).length} fully completed.`;
    default:
      return `${total} items.`;
  }
};

type Props = {
  result: TReportResult;
  chartType: TReportChartType;
};

const tooltipStyle = {
  background: "var(--background-color-surface-1, #fff)",
  border: "1px solid var(--border-color-subtle, #e5e7eb)",
  borderRadius: 6,
  fontSize: 12,
};

export function ChartShell({ result, chartType }: Props) {
  const shape = useMemo(() => shapeFor(result), [result]);
  const summary = useMemo(() => summarizeReport(result), [result]);
  const singleSeries = shape.series.length === 1;
  const slices = useMemo(() => shape.rows.filter((row) => Number(row.count) > 0), [shape]);
  const effective: TReportChartType = chartType === "donut" && !singleSeries ? "bar" : chartType;

  if (effective === "table") return null;

  const height = Math.max(260, effective === "bar" && singleSeries ? shape.rows.length * 38 + 60 : 300);

  return (
    <figure className="m-0">
      {/* The text summary is the accessible name of the chart; the table below carries the numbers. */}
      <figcaption className="mb-2 text-13 text-secondary">{summary}</figcaption>
      <div className="overflow-x-auto" role="img" aria-label={summary}>
        <div style={{ minWidth: 480, height }}>
          <ResponsiveContainer width="100%" height="100%">
            {effective === "donut" ? (
              <PieChart>
                <Pie
                  data={slices}
                  dataKey="count"
                  nameKey={shape.xKey}
                  innerRadius="55%"
                  outerRadius="85%"
                  label={(entry: { name?: string; value?: number }) => `${entry.name}: ${entry.value}`}
                >
                  {slices.map((row) => (
                    <Cell key={String(row[shape.xKey])} fill={colorForRow(result.report, row, SERIES_COLORS[0])} />
                  ))}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} />
                <Legend />
              </PieChart>
            ) : effective === "line" ? (
              <LineChart data={shape.rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey={shape.xKey} tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend />
                {shape.series.map((series) => (
                  <Line
                    key={series.key}
                    type="monotone"
                    dataKey={series.key}
                    name={series.label}
                    stroke={series.color}
                    strokeWidth={2}
                    strokeDasharray={series.dashed ? "6 4" : undefined}
                    dot={{ r: 3 }}
                    connectNulls={false}
                  />
                ))}
              </LineChart>
            ) : singleSeries ? (
              <BarChart data={shape.rows} layout="vertical" margin={{ top: 8, right: 32, bottom: 8, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
                <YAxis type="category" dataKey={shape.xKey} width={140} tick={{ fontSize: 12 }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey={shape.series[0].key} name={shape.series[0].label} radius={[0, 4, 4, 0]}>
                  {shape.rows.map((row) => (
                    <Cell key={String(row[shape.xKey])} fill={colorForRow(result.report, row, shape.series[0].color)} />
                  ))}
                  <LabelList dataKey={shape.series[0].key} position="right" style={{ fontSize: 12 }} />
                </Bar>
              </BarChart>
            ) : (
              <BarChart data={shape.rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey={shape.xKey} tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend />
                {shape.series.map((series) => (
                  <Bar
                    key={series.key}
                    dataKey={series.key}
                    name={series.label}
                    fill={series.color}
                    stackId={shape.stacked ? "stack" : undefined}
                  >
                    <LabelList
                      dataKey={series.key}
                      position={shape.stacked ? "center" : "top"}
                      style={{ fontSize: 11 }}
                    />
                  </Bar>
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      </div>
    </figure>
  );
}
