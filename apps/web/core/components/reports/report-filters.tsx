/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
import { Button } from "@plane/propel/button";
import { useCycle } from "@/hooks/store/use-cycle";
import { useLabel } from "@/hooks/store/use-label";
import { useMember } from "@/hooks/store/use-member";
import { useModule } from "@/hooks/store/use-module";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";
import type { TReportFilters } from "@/services/reports.service";
import type { TBuiltInReport } from "./constants";

type Props = {
  report: TBuiltInReport;
  filters: TReportFilters;
  workspaceSlug: string;
  projectId: string;
  onChange: (next: TReportFilters) => void;
  onClear: () => void;
};

const PRIORITIES = [
  { value: "urgent", label: "Urgent" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "none", label: "No priority" },
];

const selectClass =
  "h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-primary outline-none focus:border-accent-strong";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-11 text-tertiary">
      <span>{label}</span>
      {children}
    </label>
  );
}

export const ReportFilters = observer(function ReportFilters(props: Props) {
  const { report, filters, workspaceSlug, projectId, onChange, onClear } = props;
  const has = (key: TBuiltInReport["filters"][number]) => report.filters.includes(key);
  const set = (patch: Partial<TReportFilters>) => onChange({ ...filters, ...patch });

  const { types, isEnabled: typesEnabled } = useProjectWorkItemTypes(projectId);
  const { getUserDetails, project: projectMembers } = useMember();
  const { getProjectCycleIds, getCycleById, fetchAllCycles } = useCycle();
  const { getProjectModuleIds, getModuleById, fetchModulesSlim } = useModule();
  const { getProjectLabelIds, getLabelById, fetchProjectLabels } = useLabel();

  useSWR(has("cycle_id") ? `REPORT_CYCLES_${projectId}` : null, () => fetchAllCycles(workspaceSlug, projectId), {
    revalidateOnFocus: false,
  });
  useSWR(has("module_id") ? `REPORT_MODULES_${projectId}` : null, () => fetchModulesSlim(workspaceSlug, projectId), {
    revalidateOnFocus: false,
  });
  useSWR(has("label_id") ? `REPORT_LABELS_${projectId}` : null, () => fetchProjectLabels(workspaceSlug, projectId), {
    revalidateOnFocus: false,
  });

  const memberIds = has("assignee_id") ? (projectMembers.getProjectMemberIds(projectId, false) ?? []) : [];
  const cycleIds = has("cycle_id") ? (getProjectCycleIds(projectId) ?? []) : [];
  const moduleIds = has("module_id") ? (getProjectModuleIds(projectId) ?? []) : [];
  const labelIds = has("label_id") ? (getProjectLabelIds(projectId) ?? []) : [];

  return (
    <div className="flex flex-wrap items-end gap-3" role="group" aria-label="Report filters">
      {has("type_id") && typesEnabled && (
        <Field label="Work item type">
          <select
            className={selectClass}
            value={filters.type_id ?? ""}
            onChange={(e) => set({ type_id: e.target.value || null })}
          >
            <option value="">{report.type === "module_progress" ? "All types" : "Bugs (default)"}</option>
            {report.type !== "module_progress" && <option value="all">All work items</option>}
            {types.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}
              </option>
            ))}
          </select>
        </Field>
      )}
      {has("priority") && (
        <Field label="Priority">
          <select
            className={selectClass}
            value={filters.priority ?? ""}
            onChange={(e) => set({ priority: e.target.value || null })}
          >
            <option value="">Any priority</option>
            {PRIORITIES.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
      )}
      {has("assignee_id") && (
        <Field label="Assignee">
          <select
            className={selectClass}
            value={filters.assignee_id ?? ""}
            onChange={(e) => set({ assignee_id: e.target.value || null })}
          >
            <option value="">Anyone</option>
            {memberIds.map((id) => (
              <option key={id} value={id}>
                {getUserDetails(id)?.display_name ?? id}
              </option>
            ))}
          </select>
        </Field>
      )}
      {has("label_id") && (
        <Field label="Label">
          <select
            className={selectClass}
            value={filters.label_id ?? ""}
            onChange={(e) => set({ label_id: e.target.value || null })}
          >
            <option value="">Any label</option>
            {labelIds.map((id) => (
              <option key={id} value={id}>
                {getLabelById(id)?.name ?? id}
              </option>
            ))}
          </select>
        </Field>
      )}
      {has("cycle_id") && (
        <Field label={report.needsCycle ? "Cycle (required)" : "Cycle"}>
          <select
            className={selectClass}
            value={filters.cycle_id ?? ""}
            onChange={(e) => set({ cycle_id: e.target.value || null })}
          >
            <option value="">{report.needsCycle ? "Choose a cycle" : "Any cycle"}</option>
            {cycleIds.map((id) => (
              <option key={id} value={id}>
                {getCycleById(id)?.name ?? id}
              </option>
            ))}
          </select>
        </Field>
      )}
      {has("module_id") && (
        <Field label="Module">
          <select
            className={selectClass}
            value={filters.module_id ?? ""}
            onChange={(e) => set({ module_id: e.target.value || null })}
          >
            <option value="">Any module</option>
            {moduleIds.map((id) => (
              <option key={id} value={id}>
                {getModuleById(id)?.name ?? id}
              </option>
            ))}
          </select>
        </Field>
      )}
      {has("dates") && (
        <>
          <Field label="From">
            <input
              type="date"
              className={selectClass}
              value={filters.date_from ?? ""}
              onChange={(e) => set({ date_from: e.target.value || null })}
            />
          </Field>
          <Field label="To">
            <input
              type="date"
              className={selectClass}
              value={filters.date_to ?? ""}
              onChange={(e) => set({ date_to: e.target.value || null })}
            />
          </Field>
        </>
      )}
      {has("interval") && (
        <Field label="Group by">
          <select
            className={selectClass}
            value={filters.interval ?? "week"}
            onChange={(e) => set({ interval: e.target.value as "week" | "month" })}
          >
            <option value="week">Week</option>
            <option value="month">Month</option>
          </select>
        </Field>
      )}
      <Button variant="secondary" size="sm" onClick={onClear}>
        Clear filters
      </Button>
    </div>
  );
});
