/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";
import { workItemTypesService } from "@/services/work-item-types.service";
import type { TWorkItemType, TWorkflowErrorBody } from "@/services/work-item-types.service";
import { WorkItemTypeBadge } from "./type-badge";

type Props = { workspaceSlug: string; projectId: string; canManage: boolean };

const errorMessage = (e: unknown, fallback: string) =>
  (e as TWorkflowErrorBody | undefined)?.error?.message ?? fallback;

/** Project settings: switch work item types on, choose which ones the project uses and its default. */
export const WorkItemTypesSettings = observer(function WorkItemTypesSettings(props: Props) {
  const { workspaceSlug, projectId, canManage } = props;
  const { rows, isEnabled, mutate, isLoading } = useProjectWorkItemTypes(projectId);
  const { data: workspaceTypes, mutate: mutateWorkspace } = useSWR(`WORKSPACE_WORK_ITEM_TYPES_${workspaceSlug}`, () =>
    workItemTypesService.listWorkspaceTypes(workspaceSlug)
  );
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (action: () => Promise<unknown>, success?: string) => {
    setBusy(true);
    try {
      await action();
      await Promise.all([mutate(), mutateWorkspace()]);
      if (success) setToast({ type: TOAST_TYPE.SUCCESS, title: "Done", message: success });
    } catch (e) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Error", message: errorMessage(e, "Something went wrong.") });
    } finally {
      setBusy(false);
    }
  };

  const rowByType = new Map(rows.map((row) => [row.issue_type.id, row]));
  const available: TWorkItemType[] = (workspaceTypes ?? []).filter((t) => !rowByType.get(t.id)?.is_enabled);

  const addType = () =>
    run(async () => {
      const created = await workItemTypesService.createWorkspaceType(workspaceSlug, { name: newName.trim() });
      await workItemTypesService.addProjectType(workspaceSlug, projectId, created.id);
      setNewName("");
    }, "Type created and added to this project.");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between rounded-md border border-subtle p-4">
        <div>
          <p className="text-14 font-medium text-primary">
            Work item types and workflows are {isEnabled ? "on" : "off"} for this project
          </p>
          <p className="mt-1 text-13 text-secondary">
            {isEnabled
              ? "Every work item has a type, and state changes follow the type's workflow."
              : "Turning this on gives work items a type (Bug, Task, Story, Epic) and enforces workflows."}
          </p>
        </div>
        {canManage && (
          <Button
            variant={isEnabled ? "secondary" : "primary"}
            size="sm"
            loading={busy}
            onClick={() =>
              run(
                () => workItemTypesService.enableProjectTypes(workspaceSlug, projectId, !isEnabled),
                isEnabled ? "Work item types turned off." : "Work item types turned on."
              )
            }
          >
            {isEnabled ? "Turn off" : "Turn on"}
          </Button>
        )}
      </div>

      {isLoading && <p className="text-13 text-secondary">Loading…</p>}

      {rows.length > 0 && (
        <div className="divide-y divide-subtle rounded-md border border-subtle">
          {rows.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <WorkItemTypeBadge projectId={projectId} typeId={row.issue_type.id} />
                {!row.is_enabled && <span className="text-12 text-tertiary">Not used in this project</span>}
                {row.is_default && row.is_enabled && (
                  <span className="rounded-sm bg-layer-1 px-1.5 text-11 text-secondary">Default</span>
                )}
                <span className="truncate text-13 text-secondary">{row.issue_type.description}</span>
              </div>
              {canManage && isEnabled && (
                <div className="flex shrink-0 items-center gap-2">
                  {row.is_enabled && !row.is_default && (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        run(
                          () =>
                            workItemTypesService.updateProjectType(workspaceSlug, projectId, row.id, {
                              is_default: true,
                            }),
                          `${row.issue_type.name} is now the default.`
                        )
                      }
                    >
                      Make default
                    </Button>
                  )}
                  {row.is_enabled && !row.is_default && (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        run(() => workItemTypesService.disableProjectType(workspaceSlug, projectId, row.id))
                      }
                    >
                      Stop using
                    </Button>
                  )}
                  {!row.is_enabled && (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        run(() =>
                          workItemTypesService.updateProjectType(workspaceSlug, projectId, row.id, { is_enabled: true })
                        )
                      }
                    >
                      Use
                    </Button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {canManage && isEnabled && (
        <div className="space-y-3 rounded-md border border-subtle p-4">
          <p className="text-14 font-medium text-primary">Add a type</p>
          {available.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {available.map((t) => (
                <Button
                  key={t.id}
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={() => run(() => workItemTypesService.addProjectType(workspaceSlug, projectId, t.id))}
                >
                  Use {t.name}
                </Button>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="New type name, for example Spike"
              className="h-8 flex-1 rounded-md border border-subtle bg-surface-1 px-2 text-13 outline-none focus:border-accent-strong"
            />
            <Button variant="primary" size="sm" disabled={busy || !newName.trim()} onClick={addType}>
              Create
            </Button>
          </div>
          <p className="text-12 text-tertiary">
            A new type has no workflow of its own and uses the project default until you add one.
          </p>
        </div>
      )}
    </div>
  );
});
