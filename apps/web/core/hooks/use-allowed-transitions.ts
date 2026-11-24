/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useParams } from "next/navigation";
import useSWR from "swr";
import { workItemTypesService } from "@/services/work-item-types.service";
import type { TAllowedTransition } from "@/services/work-item-types.service";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";

/**
 * The state moves the current user may make on a work item. Only fetched when `enabled` (dropdown open)
 * and the project has work item types switched on; otherwise it returns `transitions: null`,
 * which means "no restriction, show every state".
 */
export const useAllowedTransitions = (
  projectId: string | null | undefined,
  issueId: string | null | undefined,
  currentStateId: string | null | undefined,
  enabled: boolean
) => {
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString();
  const { isEnabled } = useProjectWorkItemTypes(projectId);
  const shouldFetch = Boolean(enabled && isEnabled && slug && projectId && issueId);
  const { data, isLoading } = useSWR(
    shouldFetch ? `ALLOWED_TRANSITIONS_${issueId}_${currentStateId}` : null,
    shouldFetch ? () => workItemTypesService.getAllowedTransitions(slug!, projectId!, issueId!) : null,
    { revalidateOnFocus: false, dedupingInterval: 0 }
  );
  const transitions: TAllowedTransition[] | null = data && data.workflow_id ? data.transitions : null;
  return { transitions, isLoading };
};
