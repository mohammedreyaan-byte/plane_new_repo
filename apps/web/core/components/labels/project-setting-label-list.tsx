/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState, useRef } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { orderBy } from "lodash-es";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { EmptyStateCompact } from "@plane/propel/empty-state";
import { SearchIcon } from "@plane/propel/icons";
import type { IIssueLabel } from "@plane/types";
import { Loader } from "@plane/ui";
import type { TLabelOperationsCallbacks } from "@/components/labels";
import {
  CreateUpdateLabelInline,
  DeleteLabelModal,
  MergeLabelsModal,
  ProjectSettingLabelGroup,
  ProjectSettingLabelItem,
} from "@/components/labels";
// hooks
import { useLabel } from "@/hooks/store/use-label";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { SettingsHeading } from "../settings/heading";

export const ProjectSettingsLabelList = observer(function ProjectSettingsLabelList() {
  // router
  const { workspaceSlug, projectId } = useParams();
  // refs
  const scrollToRef = useRef<HTMLDivElement>(null);
  // states
  const [showLabelForm, setLabelForm] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [selectDeleteLabel, setSelectDeleteLabel] = useState<IIssueLabel | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState<"sort_order" | "name" | "usage" | "created">("sort_order");
  const [mergeTarget, setMergeTarget] = useState<IIssueLabel | null>(null);
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const { projectLabels, updateLabelPosition, projectLabelsTree, createLabel, updateLabel } = useLabel();
  const { allowPermissions } = useUserPermissions();
  // derived values
  const isEditable = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);
  const normalizedQuery = searchQuery.trim().toLowerCase();
  const displayedLabels = orderBy(
    (projectLabels ?? []).filter((label) => !normalizedQuery || label.name.toLowerCase().includes(normalizedQuery)),
    [
      (label) =>
        sortBy === "name"
          ? label.name.toLowerCase()
          : sortBy === "usage"
            ? (label.issue_count ?? 0)
            : sortBy === "created"
              ? (label.created_at ?? "")
              : label.sort_order,
    ],
    [sortBy === "name" || sortBy === "sort_order" ? "asc" : "desc"]
  );
  const isFlatList = !!normalizedQuery || sortBy !== "sort_order";
  const mergeCandidates = mergeTarget
    ? (projectLabels ?? []).filter(
        (label) => label.id !== mergeTarget.id && label.name.toLowerCase() === mergeTarget.name.toLowerCase()
      )
    : [];
  const labelOperationsCallbacks: TLabelOperationsCallbacks = {
    createLabel: (data: Partial<IIssueLabel>) => createLabel(workspaceSlug?.toString(), projectId?.toString(), data),
    updateLabel: (labelId: string, data: Partial<IIssueLabel>) =>
      updateLabel(workspaceSlug?.toString(), projectId?.toString(), labelId, data),
  };

  const newLabel = () => {
    setIsUpdating(false);
    setLabelForm(true);
  };

  const onDrop = (
    draggingLabelId: string,
    droppedParentId: string | null,
    droppedLabelId: string | undefined,
    dropAtEndOfList: boolean
  ) => {
    if (workspaceSlug && projectId) {
      updateLabelPosition(
        workspaceSlug?.toString(),
        projectId?.toString(),
        draggingLabelId,
        droppedParentId,
        droppedLabelId,
        dropAtEndOfList
      );
      return;
    }
  };

  return (
    <>
      <DeleteLabelModal
        isOpen={!!selectDeleteLabel}
        data={selectDeleteLabel ?? null}
        onClose={() => setSelectDeleteLabel(null)}
      />
      {workspaceSlug && projectId && (
        <MergeLabelsModal
          isOpen={!!mergeTarget}
          onClose={() => setMergeTarget(null)}
          workspaceSlug={workspaceSlug.toString()}
          projectId={projectId.toString()}
          target={mergeTarget}
          candidates={mergeCandidates}
        />
      )}
      <SettingsHeading
        title={t("project_settings.labels.heading")}
        description={t("project_settings.labels.description")}
        control={
          isEditable && (
            <Button variant="primary" size="lg" onClick={newLabel}>
              {t("common.add_label")}
            </Button>
          )
        }
      />
      <p className="mt-3 text-13 text-tertiary">
        Types classify work; labels are free-form tags. Do not use labels to model Bug/Task/Story/Epic.
      </p>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex flex-1 items-center gap-1.5 rounded-sm border border-subtle bg-surface-2 px-2">
          <SearchIcon className="h-3.5 w-3.5 text-placeholder" strokeWidth={1.5} />
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={t("common.search.label")}
            aria-label={t("common.search.label")}
            className="w-full bg-transparent py-1.5 text-13 text-secondary placeholder:text-placeholder focus:outline-none"
          />
        </div>
        <select
          value={sortBy}
          onChange={(event) => setSortBy(event.target.value as typeof sortBy)}
          aria-label="Sort labels"
          className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13 text-secondary focus:outline-none"
        >
          <option value="sort_order">Sort order</option>
          <option value="name">Name</option>
          <option value="usage">Usage</option>
          <option value="created">Created</option>
        </select>
      </div>
      <div className="mt-6 w-full">
        {showLabelForm && (
          <div className="my-2 w-full rounded-sm border border-subtle px-3.5 py-2">
            <CreateUpdateLabelInline
              labelForm={showLabelForm}
              setLabelForm={setLabelForm}
              isUpdating={isUpdating}
              labelOperationsCallbacks={labelOperationsCallbacks}
              ref={scrollToRef}
              onClose={() => {
                setLabelForm(false);
                setIsUpdating(false);
              }}
            />
          </div>
        )}
        {!projectLabels && !showLabelForm ? (
          <Loader className="space-y-5">
            <Loader.Item height="42px" />
            <Loader.Item height="42px" />
            <Loader.Item height="42px" />
            <Loader.Item height="42px" />
          </Loader>
        ) : projectLabels?.length === 0 && !showLabelForm ? (
          <EmptyStateCompact
            assetKey="label"
            assetClassName="size-20"
            title={t("settings_empty_state.labels.title")}
            description={t("settings_empty_state.labels.description")}
            actions={[
              {
                label: t("settings_empty_state.labels.cta_primary"),
                onClick: () => {
                  newLabel();
                },
              },
            ]}
            align="start"
            rootClassName="py-20"
          />
        ) : isFlatList ? (
          displayedLabels.length === 0 ? (
            <p className="py-10 text-center text-13 text-tertiary">No labels match your search.</p>
          ) : (
            displayedLabels.map((label, index) => (
              <ProjectSettingLabelItem
                key={label.id}
                label={label}
                setIsUpdating={setIsUpdating}
                handleLabelDelete={(item) => setSelectDeleteLabel(item)}
                isChild={false}
                isLastChild={index === displayedLabels.length - 1}
                onDrop={onDrop}
                isEditable={isEditable}
                labelOperationsCallbacks={labelOperationsCallbacks}
                onMergeDuplicates={isEditable ? setMergeTarget : undefined}
              />
            ))
          )
        ) : (
          projectLabelsTree?.map((label, index) => {
            const mergeCallback = isEditable ? setMergeTarget : undefined;
            if (label.children && label.children.length) {
              return (
                <ProjectSettingLabelGroup
                  key={label.id}
                  label={label}
                  labelChildren={label.children || []}
                  handleLabelDelete={(item: IIssueLabel) => setSelectDeleteLabel(item)}
                  isUpdating={isUpdating}
                  setIsUpdating={setIsUpdating}
                  isLastChild={index === (projectLabelsTree?.length ?? 0) - 1}
                  onDrop={onDrop}
                  isEditable={isEditable}
                  labelOperationsCallbacks={labelOperationsCallbacks}
                  onMergeDuplicates={mergeCallback}
                />
              );
            }
            return (
              <ProjectSettingLabelItem
                label={label}
                key={label.id}
                setIsUpdating={setIsUpdating}
                handleLabelDelete={(item) => setSelectDeleteLabel(item)}
                isChild={false}
                isLastChild={index === (projectLabelsTree?.length ?? 0) - 1}
                onDrop={onDrop}
                isEditable={isEditable}
                labelOperationsCallbacks={labelOperationsCallbacks}
                onMergeDuplicates={mergeCallback}
              />
            );
          })
        )}
      </div>
    </>
  );
});
