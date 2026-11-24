/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import { Button } from "@plane/propel/button";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import type { TProjectWorkItemType, TWorkflow } from "@/services/work-item-types.service";
import { workItemTypesService } from "@/services/work-item-types.service";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { useParams } from "next/navigation";

type Props = {
  isOpen: boolean;
  source: TWorkflow;
  projectId: string;
  workflows: TWorkflow[];
  projectTypes: TProjectWorkItemType[];
  onClose: () => void;
  onCreated: (workflow: TWorkflow) => void;
};

const errorMessage = (error: unknown) =>
  (error as { error?: { message?: string } } | undefined)?.error?.message ?? "Could not clone this workflow.";

export function CloneWorkflowModal({ isOpen, source, projectId, workflows, projectTypes, onClose, onCreated }: Props) {
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString() ?? "";
  const availableTypes = useMemo(
    () => projectTypes.filter((row) => row.is_enabled).map((row) => row.issue_type),
    [projectTypes]
  );
  const [name, setName] = useState("");
  const [typeId, setTypeId] = useState("");
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    const defaultTarget = availableTypes.find((type) => type.id !== source.issue_type) ?? availableTypes[0];
    setName(`${source.name} copy`);
    setTypeId(defaultTarget?.id ?? "");
    setReplace(false);
  }, [isOpen, source, availableTypes]);

  const existingDefault = workflows.find((workflow) => workflow.issue_type === typeId && workflow.is_active && workflow.is_default);

  const submit = async () => {
    if (!slug || !typeId || !name.trim() || (existingDefault && !replace)) return;
    setBusy(true);
    try {
      const cloned = await workItemTypesService.cloneWorkflow(slug, projectId, source.id, {
        name: name.trim(),
        issue_type_id: typeId,
        replace,
      });
      onCreated(cloned);
      onClose();
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Could not clone workflow", message: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.CENTER} width={EModalWidth.XL}>
      <div className="space-y-4 p-5">
        <div>
          <h2 className="text-body-md-medium text-primary">Clone workflow</h2>
          <p className="mt-1 text-body-xs-regular text-secondary">
            Make an independent copy of {source.name} for another work item type.
          </p>
        </div>
        <label className="block space-y-1 text-13 text-secondary">
          <span>Workflow name</span>
          <input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            className="h-9 w-full rounded-md border border-subtle bg-surface-1 px-2 text-primary outline-none focus:border-accent-strong"
          />
        </label>
        <label className="block space-y-1 text-13 text-secondary">
          <span>Target work item type</span>
          <select
            value={typeId}
            onChange={(event) => {
              setTypeId(event.target.value);
              setReplace(false);
            }}
            className="h-9 w-full rounded-md border border-subtle bg-surface-1 px-2 text-primary"
          >
            <option value="" disabled>
              Select a type
            </option>
            {availableTypes.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}
              </option>
            ))}
          </select>
        </label>
        {existingDefault && (
          <div className="rounded-md border border-warning-subtle bg-warning-subtle p-3 text-13 text-secondary">
            <p className="font-medium text-primary">{existingDefault.name} is currently the default workflow.</p>
            <label className="mt-2 flex items-start gap-2">
              <input
                type="checkbox"
                checked={replace}
                onChange={(event) => setReplace(event.target.checked)}
                className="mt-0.5"
              />
              <span>Archive it and make this clone the default for the selected type.</span>
            </label>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={submit}
            loading={busy}
            disabled={!name.trim() || !typeId || Boolean(existingDefault && !replace)}
          >
            Clone workflow
          </Button>
        </div>
      </div>
    </ModalCore>
  );
}
