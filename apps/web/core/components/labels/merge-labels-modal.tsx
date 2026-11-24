/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IIssueLabel } from "@plane/types";
import { ModalCore } from "@plane/ui";
// hooks
import { useLabel } from "@/hooks/store/use-label";
// services
import type { TLabelMergePreview } from "@/services/issue";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
  projectId: string;
  target: IIssueLabel | null;
  candidates: IIssueLabel[];
};

const errorMessage = (error: unknown, fallback: string) => {
  const body = error as { error?: { message?: string } } | undefined;
  return body?.error?.message ?? (typeof error === "string" ? error : fallback);
};

/** Admin-only duplicate resolution with a preview before any issue is repointed. */
export const MergeLabelsModal = observer(function MergeLabelsModal(props: Props) {
  const { isOpen, onClose, workspaceSlug, projectId, target, candidates } = props;
  const { mergeProjectLabels } = useLabel();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<TLabelMergePreview | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !target) return;
    const ids = candidates.filter((candidate) => candidate.id !== target.id).map((candidate) => candidate.id);
    setSelectedIds(ids);
    setError(null);
    setPreview(null);
    if (ids.length === 0) return;

    let cancelled = false;
    void (async () => {
      try {
        const result = await mergeProjectLabels(workspaceSlug, projectId, {
          target_id: target.id,
          source_ids: ids,
          preview: true,
        });
        if (!cancelled) setPreview(result);
      } catch (requestError: unknown) {
        if (!cancelled) setError(errorMessage(requestError, "The merge preview could not be loaded."));
      }
    })();
    return () => {
      cancelled = true;
    };
    // The candidate list is derived from the selected label and the current label map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, target?.id, workspaceSlug, projectId]);

  const refreshPreview = async (ids: string[]) => {
    if (!target || ids.length === 0) {
      setPreview(null);
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      setPreview(
        await mergeProjectLabels(workspaceSlug, projectId, { target_id: target.id, source_ids: ids, preview: true })
      );
    } catch (requestError) {
      setError(errorMessage(requestError, "The merge preview could not be loaded."));
    } finally {
      setIsLoading(false);
    }
  };

  const toggleSource = async (id: string) => {
    const next = selectedIds.includes(id) ? selectedIds.filter((value) => value !== id) : [...selectedIds, id];
    setSelectedIds(next);
    await refreshPreview(next);
  };

  const applyMerge = async () => {
    if (!target || selectedIds.length === 0) return;
    setIsLoading(true);
    setError(null);
    try {
      await mergeProjectLabels(workspaceSlug, projectId, {
        target_id: target.id,
        source_ids: selectedIds,
        preview: false,
      });
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Success!", message: "Duplicate labels merged." });
      onClose();
    } catch (requestError) {
      setError(errorMessage(requestError, "The labels could not be merged."));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} className="max-w-xl">
      <div className="space-y-4 p-6">
        <div>
          <h2 className="text-16 font-semibold text-primary">Merge duplicate labels</h2>
          <p className="mt-1 text-13 text-secondary">
            Keep <span className="font-medium text-primary">{target?.name}</span> and repoint work items from the
            selected duplicates. Nothing changes until you apply.
          </p>
        </div>

        {candidates.length === 0 ? (
          <p className="rounded-sm border border-subtle p-3 text-13 text-tertiary">
            No case-insensitive duplicates were found for this label.
          </p>
        ) : (
          <div className="max-h-52 space-y-2 overflow-y-auto rounded-sm border border-subtle p-3">
            {candidates.map((candidate) => (
              <label key={candidate.id} className="flex items-center gap-2 text-13 text-secondary">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(candidate.id)}
                  onChange={() => void toggleSource(candidate.id)}
                  disabled={isLoading}
                />
                <span className="flex-grow">{candidate.name}</span>
                <span className="text-11 text-tertiary">{candidate.issue_count ?? 0} items</span>
              </label>
            ))}
          </div>
        )}

        {preview && (
          <div className="rounded-sm bg-surface-2 p-3 text-13 text-secondary">
            Preview: {preview.affected_issue_count} work item{preview.affected_issue_count === 1 ? "" : "s"} will be
            repointed to <span className="font-medium text-primary">{preview.target.name}</span>.
          </div>
        )}
        {error && <p className="text-13 text-danger-secondary">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void applyMerge()} disabled={isLoading || selectedIds.length === 0}>
            {isLoading ? "Working..." : "Merge"}
          </Button>
        </div>
      </div>
    </ModalCore>
  );
});
