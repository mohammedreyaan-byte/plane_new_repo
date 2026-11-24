/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Button } from "@plane/propel/button";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import type { TReportChartType, TReportErrorBody } from "@/services/reports.service";
import { CHART_TYPE_LABELS } from "./constants";

type Props = {
  isOpen: boolean;
  defaultName: string;
  chartTypes: TReportChartType[];
  initialChartType: TReportChartType;
  onClose: () => void;
  onSubmit: (data: { name: string; is_shared: boolean; chart_type: TReportChartType }) => Promise<void>;
};

const errorMessage = (error: unknown): string => {
  const body = error as (TReportErrorBody & { name?: string | string[] }) | undefined;
  if (body?.name) return Array.isArray(body.name) ? body.name[0] : String(body.name);
  return body?.error?.message ?? "The report could not be saved.";
};

/** "Save as report": stores the current filters and chart type, optionally shared with the project. */
export function SaveReportModal({ isOpen, defaultName, chartTypes, initialChartType, onClose, onSubmit }: Props) {
  const [name, setName] = useState(defaultName);
  const [shared, setShared] = useState(false);
  const [chartType, setChartType] = useState<TReportChartType>(initialChartType);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const close = () => {
    setError(null);
    setSaving(false);
    onClose();
  };

  const submit = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ name: name.trim(), is_shared: shared, chart_type: chartType });
      close();
    } catch (e) {
      setError(errorMessage(e));
      setSaving(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={close} position={EModalPosition.CENTER} width={EModalWidth.XL}>
      <div className="space-y-4 p-5">
        <div>
          <h3 className="text-16 font-medium text-primary">Save as report</h3>
          <p className="mt-1 text-13 text-secondary">
            Saves the filters and chart. Numbers are always calculated fresh, never stored.
          </p>
        </div>
        <label className="block text-13 text-secondary">
          Name
          <input
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full rounded-md border border-subtle bg-surface-1 p-2 text-13 text-primary outline-none focus:border-accent-strong"
          />
        </label>
        <label className="block text-13 text-secondary">
          Chart
          <select
            value={chartType}
            onChange={(e) => setChartType(e.target.value as TReportChartType)}
            className="mt-1 w-full rounded-md border border-subtle bg-surface-1 p-2 text-13 text-primary outline-none focus:border-accent-strong"
          >
            {chartTypes.map((type) => (
              <option key={type} value={type}>
                {CHART_TYPE_LABELS[type]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-13 text-primary">
          <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
          Share with everyone in this project
        </label>
        {error && (
          <p role="alert" className="text-13 text-danger-primary">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={close} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={submit} loading={saving} disabled={!name.trim()}>
            Save report
          </Button>
        </div>
      </div>
    </ModalCore>
  );
}
