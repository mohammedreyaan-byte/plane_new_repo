/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TReportResult } from "@/services/reports.service";

type Props = { summary?: TReportResult["meta"]["summary"] };

const TILES: { key: "open" | "resolved" | "cancelled"; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "resolved", label: "Resolved" },
  { key: "cancelled", label: "Cancelled" },
];

/** Open / resolved / cancelled for the current scope. Cancelled is never folded into resolved. */
export function ReportCard({ summary }: Props) {
  if (!summary || summary.open === undefined) return null;
  return (
    <dl className="grid grid-cols-3 gap-3">
      {TILES.map((tile) => (
        <div key={tile.key} className="rounded-md border border-subtle bg-surface-1 p-3">
          <dt className="text-11 text-tertiary">{tile.label}</dt>
          <dd className="mt-1 text-18 font-semibold text-primary">{summary[tile.key] ?? 0}</dd>
        </div>
      ))}
    </dl>
  );
}
