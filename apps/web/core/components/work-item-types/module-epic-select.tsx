/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
import { useParams } from "next/navigation";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";
import { workItemTypesService } from "@/services/work-item-types.service";

type Props = {
  projectId: string;
  value: string | null | undefined;
  onChange: (epicId: string | null) => void;
  disabled?: boolean;
};

/** Choose the epic a module delivers. Hidden while the project has no epic type. */
export const ModuleEpicSelect = observer(function ModuleEpicSelect({ projectId, value, onChange, disabled }: Props) {
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString();
  const { types } = useProjectWorkItemTypes(projectId);
  const epicType = types.find((type) => type.is_epic);
  const { data: epics } = useSWR(
    slug && epicType ? `PROJECT_EPICS_${projectId}` : null,
    slug && epicType ? () => workItemTypesService.listProjectEpics(slug, projectId, epicType.id) : null,
    { revalidateOnFocus: false }
  );
  if (!epicType) return null;
  return (
    <select
      aria-label="Epic"
      value={value ?? ""}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value || null)}
      className="h-7 max-w-48 rounded-md border border-subtle bg-surface-1 px-2 text-12 text-secondary outline-none focus:border-accent-strong"
    >
      <option value="">No epic</option>
      {(epics ?? []).map((epic) => (
        <option key={epic.id} value={epic.id}>
          {epic.name}
        </option>
      ))}
    </select>
  );
});
