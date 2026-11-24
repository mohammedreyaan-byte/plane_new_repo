/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TReportChartType, TReportType } from "@/services/reports.service";

export type TBuiltInReport = {
  type: TReportType;
  title: string;
  description: string;
  defaultChart: TReportChartType;
  /** Charts that make sense for this report, first is the default. */
  charts: TReportChartType[];
  needsCycle?: boolean;
  /** Which filters the filter bar offers for this report. */
  filters: ("type_id" | "priority" | "assignee_id" | "label_id" | "cycle_id" | "module_id" | "dates" | "interval")[];
};

export const BUILT_IN_REPORTS: TBuiltInReport[] = [
  {
    type: "bugs_by_state",
    title: "Open bugs by state",
    description: "Bugs that are not resolved or cancelled, grouped by their current state.",
    defaultChart: "bar",
    charts: ["bar", "donut", "table"],
    filters: ["type_id", "priority", "assignee_id", "label_id", "cycle_id", "module_id", "dates"],
  },
  {
    type: "bugs_by_priority",
    title: "Open bugs by priority",
    description: "Open bugs grouped by priority. No priority is its own group.",
    defaultChart: "bar",
    charts: ["bar", "donut", "table"],
    filters: ["type_id", "assignee_id", "label_id", "cycle_id", "module_id", "dates"],
  },
  {
    type: "created_vs_resolved",
    title: "Created vs resolved",
    description: "Bugs created and bugs resolved per week or month, in the project time zone.",
    defaultChart: "line",
    charts: ["line", "bar", "table"],
    filters: ["type_id", "priority", "assignee_id", "label_id", "cycle_id", "module_id", "dates", "interval"],
  },
  {
    type: "cycle_burndown",
    title: "Cycle burndown",
    description: "Work remaining in a cycle per day, against the ideal line. Same data as the cycle page.",
    defaultChart: "line",
    charts: ["line", "table"],
    needsCycle: true,
    filters: ["cycle_id"],
  },
  {
    type: "cycle_scope",
    title: "Cycle scope changes",
    description: "Work items added to or removed from a cycle after it started.",
    defaultChart: "bar",
    charts: ["bar", "table"],
    needsCycle: true,
    filters: ["cycle_id"],
  },
  {
    type: "module_progress",
    title: "Module progress",
    description: "Completed and total work items and points per module.",
    defaultChart: "bar",
    charts: ["bar", "table"],
    filters: ["type_id", "priority", "assignee_id", "label_id", "dates"],
  },
];

export const getBuiltInReport = (type: TReportType | string | null | undefined) =>
  BUILT_IN_REPORTS.find((report) => report.type === type);

export const CHART_TYPE_LABELS: Record<TReportChartType, string> = {
  bar: "Bar",
  line: "Line",
  donut: "Donut",
  table: "Table",
};

export const REPORT_FILTER_KEYS = [
  "cycle_id",
  "module_id",
  "assignee_id",
  "label_id",
  "priority",
  "type_id",
  "date_from",
  "date_to",
  "interval",
  "plot",
] as const;
