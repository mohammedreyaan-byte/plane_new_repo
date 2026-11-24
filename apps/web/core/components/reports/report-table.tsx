/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TReportResult } from "@/services/reports.service";

/** The table behind every chart. It is also what screen readers get, so it always renders. */
export function ReportTable({ result, caption }: { result: TReportResult; caption: string }) {
  return (
    <div className="overflow-x-auto rounded-md border border-subtle">
      <table className="w-full min-w-[420px] text-left text-13">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-layer-1 text-secondary">
          <tr>
            {result.columns.map((column) => (
              <th key={column.key} scope="col" className="px-3 py-2 font-medium">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row) => (
            <tr
              key={`${result.report}-${String(row[result.columns[0]?.key ?? ""])}`}
              className="border-t border-subtle text-primary"
            >
              {result.columns.map((column) => (
                <td key={column.key} className="px-3 py-2">
                  {row[column.key] ?? ""}
                </td>
              ))}
            </tr>
          ))}
          {result.rows.length === 0 && (
            <tr>
              <td colSpan={result.columns.length} className="px-3 py-4 text-center text-secondary">
                No rows
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
