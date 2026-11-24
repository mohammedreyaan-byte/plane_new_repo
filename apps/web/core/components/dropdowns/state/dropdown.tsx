/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
import { useAllowedTransitions } from "@/hooks/use-allowed-transitions";
import { TransitionCommentModal } from "@/components/work-item-types";
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
  // derived values
  const stateIds = propsStateIds ?? getProjectStateIds(projectId);

  // workflow rules (only when the dropdown belongs to a work item in a project with types on)
  const { transitions } = useAllowedTransitions(projectId, issueId, value, isOpened);
  const pendingState = pendingStateId ? getStateById(pendingStateId) : undefined;

  const handleChange = (stateId: string) => {
    const needsComment = transitions?.find((t) => t.to_state_id === stateId)?.requires_comment;
    if (needsComment && issueId && stateId !== value) {
      setPendingStateId(stateId);
      return;
    }
    onChange(stateId);
  };

  // A transition that needs a comment goes through the transition endpoint, which stores the comment.
  // Calling onChange afterwards is a no-op on the server but updates the local stores.
  const submitComment = async (comment: string) => {
    if (!workspaceSlug || !projectId || !issueId || !pendingStateId) return;
    await workItemTypesService.transitionWorkItem(
      workspaceSlug.toString(),
      projectId,
      issueId,
      pendingStateId,
      comment
    );
    onChange(pendingStateId);
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
