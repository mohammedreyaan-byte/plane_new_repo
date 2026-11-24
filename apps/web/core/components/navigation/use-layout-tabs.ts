/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { MouseEvent } from "react";
import { useCallback } from "react";
import { useNavigate } from "react-router";
// plane imports
import { EIssueFilterType } from "@plane/constants";
import { EIssuesStoreType } from "@plane/types";
// hooks
import { useIssues } from "@/hooks/store/use-issues";
// local imports
import type { TNavigationItem } from "./tab-navigation-root";

/**
 * Jira-style Issues / Board / Timeline tabs are three views of the same project work items page.
 * This hook exposes the project's current layout (to decide which tab is active) and a click handler
 * that sets the layout *before* navigating, so the page doesn't reload the previously saved layout.
 */
export const useLayoutTabs = (workspaceSlug: string, projectId: string) => {
  const navigate = useNavigate();
  const { issuesFilter } = useIssues(EIssuesStoreType.PROJECT);

  const currentLayout = issuesFilter.getIssueFilters(projectId)?.displayFilters?.layout;

  const handleLayoutTabClick = useCallback(
    async (e: MouseEvent, item: TNavigationItem) => {
      // regular tabs keep their normal link navigation
      if (!item.layout) return;
      e.preventDefault();
      try {
        // updateFilters is a no-op until the project's filters are loaded (e.g. when coming from Sprints)
        if (!issuesFilter.getIssueFilters(projectId)) await issuesFilter.fetchFilters(workspaceSlug, projectId);
        await issuesFilter.updateFilters(workspaceSlug, projectId, EIssueFilterType.DISPLAY_FILTERS, {
          layout: item.layout,
        });
      } catch (error) {
        // still navigate; the page will open with the last saved layout
        console.error("Failed to switch work item layout", error);
      }
      navigate(item.href);
    },
    [issuesFilter, navigate, projectId, workspaceSlug]
  );

  return { currentLayout, handleLayoutTabClick };
};
