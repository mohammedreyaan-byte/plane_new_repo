/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment, useEffect, useState } from "react";
import { observer } from "mobx-react";
import { usePopper } from "react-popper";
import { Loader } from "lucide-react";
import { Combobox } from "@headlessui/react";
// plane imports
import { EUserPermissionsLevel, getRandomLabelColor } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { CheckIcon, SearchIcon, PlusIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IIssueLabel } from "@plane/types";
import { EUserProjectRoles } from "@plane/types";
// helpers
import { getTabIndex } from "@plane/utils";
// hooks
import { useLabel } from "@/hooks/store/use-label";
import { useUserPermissions } from "@/hooks/store/user";
import { usePlatformOS } from "@/hooks/use-platform-os";
//constants
export interface IIssueLabelSelect {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  values: string[];
  onSelect: (_labelIds: string[]) => void;
  onAddLabel: (workspaceSlug: string, projectId: string, data: Partial<IIssueLabel>) => Promise<any>;
}

const MAX_LABELS_PER_ISSUE = 10;
const RECENT_LABEL_LIMIT = 20;
const RECENT_LABELS_SHOWN = 5;

/** Legacy type labels stay readable on historical items but are not offered for new selection. */
const isLegacyTypeLabel = (name: string) => /^type\s*:/i.test(name.trim());

type TLabelOption = {
  value: string;
  query: string;
  content: React.ReactNode;
};

const toOption = (label: IIssueLabel): TLabelOption => ({
  value: label.id,
  query: label.name,
  content: (
    <div className="flex items-center justify-start gap-2 overflow-hidden">
      <span
        className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
        style={{
          backgroundColor: label.color,
        }}
      />
      <div className="line-clamp-1 inline-block truncate">{label.name}</div>
    </div>
  ),
});

const renderOption = (option: TLabelOption) => (
  <Combobox.Option
    key={option.value}
    value={option.value}
    className={({ selected }) =>
      `flex cursor-pointer items-center justify-between gap-2 truncate rounded-sm px-1 py-1.5 select-none hover:bg-layer-1 ${
        selected ? "text-primary" : "text-secondary"
      }`
    }
  >
    {({ selected }) => (
      <>
        {option.content}
        {selected && (
          <div className="flex-shrink-0">
            <CheckIcon className={`h-3.5 w-3.5`} />
          </div>
        )}
      </>
    )}
  </Combobox.Option>
);

export const IssueLabelSelect = observer(function IssueLabelSelect(props: IIssueLabelSelect) {
  const { workspaceSlug, projectId, issueId, values, onSelect, onAddLabel } = props;
  const { t } = useTranslation();
  // store hooks
  const { isMobile } = usePlatformOS();
  const { fetchProjectLabels, getProjectLabels } = useLabel();
  const { allowPermissions } = useUserPermissions();
  // states
  const [referenceElement, setReferenceElement] = useState<HTMLButtonElement | null>(null);
  const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [recentLabelIds, setRecentLabelIds] = useState<string[]>([]);

  const canCreateLabel = allowPermissions(
    [EUserProjectRoles.ADMIN, EUserProjectRoles.MEMBER],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );

  const projectLabels = getProjectLabels(projectId);
  const recentStorageKey = `plane.recent-labels.${workspaceSlug}.${projectId}`;

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(recentStorageKey);
      const parsed: unknown = stored ? JSON.parse(stored) : [];
      setRecentLabelIds(
        Array.isArray(parsed)
          ? parsed.filter((id): id is string => typeof id === "string").slice(0, RECENT_LABEL_LIMIT)
          : []
      );
    } catch {
      setRecentLabelIds([]);
    }
  }, [recentStorageKey]);

  const { baseTabIndex } = getTabIndex(undefined, isMobile);

  const fetchLabels = async () => {
    if (!workspaceSlug || !projectId || projectLabels) return;
    setIsLoading(true);
    try {
      await fetchProjectLabels(workspaceSlug, projectId);
    } finally {
      setIsLoading(false);
    }
  };

  const visibleLabels = (projectLabels ?? []).filter((label) => !isLegacyTypeLabel(label.name));
  const labelsById = new Map(visibleLabels.map((label) => [label.id, label]));
  const options = visibleLabels.map(toOption);
  const recentOptions =
    query === ""
      ? recentLabelIds
          .map((id) => labelsById.get(id))
          .filter((label): label is IIssueLabel => !!label)
          .slice(0, RECENT_LABELS_SHOWN)
          .map(toOption)
      : [];

  const filteredOptions =
    query === "" ? options : options.filter((option) => option.query.toLowerCase().includes(query.toLowerCase()));

  const { styles, attributes } = usePopper(referenceElement, popperElement, {
    placement: "bottom-start",
    modifiers: [
      {
        name: "preventOverflow",
        options: {
          padding: 12,
        },
      },
    ],
  });

  const issueLabels = values ?? [];

  const label = <span className="text-body-xs-medium text-placeholder">{t("label.select")}</span>;

  const showLabelLimitError = () =>
    setToast({
      title: t("toast.error"),
      type: TOAST_TYPE.ERROR,
      message: `You can add at most ${MAX_LABELS_PER_ISSUE} labels to a work item.`,
    });

  const rememberLabels = (labelIds: string[]) => {
    const next = [...labelIds, ...recentLabelIds.filter((id) => !labelIds.includes(id))].slice(0, RECENT_LABEL_LIMIT);
    setRecentLabelIds(next);
    try {
      window.localStorage.setItem(recentStorageKey, JSON.stringify(next));
    } catch {
      // Recent labels are a local convenience only; storage failures must not block updates.
    }
  };

  const handleSelect = (labelIds: string[]) => {
    if (labelIds.length > MAX_LABELS_PER_ISSUE) {
      showLabelLimitError();
      return;
    }
    rememberLabels(labelIds);
    onSelect(labelIds);
  };

  const searchInputKeyDown = async (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (query !== "" && e.key === "Escape") {
      e.stopPropagation();
      setQuery("");
    }

    if (query !== "" && e.key === "Enter" && !e.nativeEvent.isComposing && canCreateLabel) {
      e.stopPropagation();
      e.preventDefault();
      await handleAddLabel(query);
    }
  };

  const handleAddLabel = async (labelName: string) => {
    if (issueLabels.length >= MAX_LABELS_PER_ISSUE) {
      showLabelLimitError();
      return;
    }
    setSubmitting(true);
    try {
      const newLabel = await onAddLabel(workspaceSlug, projectId, { name: labelName, color: getRandomLabelColor() });
      handleSelect([...issueLabels, newLabel.id]);
      setQuery("");
    } catch {
      // The label operation already surfaces the server error in a toast.
    } finally {
      setSubmitting(false);
    }
  };

  if (!issueId || !values) return <></>;

  return (
    <>
      <Combobox
        as="div"
        className="size-full flex-shrink-0 text-left"
        value={issueLabels}
        onChange={handleSelect}
        multiple
      >
        <Combobox.Button as={Fragment}>
          <Button
            ref={setReferenceElement}
            type="button"
            variant="tertiary"
            size="sm"
            prependIcon={<PlusIcon />}
            onClick={() => void fetchLabels()}
          >
            {label}
          </Button>
        </Combobox.Button>

        <Combobox.Options className="fixed z-10">
          <div
            className={`z-10 my-1 w-48 rounded-sm border border-strong bg-surface-1 py-2.5 text-11 whitespace-nowrap shadow-raised-200 focus:outline-none`}
            ref={setPopperElement}
            style={styles.popper}
            {...attributes.popper}
          >
            <div className="px-2">
              <div className="flex w-full items-center justify-start rounded-sm border border-subtle bg-surface-2 px-2">
                <SearchIcon className="h-3.5 w-3.5 text-tertiary" />
                <Combobox.Input
                  className="w-full bg-transparent px-2 py-1 text-11 text-secondary placeholder:text-placeholder focus:outline-none"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("common.search.label")}
                  displayValue={(assigned: any) => assigned?.name}
                  onKeyDown={searchInputKeyDown}
                  tabIndex={baseTabIndex}
                />
              </div>
            </div>
            <div className={`vertical-scrollbar mt-2 scrollbar-sm max-h-48 space-y-1 overflow-y-scroll px-2 pr-0`}>
              {isLoading ? (
                <p className="text-center text-secondary">{t("common.loading")}</p>
              ) : (
                <>
                  {recentOptions.length > 0 && (
                    <div className="mb-1 space-y-1 border-b border-subtle pb-1">
                      <p className="px-1 text-10 text-placeholder uppercase">Recent</p>
                      {recentOptions.map(renderOption)}
                    </div>
                  )}
                  {filteredOptions.length > 0 ? (
                    filteredOptions.map(renderOption)
                  ) : submitting ? (
                    <Loader className="spin h-3.5 w-3.5" />
                  ) : canCreateLabel ? (
                    <Combobox.Option
                      value={query}
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        if (!query.length) return;
                        void handleAddLabel(query);
                      }}
                      className={`text-left text-secondary ${query.length ? "cursor-pointer" : "cursor-default"}`}
                    >
                      {query.length ? (
                        <>
                          {/* TODO: Translate here */}+ Add <span className="text-primary">&quot;{query}&quot;</span> to
                          labels
                        </>
                      ) : (
                        t("label.create.type")
                      )}
                    </Combobox.Option>
                  ) : (
                    <p className="text-left text-secondary">{t("common.search.no_matching_results")}</p>
                  )}
                </>
              )}
            </div>
          </div>
        </Combobox.Options>
      </Combobox>
    </>
  );
});
