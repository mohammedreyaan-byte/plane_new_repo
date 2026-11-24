/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { action, computed, makeObservable, observable } from "mobx";
import { computedFn } from "mobx-utils";
import { DRAG_ALLOWED_GROUPS } from "@plane/constants";
// types
import type { TIssueGroupByOptions, TWorkflowBoardMetadata } from "@plane/types";
// constants
// store
import type { IssueRootStore } from "./root.store";

export interface IIssueKanBanViewStore {
  kanBanToggle: {
    groupByHeaderMinMax: string[];
    subgroupByIssuesVisibility: string[];
  };
  isDragging: boolean;
  /** Workflow-aware board payload returned by the issues list endpoint. */
  boardMetadata: TWorkflowBoardMetadata | null;
  collapsedColumns: string[];
  // computed
  getCanUserDragDrop: (
    group_by: TIssueGroupByOptions | undefined,
    sub_group_by: TIssueGroupByOptions | undefined
  ) => boolean;
  canUserDragDropVertically: boolean;
  canUserDragDropHorizontally: boolean;
  // actions
  handleKanBanToggle: (toggle: "groupByHeaderMinMax" | "subgroupByIssuesVisibility", value: string) => void;
  setIsDragging: (isDragging: boolean) => void;
  setBoardMetadata: (metadata: TWorkflowBoardMetadata | null) => void;
  toggleCollapsedColumn: (stateId: string) => void;
}

const COLLAPSED_COLUMNS_KEY = "plane-workflow-board-collapsed-columns";

function readCollapsedColumns(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const stored = window.localStorage.getItem(COLLAPSED_COLUMNS_KEY);
    const parsed = stored ? JSON.parse(stored) : [];
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export class IssueKanBanViewStore implements IIssueKanBanViewStore {
  kanBanToggle: {
    groupByHeaderMinMax: string[];
    subgroupByIssuesVisibility: string[];
  } = { groupByHeaderMinMax: [], subgroupByIssuesVisibility: [] };
  isDragging = false;
  boardMetadata: TWorkflowBoardMetadata | null = null;
  collapsedColumns: string[] = readCollapsedColumns();
  // root store
  rootStore;

  constructor(_rootStore: IssueRootStore) {
    makeObservable(this, {
      kanBanToggle: observable,
      isDragging: observable.ref,
      boardMetadata: observable.ref,
      collapsedColumns: observable,
      // computed
      canUserDragDropVertically: computed,
      canUserDragDropHorizontally: computed,

      // actions
      handleKanBanToggle: action,
      setIsDragging: action.bound,
      setBoardMetadata: action.bound,
      toggleCollapsedColumn: action.bound,
    });

    this.rootStore = _rootStore;
  }

  setIsDragging = (isDragging: boolean) => {
    this.isDragging = isDragging;
  };

  getCanUserDragDrop = computedFn(
    (group_by: TIssueGroupByOptions | undefined, sub_group_by: TIssueGroupByOptions | undefined) => {
      if (group_by && DRAG_ALLOWED_GROUPS.includes(group_by)) {
        if (!sub_group_by) return true;
        if (sub_group_by && DRAG_ALLOWED_GROUPS.includes(sub_group_by)) return true;
      }
      return false;
    }
  );

  get canUserDragDropVertically() {
    return false;
  }

  get canUserDragDropHorizontally() {
    return false;
  }

  setBoardMetadata = (metadata: TWorkflowBoardMetadata | null) => {
    this.boardMetadata = metadata;
  };

  toggleCollapsedColumn = (stateId: string) => {
    this.collapsedColumns = this.collapsedColumns.includes(stateId)
      ? this.collapsedColumns.filter((item) => item !== stateId)
      : [...this.collapsedColumns, stateId];
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(COLLAPSED_COLUMNS_KEY, JSON.stringify(this.collapsedColumns));
      } catch {
        // Persistence is best effort; in-memory state still works.
      }
    }
  };

  handleKanBanToggle = (toggle: "groupByHeaderMinMax" | "subgroupByIssuesVisibility", value: string) => {
    this.kanBanToggle = {
      ...this.kanBanToggle,
      [toggle]: this.kanBanToggle[toggle].includes(value)
        ? this.kanBanToggle[toggle].filter((v) => v !== value)
        : [...this.kanBanToggle[toggle], value],
    };
  };
}
