/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import type { TIssueGroupByOptions } from "@plane/types";
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useProjectState } from "@/hooks/store/use-project-state";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";
import { workItemTypesService } from "@/services/work-item-types.service";
import type { TAllowedTransitions } from "@/services/work-item-types.service";

// Every column of a board runs this hook and asks the same question when a drag starts, so share one request.
const inflight = new Map<string, Promise<TAllowedTransitions>>();
const fetchAllowed = (workspaceSlug: string, projectId: string, issueId: string, stateId: string) => {
  const key = `${issueId}_${stateId}`;
  let request = inflight.get(key);
  if (!request) {
    request = workItemTypesService.getAllowedTransitions(workspaceSlug, projectId, issueId);
    inflight.set(key, request);
    // Allowed moves can change between drags (a comment, a role change), so do not keep the answer.
    const clear = () => setTimeout(() => inflight.delete(key), 1500);
    request.then(clear, clear);
  }
  return request;
};

/**
 * Workflow rules for board and list drag and drop.
 *
 * Rules only apply when the board is grouped by state, because the groups are then workflow states.
 * `handleWorkFlowState` runs for each column when a drag starts or enters it and decides whether that
 * column accepts the dragged work item. `workflowDisabledSource` is the name of the state being left, set
 * only while the column refuses the drop, so the overlay can explain why.
 */
export const useWorkFlowFDragNDrop = (groupBy: TIssueGroupByOptions | undefined, subGroupBy?: TIssueGroupByOptions) => {
  const { workspaceSlug, projectId } = useParams();
  const slug = workspaceSlug?.toString();
  const projectIdParam = projectId?.toString();
  const { getStateById } = useProjectState();
  const {
    issue: { getIssueById },
  } = useIssueDetail();
  const { isEnabled } = useProjectWorkItemTypes(projectIdParam);
  const [workflowDisabledSource, setWorkflowDisabledSource] = useState<string | undefined>(undefined);
  const [isWorkflowDropDisabled, setIsWorkflowDropDisabled] = useState(false);

  const isStateBoard = groupBy === "state" && !subGroupBy;
  const isStateBoardWithSub = groupBy === "state";

  const reset = useCallback(() => {
    setWorkflowDisabledSource(undefined);
    setIsWorkflowDropDisabled(false);
  }, []);

  const handleWorkFlowState = useCallback(
    async (
      sourceGroupId: string,
      destinationGroupId: string,
      sourceSubGroupId?: string,
      destinationSubGroupId?: string,
      issueId?: string
    ) => {
      const sameCell =
        sourceGroupId === destinationGroupId && (sourceSubGroupId ?? "") === (destinationSubGroupId ?? "");
      if (!isStateBoardWithSub || !isEnabled || !slug || !issueId || sameCell || sourceGroupId === destinationGroupId) {
        reset();
        return;
      }
      const issue = getIssueById(issueId);
      const projectOfIssue = issue?.project_id ?? projectIdParam;
      if (!projectOfIssue) {
        reset();
        return;
      }
      try {
        const result = await fetchAllowed(slug, projectOfIssue, issueId, sourceGroupId);
        // No workflow for this item: nothing to enforce.
        if (!result.workflow_id) {
          reset();
          return;
        }
        const allowed = result.transitions.some((t) => t.to_state_id === destinationGroupId);
        if (allowed) {
          reset();
        } else {
          setWorkflowDisabledSource(getStateById(sourceGroupId)?.name ?? "this state");
          setIsWorkflowDropDisabled(true);
        }
      } catch {
        // If the rules cannot be fetched, let the server decide on drop.
        reset();
      }
    },
    [getIssueById, getStateById, isEnabled, isStateBoardWithSub, projectIdParam, reset, slug]
  );

  // New work items always start in the first state of their workflow, so other columns cannot take quick-adds.
  const { data: initialStateIds } = useSWR(
    isEnabled && isStateBoard && slug && projectIdParam ? `WORKFLOW_INITIAL_STATES_${projectIdParam}` : null,
    async () => {
      const list = await workItemTypesService.listWorkflows(slug!, projectIdParam!);
      const details = await Promise.all(
        list.map((w) => workItemTypesService.getWorkflow(slug!, projectIdParam!, w.id))
      );
      const ids = new Set<string>();
      details.forEach((d) => d.states?.forEach((s) => s.is_initial && ids.add(s.state_id)));
      return Array.from(ids);
    },
    { revalidateOnFocus: false, revalidateIfStale: false }
  );

  const getIsWorkflowWorkItemCreationDisabled = useCallback(
    (groupId: string, _subGroupId?: string) => {
      if (!isStateBoard || !initialStateIds || initialStateIds.length === 0) return false;
      return !initialStateIds.includes(groupId);
    },
    [initialStateIds, isStateBoard]
  );

  return {
    workflowDisabledSource,
    isWorkflowDropDisabled,
    getIsWorkflowWorkItemCreationDisabled,
    handleWorkFlowState,
  };
};
