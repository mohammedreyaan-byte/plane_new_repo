/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useProjectState } from "@/hooks/store/use-project-state";
import { useUserPermissions } from "@/hooks/store/user";
import { useAllowedTransitions } from "@/hooks/use-allowed-transitions";
import { TransitionCommentModal } from "@/components/work-item-types";
import type { TWorkflowErrorBody } from "@/services/work-item-types.service";
import { workItemTypesService } from "@/services/work-item-types.service";
// local imports
import type { TWorkItemStateDropdownBaseProps } from "./base";
import { WorkItemStateDropdownBase } from "./base";

type TWorkItemStateDropdownProps = Omit<
  TWorkItemStateDropdownBaseProps,
  "stateIds" | "getStateById" | "onDropdownOpen" | "isInitializing"
> & {
  stateIds?: string[];
};

export const StateDropdown = observer(function StateDropdown(props: TWorkItemStateDropdownProps) {
  const { projectId, stateIds: propsStateIds, issueId, onChange, value } = props;
  // router params
  const { workspaceSlug } = useParams();
  // states
  const [stateLoader, setStateLoader] = useState(false);
  const [isOpened, setIsOpened] = useState(false);
  const [pendingStateId, setPendingStateId] = useState<string | null>(null);
  // store hooks
  const { fetchProjectStates, getProjectStateIds, getStateById } = useProjectState();
  const { fetchIssue } = useIssueDetail();
  const { allowPermissions } = useUserPermissions();
  // derived values
  const stateIds = propsStateIds ?? getProjectStateIds(projectId);
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);

  // workflow rules (only when the dropdown belongs to a work item in a project with types on)
  const {
    transitions,
    denied,
    refetch: refetchAllowedTransitions,
  } = useAllowedTransitions(projectId, issueId, value, isOpened);
  const pendingState = pendingStateId ? getStateById(pendingStateId) : undefined;

  const showTransitionError = (error: unknown) => {
    const body = error as TWorkflowErrorBody | undefined;
    setToast({
      type: TOAST_TYPE.ERROR,
      title: "Error!",
      // Never apply a local state change when the server refused the move.
      message: body?.error?.message ?? "This state change is not allowed.",
    });
  };

  const refetchAfterDenial = async () => {
    void refetchAllowedTransitions();
    if (workspaceSlug && projectId && issueId) {
      try {
        await fetchIssue(workspaceSlug.toString(), projectId, issueId);
      } catch {
        // The allowed-list refresh already restores the menu; the item fetch is best effort.
      }
    }
  };

  const applyStateChange = async (stateId: string) => {
    // Work items without workflow rules keep the original optimistic update path.
    if (!transitions || !workspaceSlug || !projectId || !issueId) {
      onChange(stateId);
      return;
    }
    try {
      await workItemTypesService.transitionWorkItem(
        workspaceSlug.toString(),
        projectId,
        issueId,
        stateId,
        undefined,
        transitions.find((t) => t.to_state_id === stateId)?.transition_id
      );
      onChange(stateId);
    } catch (error) {
      showTransitionError(error);
      await refetchAfterDenial();
    }
  };

  const handleChange = (stateId: string) => {
    const needsComment = transitions?.find((t) => t.to_state_id === stateId)?.requires_comment;
    if (needsComment && issueId && stateId !== value) {
      setPendingStateId(stateId);
      return;
    }
    void applyStateChange(stateId);
  };

  // A transition that needs a comment goes through the transition endpoint, which stores the comment.
  // Calling onChange afterwards is a no-op on the server but updates the local stores.
  const submitComment = async (comment: string) => {
    if (!workspaceSlug || !projectId || !issueId || !pendingStateId) return;
    try {
      await workItemTypesService.transitionWorkItem(
        workspaceSlug.toString(),
        projectId,
        issueId,
        pendingStateId,
        comment,
        transitions?.find((t) => t.to_state_id === pendingStateId)?.transition_id
      );
      onChange(pendingStateId);
      setPendingStateId(null);
    } catch (error) {
      showTransitionError(error);
      await refetchAfterDenial();
    }
  };

  // fetch states if not provided
  const onDropdownOpen = async () => {
    setIsOpened(true);
    if ((stateIds === undefined || stateIds.length === 0) && workspaceSlug && projectId) {
      setStateLoader(true);
      await fetchProjectStates(workspaceSlug.toString(), projectId);
      setStateLoader(false);
    }
  };

  return (
    <>
      <WorkItemStateDropdownBase
        {...props}
        allowedTransitions={transitions}
        deniedTransitions={denied}
        isAdmin={isAdmin}
        onChange={handleChange}
        getStateById={getStateById}
        isInitializing={stateLoader}
        stateIds={stateIds ?? []}
        onDropdownOpen={onDropdownOpen}
      />
      <TransitionCommentModal
        isOpen={Boolean(pendingStateId)}
        stateName={pendingState?.name ?? ""}
        onClose={() => setPendingStateId(null)}
        onSubmit={submitComment}
      />
    </>
  );
});
