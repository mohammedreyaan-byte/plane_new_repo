/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TBulkOperationsPayload, TIssuePriorities } from "@plane/types";
import { cn } from "@plane/utils";
// components
import { PriorityDropdown } from "@/components/dropdowns/priority";
import { StateDropdown } from "@/components/dropdowns/state/dropdown";
import { WorkItemTypeSelect } from "@/components/work-item-types";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useIssues } from "@/hooks/store/use-issues";
import { useMultipleSelectStore } from "@/hooks/store/use-multiple-select-store";
import { useIssueStoreType } from "@/hooks/use-issue-layout-store";
import type { TSelectionHelper } from "@/hooks/use-multiple-select";

type Props = {
  className?: string;
  selectionHelpers: TSelectionHelper;
};

/**
 * Appears when work items are selected. Every change is checked by the server per work item with the same
 * rules as a single edit, so a bulk move cannot skip a workflow.
 */
export const IssueBulkOperationsRoot = observer(function IssueBulkOperationsRoot(props: Props) {
  const { className, selectionHelpers } = props;
  const { workspaceSlug } = useParams();
  const storeType = useIssueStoreType();
  const { issues } = useIssues(storeType);
  const {
    issue: { getIssueById },
  } = useIssueDetail();
  const { isSelectionActive, selectedEntityIds, clearSelection } = useMultipleSelectStore();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [typeId, setTypeId] = useState<string | null>(null);

  if (!isSelectionActive || selectionHelpers.isSelectionDisabled || !workspaceSlug) return null;

  const projectIds = Array.from(
    new Set(selectedEntityIds.map((id) => getIssueById(id)?.project_id).filter((id): id is string => !!id))
  );
  const projectId = projectIds.length === 1 ? projectIds[0] : undefined;

  const apply = async (properties: TBulkOperationsPayload["properties"]) => {
    if (!projectId) return;
    setIsSubmitting(true);
    try {
      const result = await issues.bulkUpdateProperties(workspaceSlug.toString(), projectId, {
        issue_ids: selectedEntityIds,
        properties,
      });
      const failed = result?.failed ?? [];
      const updatedCount = result?.updated.length ?? selectedEntityIds.length;
      if (failed.length === 0) {
        setToast({ type: TOAST_TYPE.SUCCESS, title: "Updated", message: `${updatedCount} work items updated.` });
        clearSelection();
      } else {
        // Keep only the work items that did not change selected, so the person can see what to fix.
        const reasons = Array.from(new Set(failed.map((f) => f.message)))
          .slice(0, 2)
          .join(" ");
        setToast({
          type: TOAST_TYPE.WARNING,
          title: `${updatedCount} updated, ${failed.length} not changed`,
          message: reasons,
        });
      }
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error ?? "The work items could not be updated.";
      setToast({ type: TOAST_TYPE.ERROR, title: "Error", message });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className={cn("sticky bottom-0 left-0 z-[2] grid h-20 place-items-center px-3.5", className)}>
      <div className="flex h-14 w-full items-center justify-between gap-3 rounded-md border-[0.5px] border-accent-strong/50 bg-surface-1 px-3.5 py-4 shadow-raised-200">
        <p className="text-13 font-medium text-primary">{selectedEntityIds.length} selected</p>
        {projectId ? (
          <div className="flex items-center gap-2">
            <StateDropdown
              projectId={projectId}
              value={undefined}
              showDefaultState={false}
              buttonVariant="border-with-text"
              disabled={isSubmitting}
              onChange={(stateId) => void apply({ state_id: stateId })}
            />
            <PriorityDropdown
              value={undefined}
              buttonVariant="border-with-text"
              disabled={isSubmitting}
              onChange={(priority: TIssuePriorities) => void apply({ priority })}
            />
            <WorkItemTypeSelect
              projectId={projectId}
              value={typeId}
              disabled={isSubmitting}
              onChange={(id) => {
                setTypeId(id);
                void apply({ type_id: id });
              }}
            />
            <Button variant="secondary" size="sm" onClick={clearSelection} disabled={isSubmitting}>
              Clear
            </Button>
          </div>
        ) : (
          <p className="text-13 text-secondary">Select work items from one project to change them together.</p>
        )}
      </div>
    </div>
  );
});
