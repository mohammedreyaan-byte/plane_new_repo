/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useMemo } from "react";
import type { TIssue } from "@plane/types";
import { EIssueLayoutTypes } from "@plane/types";
import type { TNavigationItem } from "@/components/navigation/tab-navigation-root";

// layouts that have their own tab (Board, Timeline); every other layout belongs to the Issues tab
const DEDICATED_LAYOUT_TABS: EIssueLayoutTypes[] = [EIssueLayoutTypes.KANBAN, EIssueLayoutTypes.GANTT];

type UseActiveTabProps = {
  navigationItems: TNavigationItem[];
  pathname: string;
  workItemId?: string;
  workItem?: TIssue;
  projectId: string;
  /** current work item layout of the project (undefined until its filters are loaded) */
  currentLayout?: EIssueLayoutTypes;
};

export const useActiveTab = ({
  navigationItems,
  pathname,
  workItemId,
  workItem,
  projectId,
  currentLayout,
}: UseActiveTabProps) => {
  // Check if a navigation item is active
  const isActive = useCallback(
    (item: TNavigationItem) => {
      // Work item condition
      const workItemCondition = workItemId && workItem && !workItem?.is_epic && workItem?.project_id === projectId;
      // Epic condition
      const epicCondition = workItemId && workItem && workItem?.is_epic && workItem?.project_id === projectId;
      // Is active
      const isWorkItemActive = item.key === "work_items" && workItemCondition;
      const isEpicActive = item.key === "epics" && epicCondition;
      // Pathname condition - use exact match or startsWith for better accuracy
      const isPathnameActive = pathname === item.href || pathname.startsWith(item.href + "/");
      // Board / Timeline share the Issues page, so they are told apart by the current layout
      if (item.layout && DEDICATED_LAYOUT_TABS.includes(item.layout)) {
        return isPathnameActive && currentLayout === item.layout;
      }
      // Issues tab: active on its page unless the Board / Timeline layout is showing
      if (item.key === "work_items" && currentLayout && DEDICATED_LAYOUT_TABS.includes(currentLayout)) {
        return !!isWorkItemActive;
      }
      // Return
      return isWorkItemActive || isEpicActive || isPathnameActive;
    },
    [pathname, workItem, workItemId, projectId, currentLayout]
  );

  // Find active item
  const activeItem = useMemo(() => navigationItems.find((item) => isActive(item)), [navigationItems, isActive]);

  return { isActive, activeItem };
};
