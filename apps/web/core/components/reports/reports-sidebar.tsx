/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TReportDefinition, TReportType } from "@/services/reports.service";
import { BUILT_IN_REPORTS } from "./constants";

type Props = {
  activeBuiltIn: TReportType | null;
  activeSavedId: string | null;
  saved: TReportDefinition[];
  isLoading: boolean;
  onSelectBuiltIn: (type: TReportType) => void;
  onSelectSaved: (id: string) => void;
};

const itemClass = (active: boolean) =>
  `w-full rounded-md px-3 py-2 text-left text-13 outline-none focus-visible:ring-2 focus-visible:ring-accent-strong ${
    active ? "bg-layer-1 font-medium text-primary" : "text-secondary hover:bg-layer-1"
  }`;

export function ReportsSidebar(props: Props) {
  const { activeBuiltIn, activeSavedId, saved, isLoading, onSelectBuiltIn, onSelectSaved } = props;
  return (
    <nav aria-label="Reports" className="flex w-full shrink-0 flex-col gap-4 md:w-64">
      <section>
        <h2 className="px-3 pb-1 text-11 font-medium tracking-wide text-tertiary uppercase">Built-in</h2>
        <ul className="space-y-0.5">
          {BUILT_IN_REPORTS.map((report) => (
            <li key={report.type}>
              <button
                type="button"
                className={itemClass(!activeSavedId && activeBuiltIn === report.type)}
                aria-current={!activeSavedId && activeBuiltIn === report.type ? "page" : undefined}
                onClick={() => onSelectBuiltIn(report.type)}
              >
                {report.title}
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="px-3 pb-1 text-11 font-medium tracking-wide text-tertiary uppercase">Saved reports</h2>
        {isLoading ? (
          <p className="px-3 text-13 text-tertiary">Loading…</p>
        ) : saved.length === 0 ? (
          <p className="px-3 text-13 text-tertiary">Nothing saved yet. Use “Save as report” on any report.</p>
        ) : (
          <ul className="space-y-0.5">
            {saved.map((report) => (
              <li key={report.id}>
                <button
                  type="button"
                  className={itemClass(activeSavedId === report.id)}
                  aria-current={activeSavedId === report.id ? "page" : undefined}
                  onClick={() => onSelectSaved(report.id)}
                >
                  <span className="block truncate">{report.name}</span>
                  <span className="block text-11 text-tertiary">
                    {report.is_shared ? "Shared with project" : "Only you"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </nav>
  );
}
