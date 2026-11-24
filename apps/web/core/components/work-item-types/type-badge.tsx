/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { cn } from "@plane/utils";
import { IssueTypeIcon, resolveIssueTypeIcon } from "@/components/issues/issue-type-icon";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";

// Fixed accents per built-in type so a Bug is recognisable at a glance.
const TYPE_STYLES: Record<string, string> = {
  bug: "bg-red-500/10 text-red-600",
  task: "bg-blue-500/10 text-blue-600",
  story: "bg-green-500/10 text-green-600",
  epic: "bg-purple-500/10 text-purple-600",
};

type Props = {
  projectId: string | null | undefined;
  typeId: string | null | undefined;
  className?: string;
};

/** Jira-style icon-only marker shown before the issue key (hover for the type name). Renders nothing while types are off. */
export const WorkItemTypeIcon = observer(function WorkItemTypeIcon({
  projectId,
  typeId,
  className,
}: Props) {
  const { getTypeById, isEnabled } = useProjectWorkItemTypes(projectId);
  const type = getTypeById(typeId);
  if (!isEnabled || !type) return null;
  const { icon, color } = resolveIssueTypeIcon(type);
  return (
    <span className={cn("inline-flex shrink-0", className)} title={type.name}>
      <IssueTypeIcon icon={icon} color={color} size="sm" />
    </span>
  );
});

/** Small pill with the work item type name. Renders nothing while types are off in the project. */
export const WorkItemTypeBadge = observer(function WorkItemTypeBadge({ projectId, typeId, className }: Props) {
  const { getTypeById, isEnabled } = useProjectWorkItemTypes(projectId);
  const type = getTypeById(typeId);
  if (!isEnabled || !type) return null;
  const { icon, color } = resolveIssueTypeIcon(type);
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 rounded-sm px-1.5 text-11 font-medium",
        TYPE_STYLES[type.key ?? ""] ?? "bg-layer-1 text-secondary",
        className
      )}
      title={type.description || type.name}
    >
      <IssueTypeIcon icon={icon} color={color} size="xs" />
      {type.name}
    </span>
  );
});
