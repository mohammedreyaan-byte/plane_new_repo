/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";
import { workItemTypesService } from "@/services/work-item-types.service";

type Props = { workspaceSlug: string; projectId: string; issueId: string; typeId: string | null | undefined };

/** On an epic: the modules that deliver it and how far they are. Renders nothing for other types. */
export const EpicModulesPanel = observer(function EpicModulesPanel(props: Props) {
  const { workspaceSlug, projectId, issueId, typeId } = props;
  const { getTypeById } = useProjectWorkItemTypes(projectId);
  const isEpic = Boolean(getTypeById(typeId)?.is_epic);
  const { data } = useSWR(isEpic ? `EPIC_MODULES_${issueId}` : null, () =>
    workItemTypesService.getEpicModules(workspaceSlug, projectId, issueId)
  );
  if (!isEpic || !data || data.modules.length === 0) return null;
  return (
    <div className="mt-4 rounded-md border border-subtle p-3">
      <div className="flex items-center justify-between">
        <p className="text-13 font-medium text-primary">Modules delivering this epic</p>
        <p className="text-12 text-secondary">
          {data.completed_issues} of {data.total_issues} work items done ({data.progress}%)
        </p>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-layer-1">
        <div className="h-full bg-accent-primary" style={{ width: `${data.progress}%` }} />
      </div>
      <ul className="mt-3 space-y-1.5">
        {data.modules.map((module) => (
          <li key={module.id} className="flex items-center justify-between text-13">
            <a
              className="text-primary hover:underline"
              href={`/${workspaceSlug}/projects/${projectId}/modules/${module.id}`}
            >
              {module.name}
            </a>
            <span className="text-12 text-secondary">
              {module.completed_issues}/{module.total_issues} · {module.status}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
});
