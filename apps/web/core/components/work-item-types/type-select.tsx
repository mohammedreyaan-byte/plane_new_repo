/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { cn } from "@plane/utils";
import { IssueTypeIcon, resolveIssueTypeIcon } from "@/components/issues/issue-type-icon";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";

type Props = {
  projectId: string | null | undefined;
  value: string | null | undefined;
  onChange: (typeId: string) => void;
  disabled?: boolean;
  className?: string;
};

/** Plain select of the types enabled in the project. Renders nothing while types are off. */
export const WorkItemTypeSelect = observer(function WorkItemTypeSelect(props: Props) {
  const { projectId, value, onChange, disabled = false, className } = props;
  const { types, isEnabled, defaultTypeId } = useProjectWorkItemTypes(projectId);
  if (!isEnabled) return null;
  const selectedId = value ?? defaultTypeId ?? "";
  const selectedIcon = resolveIssueTypeIcon(types.find((type) => type.id === selectedId));
  return (
    // Native <option> can't render SVGs, so the selected type's icon sits next to the select.
    <div className="flex items-center gap-1.5">
      <IssueTypeIcon icon={selectedIcon.icon} color={selectedIcon.color} size="md" />
      <select
        aria-label="Work item type"
        value={selectedId}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "h-7 rounded-md border border-subtle bg-surface-1 px-2 text-12 text-secondary outline-none",
          "hover:bg-layer-transparent-hover focus:border-accent-strong disabled:cursor-not-allowed",
          className
        )}
      >
        {types.map((type) => (
          <option key={type.id} value={type.id}>
            {type.name}
          </option>
        ))}
      </select>
    </div>
  );
});
