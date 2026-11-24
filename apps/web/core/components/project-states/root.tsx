/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// components
import { EUserPermissionsLevel } from "@plane/constants";
import type { IState, TStateOperationsCallbacks } from "@plane/types";
import { EUserProjectRoles } from "@plane/types";
import { ProjectStateLoader, GroupList } from "@/components/project-states";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
import { useUserPermissions } from "@/hooks/store/user";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";
import { projectStateService } from "@/services/project/project-state.service";
import { workItemTypesService } from "@/services/work-item-types.service";

type TProjectState = {
  workspaceSlug: string;
  projectId: string;
};

export const ProjectStateRoot = observer(function ProjectStateRoot(props: TProjectState) {
  const { workspaceSlug, projectId } = props;
  // hooks
  const {
    groupedProjectStates,
    fetchProjectStates,
    createState,
    moveStatePosition,
    updateState,
    deleteState,
    markStateAsDefault,
  } = useProjectState();
  const { allowPermissions } = useUserPermissions();
  const { types, isEnabled: typesEnabled } = useProjectWorkItemTypes(projectId);
  const [selectedTypeId, setSelectedTypeId] = useState("");
  const { data: typedStates } = useSWR(
    selectedTypeId ? `PROJECT_STATES_${workspaceSlug}_${projectId}_${selectedTypeId}` : null,
    () => projectStateService.getStates(workspaceSlug, projectId, selectedTypeId),
    { revalidateIfStale: false, revalidateOnFocus: false }
  );
  const { data: allStates, mutate: mutateAllStates } = useSWR(
    workspaceSlug && projectId ? `PROJECT_STATES_WITH_USAGE_${workspaceSlug}_${projectId}` : null,
    () => projectStateService.getStates(workspaceSlug.toString(), projectId.toString()),
    { revalidateIfStale: false, revalidateOnFocus: false }
  );
  // derived values
  const isEditable = allowPermissions(
    [EUserProjectRoles.ADMIN],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );
  const { data: workflows } = useSWR(
    typesEnabled && isEditable ? `STATE_WORKFLOWS_${projectId}` : null,
    () => workItemTypesService.listWorkflows(workspaceSlug, projectId)
  );
  const workflowOptions = (workflows ?? [])
    .filter((workflow) => workflow.is_active)
    .map((workflow) => ({ id: workflow.id, name: workflow.name }));

  // Fetching all project states
  useSWR(
    workspaceSlug && projectId ? `PROJECT_STATES_${workspaceSlug}_${projectId}` : null,
    workspaceSlug && projectId ? () => fetchProjectStates(workspaceSlug.toString(), projectId.toString()) : null,
    { revalidateIfStale: false, revalidateOnFocus: false }
  );

  // State operations callbacks
  const stateOperationsCallbacks: TStateOperationsCallbacks = useMemo(
    () => ({
      createState: async (data: Partial<IState>) => {
        const created = await createState(workspaceSlug, projectId, data);
        await Promise.all([mutateAllStates(), fetchProjectStates(workspaceSlug.toString(), projectId.toString())]);
        return created;
      },
      updateState: async (stateId: string, data: Partial<IState>) =>
        updateState(workspaceSlug, projectId, stateId, data),
      deleteState: async (stateId: string) => deleteState(workspaceSlug, projectId, stateId),
      moveStatePosition: async (stateId: string, data: Partial<IState>) =>
        moveStatePosition(workspaceSlug, projectId, stateId, data),
      markStateAsDefault: async (stateId: string) => markStateAsDefault(workspaceSlug, projectId, stateId),
    }),
    [
      workspaceSlug,
      projectId,
      createState,
      moveStatePosition,
      updateState,
      deleteState,
      markStateAsDefault,
      mutateAllStates,
      fetchProjectStates,
    ]
  );

  // Loader
  if (!groupedProjectStates) return <ProjectStateLoader />;

  const displayedStates = selectedTypeId ? typedStates : allStates;
  const displayedGroups = displayedStates
    ? displayedStates.reduce<Record<string, IState[]>>((groups, state) => {
        (groups[state.group] ??= []).push(state);
        return groups;
      }, {})
    : groupedProjectStates;

  return (
    <div className="space-y-4">
      {typesEnabled && (
        <label className="flex items-center gap-3 text-13 text-secondary">
          <span>Show states for</span>
          <select
            aria-label="Show states for work item type"
            className="h-8 rounded-md border border-subtle bg-surface-1 px-2 text-primary"
            value={selectedTypeId}
            onChange={(event) => setSelectedTypeId(event.target.value)}
          >
            <option value="">All states</option>
            {types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
          </select>
        </label>
      )}
      {selectedTypeId && !typedStates ? <ProjectStateLoader /> : (
        <GroupList
          groupedStates={displayedGroups}
          stateOperationsCallbacks={stateOperationsCallbacks}
          isEditable={isEditable}
          shouldTrackEvents
          workflows={workflowOptions}
        />
      )}
    </div>
  );
});
