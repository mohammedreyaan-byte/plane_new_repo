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
import { cn } from "@plane/utils";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";
import { workItemTypesService } from "@/services/work-item-types.service";
import type { TWorkflowErrorBody, TWorkflowTransition } from "@/services/work-item-types.service";

const ROLES = ["admin", "member", "developer", "qa"] as const;
const REQUIRED_FIELDS = ["assignee", "estimate", "priority", "description", "due_date"] as const;

type Props = { workspaceSlug: string; projectId: string; canManage: boolean };

const errorMessage = (e: unknown, fallback: string) =>
  (e as TWorkflowErrorBody | undefined)?.error?.message ?? fallback;

const toggle = (list: string[], value: string) =>
  list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

function Chip(props: { active: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      disabled={props.disabled}
      onClick={props.onClick}
      className={cn(
        "rounded-sm border px-1.5 py-0.5 text-11 transition-colors disabled:cursor-not-allowed",
        props.active ? "border-accent-strong bg-accent-primary/10 text-primary" : "border-subtle text-tertiary"
      )}
    >
      {props.children}
    </button>
  );
}

/** Project settings: view and edit who can make each state change, per work item type. */
export const WorkflowsSettings = observer(function WorkflowsSettings({ workspaceSlug, projectId, canManage }: Props) {
  const { isEnabled } = useProjectWorkItemTypes(projectId);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const { data: workflows } = useSWR(isEnabled ? `WORKFLOWS_${projectId}` : null, () =>
    workItemTypesService.listWorkflows(workspaceSlug, projectId)
  );
  const workflowId = selected ?? workflows?.[0]?.id ?? null;
  const { data: workflow, mutate } = useSWR(workflowId ? `WORKFLOW_${workflowId}` : null, () =>
    workItemTypesService.getWorkflow(workspaceSlug, projectId, workflowId!)
  );
  const { data: health, mutate: mutateHealth } = useSWR(isEnabled ? `WORKFLOW_HEALTH_${projectId}` : null, () =>
    workItemTypesService.getWorkflowHealth(workspaceSlug, projectId)
  );

  if (!isEnabled) {
    return (
      <p className="rounded-md border border-subtle p-4 text-13 text-secondary">
        Turn on work item types for this project first (Settings, Work item types). Workflows apply once types are on.
      </p>
    );
  }

  const stateName = (stateId: string) => workflow?.states?.find((s) => s.state_id === stateId)?.name ?? stateId;

  const run = async (action: () => Promise<unknown>, success?: string) => {
    setBusy(true);
    try {
      await action();
      await Promise.all([mutate(), mutateHealth()]);
      if (success) setToast({ type: TOAST_TYPE.SUCCESS, title: "Saved", message: success });
    } catch (e) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Error", message: errorMessage(e, "Something went wrong.") });
    } finally {
      setBusy(false);
    }
  };

  const patch = (t: TWorkflowTransition, data: Partial<TWorkflowTransition>) =>
    run(() => workItemTypesService.updateTransition(workspaceSlug, projectId, workflow!.id, t.id, data));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {workflows?.map((w) => (
          <Chip key={w.id} active={w.id === workflowId} onClick={() => setSelected(w.id)}>
            {w.issue_type_key ? w.name : `${w.name} (project default)`}
          </Chip>
        ))}
      </div>

      {health && health.issues.length > 0 && (
        <div className="rounded-md border border-warning-subtle bg-warning-subtle p-3 text-13 text-secondary">
          <p className="font-medium text-primary">Workflow problems</p>
          <ul className="mt-1 list-disc pl-5">
            {health.issues.map((issue) => (
              <li key={`${issue.code}-${issue.workflow_id}-${String(issue.state_id ?? issue.message ?? "")}`}>
                {issue.message ?? issue.code}
              </li>
            ))}
          </ul>
        </div>
      )}

      {workflow && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-12 text-secondary">
            <span>States:</span>
            {workflow.states?.map((s) => (
              <span key={s.id} className="rounded-sm bg-layer-1 px-1.5 py-0.5">
                {s.name}
                {s.is_initial ? " (start)" : ""}
                {s.is_final ? " (end)" : ""}
              </span>
            ))}
          </div>

          <div className="overflow-x-auto rounded-md border border-subtle">
            <table className="w-full text-left text-13">
              <thead className="bg-layer-1 text-12 text-secondary">
                <tr>
                  <th className="px-3 py-2">Move</th>
                  <th className="px-3 py-2">Who can do it</th>
                  <th className="px-3 py-2">Needs</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-subtle">
                {workflow.transitions?.map((t) => (
                  <tr key={t.id}>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {stateName(t.from_state_id)} → {stateName(t.to_state_id)}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {ROLES.map((role) => (
                          <Chip
                            key={role}
                            disabled={!canManage || busy}
                            active={t.allowed_roles.length === 0 || t.allowed_roles.includes(role)}
                            onClick={() => {
                              // An empty list means "any contributor"; make it explicit before removing one role.
                              const base = t.allowed_roles.length === 0 ? [...ROLES] : t.allowed_roles;
                              const next = toggle(base, role);
                              if (next.length === 0) return;
                              void patch(t, { allowed_roles: next });
                            }}
                          >
                            {role}
                          </Chip>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        <Chip
                          disabled={!canManage || busy}
                          active={t.requires_comment}
                          onClick={() => void patch(t, { requires_comment: !t.requires_comment })}
                        >
                          comment
                        </Chip>
                        {REQUIRED_FIELDS.map((field) => (
                          <Chip
                            key={field}
                            disabled={!canManage || busy}
                            active={t.required_fields.includes(field)}
                            onClick={() => void patch(t, { required_fields: toggle(t.required_fields, field) })}
                          >
                            {field.replace("_", " ")}
                          </Chip>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right">
                      {canManage && (
                        <button
                          type="button"
                          disabled={busy}
                          className="text-12 text-danger-primary"
                          onClick={() =>
                            run(() =>
                              workItemTypesService.deleteTransition(workspaceSlug, projectId, workflow.id, t.id)
                            )
                          }
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {canManage && (
            <div className="flex flex-wrap items-center gap-2">
              {[
                { value: from, set: setFrom, label: "From" },
                { value: to, set: setTo, label: "To" },
              ].map((field) => (
                <select
                  key={field.label}
                  value={field.value}
                  onChange={(e) => field.set(e.target.value)}
                  className="h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13"
                >
                  <option value="">{field.label} state</option>
                  {workflow.states?.map((s) => (
                    <option key={s.id} value={s.state_id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              ))}
              <Button
                variant="secondary"
                size="sm"
                disabled={busy || !from || !to || from === to}
                onClick={() =>
                  run(async () => {
                    await workItemTypesService.createTransition(workspaceSlug, projectId, workflow.id, {
                      from_state_id: from,
                      to_state_id: to,
                      allowed_roles: ["admin", "member"],
                    });
                    setFrom("");
                    setTo("");
                  }, "Move added.")
                }
              >
                Add move
              </Button>
              {workflow.issue_type_key && (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    run(
                      () => workItemTypesService.resetWorkflow(workspaceSlug, projectId, workflow.id),
                      "Workflow reset."
                    )
                  }
                >
                  Reset to built-in
                </Button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
});
