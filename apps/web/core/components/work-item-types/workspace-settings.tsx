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
import { IssueTypeIcon, resolveIssueTypeIcon } from "@/components/issues/issue-type-icon";
import { workItemTypesService } from "@/services/work-item-types.service";
import type { TWorkItemType, TWorkflowErrorBody } from "@/services/work-item-types.service";
import { DeleteTypeModal } from "./delete-type-modal";
import { TYPE_ICON_CHOICES, TypeIconPicker } from "./type-icon-picker";

const errorMessage = (error: unknown) =>
  (error as TWorkflowErrorBody | undefined)?.error?.message ?? "The work item type could not be updated.";

type IconDraft = { icon: string; color: string };
type DeleteTarget = { type: TWorkItemType; error?: unknown };

/** Workspace settings: manage the catalogue of work item types. */
export const WorkspaceWorkItemTypesSettings = observer(function WorkspaceWorkItemTypesSettings(props: {
  workspaceSlug: string;
  canManage: boolean;
}) {
  const { workspaceSlug, canManage } = props;
  const { data: types, mutate } = useSWR<TWorkItemType[]>(`WORKSPACE_WORK_ITEM_TYPES_${workspaceSlug}`, () =>
    workItemTypesService.listWorkspaceTypes(workspaceSlug)
  );
  const [newName, setNewName] = useState("");
  const [newIcon, setNewIcon] = useState<IconDraft>({
    icon: TYPE_ICON_CHOICES[0].key,
    color: TYPE_ICON_CHOICES[0].color,
  });
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [icons, setIcons] = useState<Record<string, IconDraft>>({});
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      await mutate();
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Error", message: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  const create = () => {
    const name = newName.trim();
    if (!name) return;
    void run(async () => {
      await workItemTypesService.createWorkspaceType(workspaceSlug, {
        name,
        logo_props: { icon: newIcon.icon, color: newIcon.color },
      });
      setNewName("");
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Type created", message: `${name} is available to add to projects.` });
    });
  };

  const iconFor = (type: TWorkItemType): IconDraft => {
    const resolved = resolveIssueTypeIcon(type);
    return icons[type.id] ?? { icon: resolved.icon, color: resolved.color ?? TYPE_ICON_CHOICES[0].color };
  };

  const saveRow = (type: TWorkItemType) => {
    const name = (editing[type.id] ?? type.name).trim();
    const icon = iconFor(type);
    void run(async () => {
      await workItemTypesService.updateWorkspaceType(workspaceSlug, type.id, {
        name,
        logo_props: { icon: icon.icon, color: icon.color },
      });
      setIcons((current) => {
        const next = { ...current };
        delete next[type.id];
        return next;
      });
    });
  };

  const confirmDelete = async (force: boolean) => {
    if (!deleting) return;
    setBusy(true);
    try {
      await workItemTypesService.deleteWorkspaceType(workspaceSlug, deleting.type.id, force);
      await mutate();
      setDeleting(null);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Type deleted",
        message: `${deleting.type.name} was removed from the workspace.`,
      });
    } catch (error) {
      const code = (error as TWorkflowErrorBody | undefined)?.error?.code;
      if (code === "type_in_use") {
        setDeleting({ ...deleting, error });
      } else {
        setToast({ type: TOAST_TYPE.ERROR, title: "Error", message: errorMessage(error) });
        setDeleting(null);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <p className="max-w-3xl text-13 text-secondary">
        Manage the workspace catalogue. Project settings control which types are enabled and the default for each project.
      </p>
      {!types ? (
        <div className="rounded-md border border-subtle px-4 py-8 text-center text-13 text-secondary">Loading work item types…</div>
      ) : (
        <div className="divide-y divide-subtle rounded-md border border-subtle">
          {types.map((type) => {
            const icon = iconFor(type);
            const editedName = editing[type.id] ?? type.name;
            const changed = editedName.trim() !== type.name || Boolean(icons[type.id]);
            return (
              <div key={type.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <IssueTypeIcon icon={icon.icon} color={icon.color} size="md" />
                <div className="min-w-0 flex-1">
                  {canManage ? (
                    <input
                      aria-label={`Name for ${type.name}`}
                      value={editedName}
                      onChange={(event) => setEditing((current) => ({ ...current, [type.id]: event.target.value }))}
                      className="h-8 w-full max-w-72 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-primary outline-none focus:border-accent-strong"
                    />
                  ) : (
                    <p className="text-13 font-medium text-primary">{type.name}</p>
                  )}
                  <p className="mt-1 text-12 text-tertiary">{type.key} · used in {type.projects_count ?? 0} projects{type.is_epic ? " · Epic" : ""}</p>
                </div>
                {type.is_default && <span className="rounded-sm bg-layer-1 px-2 py-1 text-11 text-secondary">Workspace default</span>}
                {canManage && (
                  <div className="flex flex-wrap items-center gap-2">
                    <TypeIconPicker
                      value={icon.icon}
                      color={icon.color}
                      label={`Icon for ${type.name}`}
                      onChange={(nextIcon, nextColor) =>
                        setIcons((current) => ({ ...current, [type.id]: { icon: nextIcon, color: nextColor } }))
                      }
                    />
                    {changed && (
                      <Button variant="secondary" size="sm" disabled={busy || !editedName.trim()} onClick={() => saveRow(type)}>
                        Save
                      </Button>
                    )}
                    {!type.is_default && (
                      <Button variant="secondary" size="sm" disabled={busy || !type.is_active} onClick={() => void run(() => workItemTypesService.updateWorkspaceType(workspaceSlug, type.id, { is_default: true }))}>Make default</Button>
                    )}
                    {!type.is_default && (
                      <Button variant="secondary" size="sm" disabled={busy} onClick={() => void run(() => workItemTypesService.updateWorkspaceType(workspaceSlug, type.id, { is_active: !type.is_active }))}>{type.is_active ? "Deactivate" : "Activate"}</Button>
                    )}
                    {!type.is_default && (
                      <Button variant="error-outline" size="sm" disabled={busy} onClick={() => setDeleting({ type })}>
                        Delete
                      </Button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {canManage && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-subtle p-4">
          <input
            aria-label="New work item type name"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") create(); }}
            placeholder="Create a type, for example Spike"
            className="h-8 min-w-0 flex-1 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-primary outline-none focus:border-accent-strong"
          />
          <TypeIconPicker
            value={newIcon.icon}
            color={newIcon.color}
            label="New type icon"
            onChange={(icon, color) => setNewIcon({ icon, color })}
          />
          <Button variant="primary" size="sm" disabled={busy || !newName.trim()} onClick={create}>Create type</Button>
        </div>
      )}
      <DeleteTypeModal
        key={deleting?.type.id ?? "closed"}
        type={deleting?.type ?? null}
        error={deleting?.error}
        busy={busy}
        onClose={() => setDeleting(null)}
        onConfirm={(force) => void confirmDelete(force)}
      />
    </div>
  );
});
