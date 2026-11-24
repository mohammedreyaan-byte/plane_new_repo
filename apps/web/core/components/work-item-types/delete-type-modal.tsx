/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Button } from "@plane/propel/button";
import type { TWorkItemType, TWorkflowErrorBody } from "@/services/work-item-types.service";
import { IssueTypeIcon, resolveIssueTypeIcon } from "@/components/issues/issue-type-icon";

type Props = {
  type: TWorkItemType | null;
  error: unknown;
  busy: boolean;
  onClose: () => void;
  onConfirm: (force: boolean) => void;
};

/** Guarded delete. Work items require an explicit second confirmation. */
export function DeleteTypeModal(props: Props) {
  const { type, error, busy, onClose, onConfirm } = props;
  const [force, setForce] = useState(false);
  if (!type) return null;

  const body = error as TWorkflowErrorBody | undefined;
  const code = body?.error?.code;
  const message = body?.error?.message;
  const needsForce = code === "type_in_use";
  const icon = resolveIssueTypeIcon(type);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-md space-y-4 rounded-lg border border-subtle bg-surface-1 p-5">
        <div className="flex items-center gap-3">
          <IssueTypeIcon icon={icon.icon} color={icon.color} size="lg" />
          <div>
            <h2 className="text-16 font-semibold text-primary">Delete {type.name}?</h2>
            <p className="text-12 text-tertiary">Key: {type.key}</p>
          </div>
        </div>
        {message ? (
          <p className="rounded-md bg-layer-1 p-3 text-13 text-danger" role="alert">
            {message}
          </p>
        ) : (
          <p className="text-13 text-secondary">
            This removes the type from the workspace catalogue. Projects must choose a different default first.
          </p>
        )}
        {needsForce && (
          <label className="flex items-start gap-2 text-13 text-secondary">
            <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
            Move affected work items to each project&apos;s default type before deleting.
          </label>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="error-fill"
            size="sm"
            disabled={busy || (needsForce && !force)}
            onClick={() => onConfirm(force)}
          >
            {busy ? "Deleting…" : "Delete type"}
          </Button>
        </div>
      </div>
    </div>
  );
}
