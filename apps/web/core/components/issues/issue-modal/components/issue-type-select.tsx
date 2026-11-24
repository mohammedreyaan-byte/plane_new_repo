/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// ui
import { CustomSelect } from "@plane/ui";
import { cn } from "@plane/utils";
// components
import { IssueTypeIcon, resolveIssueTypeIcon } from "@/components/issues/issue-type-icon";
// hooks
import { useIssueTypes } from "@/hooks/use-issue-types";

type Props = {
  value: string | null | undefined;
  onChange: (typeId: string) => void;
  tabIndex?: number;
};

/** Issue type picker (Epic, Story, Task, Bug, Sub-task) for the create / edit issue form. Jira-style chip + menu. */
export const IssueTypeSelect = observer(function IssueTypeSelect(props: Props) {
  const { value, onChange, tabIndex } = props;
  const { issueTypes, getIssueTypeById } = useIssueTypes();

  const selected = getIssueTypeById(value);
  if (issueTypes.length === 0) return null;
  const selectedIcon = resolveIssueTypeIcon(selected);

  return (
    <CustomSelect
      value={selected?.id}
      onChange={onChange}
      tabIndex={tabIndex}
      label={
        <span className="flex items-center gap-1.5 text-13 font-medium">
          <IssueTypeIcon icon={selectedIcon.icon} color={selectedIcon.color} size="md" />
          {selected?.name ?? "Issue type"}
        </span>
      }
      buttonClassName="h-full rounded-md border border-[#388bff] bg-[#e9f2ff] px-2.5 py-1 text-[#0c66e4] hover:bg-[#cfe1fd]"
      optionsClassName="min-w-44 rounded-xl border-0 p-1.5 shadow-lg"
      placement="bottom-start"
      noChevron
    >
      {issueTypes.map((type) => {
        const isSelected = type.id === selected?.id;
        const typeIcon = resolveIssueTypeIcon(type);
        return (
          <CustomSelect.Option
            key={type.id}
            value={type.id}
            className={cn("rounded-md px-2.5 py-2 text-13 text-primary", {
              "border-l-2 border-[#1868db] bg-[#e9f2ff] text-[#0c66e4]": isSelected,
            })}
          >
            <span className="flex items-center gap-2.5">
              <IssueTypeIcon icon={typeIcon.icon} color={typeIcon.color} size="md" />
              {type.name}
            </span>
          </CustomSelect.Option>
        );
      })}
    </CustomSelect>
  );
});
