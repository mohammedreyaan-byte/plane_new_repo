/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pencil, Play, Plus, RefreshCw, Trash2, Zap } from "lucide-react";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { AlertModalCore, EModalWidth, ModalCore, ToggleSwitch } from "@plane/ui";
// services
import {
  gmcFeaturesService,
  type AutomationAction,
  type AutomationCondition,
  type AutomationOptions,
  type AutomationRule,
  type AutomationRun,
} from "@/services/gmc-features.service";

type Props = { workspaceSlug: string; projectId: string };

type RuleDraft = {
  id?: string;
  name: string;
  description: string;
  trigger: string;
  conditions: AutomationCondition[];
  actions: AutomationAction[];
  is_active: boolean;
};

const TRIGGERS = [
  { value: "state_changed", label: "State changes" },
  { value: "created", label: "Work item created" },
  { value: "priority_changed", label: "Priority changes" },
  { value: "assigned", label: "Assignee changes" },
  { value: "due_date", label: "Due date reached" },
];

const CONDITION_FIELDS = ["state", "priority", "assignee", "label", "type"];
const OPERATORS = ["is", "is not", "contains"];
const ACTION_TYPES = ["change_state", "assign_user", "add_label", "add_comment", "send_notification", "set_priority"];

const EMPTY_OPTIONS: AutomationOptions = {
  work_items: [],
  states: [],
  labels: [],
  members: [],
  priorities: [],
  types: [],
};

const emptyDraft = (): RuleDraft => ({
  name: "",
  description: "",
  trigger: "state_changed",
  conditions: [{ field: "state", operator: "is", value: "" }],
  actions: [{ type: "add_comment", value: "" }],
  is_active: true,
});

const errorMessage = (error: unknown) => {
  const detail = error as { error?: string; message?: string } | undefined;
  return detail?.error ?? detail?.message ?? "The request could not be completed.";
};

const optionsForField = (field: string, options: AutomationOptions): string[] => {
  if (field === "state") return options.states.map((item) => item.name);
  if (field === "priority") return options.priorities.map((item) => item.value);
  if (field === "assignee") return options.members.map((item) => item.display_name);
  if (field === "label") return options.labels.map((item) => item.name);
  if (field === "type") return options.types.map((item) => item.name);
  return [];
};

const optionsForAction = (type: string, options: AutomationOptions): string[] => {
  if (type === "change_state") return options.states.map((item) => item.name);
  if (type === "assign_user" || type === "send_notification") return options.members.map((item) => item.display_name);
  if (type === "add_label") return options.labels.map((item) => item.name);
  if (type === "set_priority") return options.priorities.map((item) => item.value);
  return [];
};

const summary = (rule: AutomationRule) => {
  const trigger = TRIGGERS.find((item) => item.value === rule.trigger)?.label ?? rule.trigger;
  const conditions = rule.conditions.map((c) => `${c.field} ${c.operator} ${c.value}`).join(" AND ") || "no conditions";
  const actions = rule.actions.map((a) => `${a.type.replace(/_/g, " ")} → ${a.value}`).join(", ") || "no actions";
  return { trigger, conditions, actions };
};

/** Rule-based automation builder shown on Project settings > Automations. */
export function RuleBasedAutomations({ workspaceSlug, projectId }: Props) {
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [options, setOptions] = useState<AutomationOptions>(EMPTY_OPTIONS);
  const [isLoading, setIsLoading] = useState(true);
  const [testIssueId, setTestIssueId] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState<RuleDraft>(emptyDraft);
  const [deleteTarget, setDeleteTarget] = useState<AutomationRule | null>(null);

  const load = useCallback(
    async (showErrors = true) => {
      try {
        const [ruleRecords, runRecords, availableOptions] = await Promise.all([
          gmcFeaturesService.getAutomationRules(workspaceSlug, projectId),
          gmcFeaturesService.getAutomationRuns(workspaceSlug, projectId),
          gmcFeaturesService.getAutomationOptions(workspaceSlug, projectId),
        ]);
        setRules(ruleRecords);
        setRuns(runRecords);
        setOptions(availableOptions);
        setTestIssueId((current) => current || availableOptions.work_items[0]?.id || "");
      } catch (error) {
        if (showErrors)
          setToast({ type: TOAST_TYPE.ERROR, title: "Unable to load automations", message: errorMessage(error) });
      } finally {
        setIsLoading(false);
      }
    },
    [projectId, workspaceSlug]
  );

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(false), 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const openNew = () => {
    setDraft(emptyDraft());
    setModalOpen(true);
  };

  const openEdit = (rule: AutomationRule) => {
    setDraft({
      id: rule.id,
      name: rule.name,
      description: rule.description,
      trigger: rule.trigger,
      conditions: rule.conditions.map((condition) => ({ ...condition })),
      actions: rule.actions.map((action) => ({ ...action })),
      is_active: rule.is_active,
    });
    setModalOpen(true);
  };

  const save = async () => {
    const name = draft.name.trim();
    if (!name) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Name required", message: "Enter a name for this automation rule." });
      return;
    }
    const conditions = draft.conditions.filter((condition) => condition.value.trim());
    const actions = draft.actions.filter((action) => action.value.trim());
    try {
      if (draft.id) {
        await gmcFeaturesService.updateAutomationRule(workspaceSlug, projectId, draft.id, {
          name,
          description: draft.description.trim(),
          trigger: draft.trigger,
          conditions,
          actions,
          is_active: draft.is_active,
        });
      } else {
        await gmcFeaturesService.createAutomationRule(workspaceSlug, projectId, {
          name,
          description: draft.description.trim(),
          trigger: draft.trigger,
          conditions,
          actions,
          is_active: draft.is_active,
        });
      }
      await load(false);
      setModalOpen(false);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Done",
        message: draft.id ? "Automation rule updated." : "Automation rule created.",
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to save rule", message: errorMessage(error) });
    }
  };

  const toggle = async (rule: AutomationRule) => {
    try {
      await gmcFeaturesService.updateAutomationRule(workspaceSlug, projectId, rule.id, { is_active: !rule.is_active });
      await load(false);
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to update rule", message: errorMessage(error) });
    }
  };

  const test = async (rule: AutomationRule) => {
    if (!testIssueId) {
      setToast({ type: TOAST_TYPE.ERROR, title: "No work item", message: "Create a work item before testing a rule." });
      return;
    }
    try {
      await gmcFeaturesService.testAutomationRule(workspaceSlug, projectId, rule.id, testIssueId);
      await load(false);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Test run queued",
        message: "The run is a dry run and will not change the work item.",
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to test rule", message: errorMessage(error) });
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    try {
      await gmcFeaturesService.deleteAutomationRule(workspaceSlug, projectId, deleteTarget.id);
      await load(false);
      setDeleteTarget(null);
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Deleted", message: "Automation rule removed." });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to delete rule", message: errorMessage(error) });
    }
  };

  const activeCount = useMemo(() => rules.filter((rule) => rule.is_active).length, [rules]);

  return (
    <section className="mt-8 space-y-6" aria-label="Rule-based automations">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-sm bg-layer-2">
            <Zap className="size-4 text-accent-primary" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-16 font-medium text-primary">Rule-based automations</h3>
            <p className="text-13 text-secondary">
              {rules.length} rules · {activeCount} active. Trigger → conditions → actions.
            </p>
          </div>
        </div>
        <Button variant="primary" size="sm" onClick={openNew} aria-label="New automation rule">
          <Plus className="size-4" aria-hidden="true" />
          New rule
        </Button>
      </div>

      {rules.length === 0 ? (
        <div className="rounded-md border border-subtle p-8 text-center">
          <p className="text-14 font-medium text-primary">
            {isLoading ? "Loading rules..." : "No automation rules yet"}
          </p>
          <p className="mt-1 text-13 text-secondary">Create a rule to automate work item updates.</p>
        </div>
      ) : (
        <div className="divide-y divide-subtle rounded-md border border-subtle">
          {rules.map((rule) => {
            const info = summary(rule);
            return (
              <div
                key={rule.id}
                className="flex flex-wrap items-start justify-between gap-4 px-4 py-4"
                data-testid="automation-rule"
              >
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-14 font-medium text-primary">{rule.name}</span>
                    <span className="rounded-sm bg-layer-1 px-1.5 py-0.5 text-11 text-secondary">
                      {rule.is_active ? "Active" : "Inactive"}
                    </span>
                  </div>
                  {rule.description && <p className="text-13 text-secondary">{rule.description}</p>}
                  <div className="flex flex-wrap gap-2 text-12">
                    <span className="rounded-sm bg-layer-1 px-2 py-1 text-accent-primary">When {info.trigger}</span>
                    <span className="rounded-sm bg-layer-2 px-2 py-1 text-secondary">If {info.conditions}</span>
                    <span className="rounded-sm bg-layer-2 px-2 py-1 text-secondary">Then {info.actions}</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <ToggleSwitch
                    value={rule.is_active}
                    onChange={() => void toggle(rule)}
                    size="sm"
                    label={`Toggle ${rule.name}`}
                  />
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => void test(rule)}
                    aria-label={`Test ${rule.name}`}
                  >
                    <Play className="size-4" aria-hidden="true" /> Test
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => openEdit(rule)} aria-label={`Edit ${rule.name}`}>
                    <Pencil className="size-4" aria-hidden="true" /> Edit
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setDeleteTarget(rule)}
                    aria-label={`Delete ${rule.name}`}
                  >
                    <Trash2 className="size-4" aria-hidden="true" /> Delete
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="rounded-md border border-subtle">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle px-4 py-3">
          <div>
            <h3 className="text-14 font-medium text-primary">Run history</h3>
            <p className="text-12 text-secondary">Runs are recorded by the backend; test runs are dry runs.</p>
          </div>
          <div className="flex items-center gap-2">
            <select
              aria-label="Work item for rule test"
              className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-12 text-primary"
              value={testIssueId}
              onChange={(event) => setTestIssueId(event.target.value)}
            >
              {options.work_items.length === 0 && <option value="">No work items</option>}
              {options.work_items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.identifier} · {item.name}
                </option>
              ))}
            </select>
            <Button variant="secondary" size="sm" onClick={() => void load()} aria-label="Refresh automation runs">
              <RefreshCw className="size-4" aria-hidden="true" /> Refresh
            </Button>
          </div>
        </div>
        {runs.length === 0 ? (
          <p className="px-4 py-6 text-center text-13 text-secondary">
            No runs yet. Use Test on a rule to queue a dry run.
          </p>
        ) : (
          <table className="w-full text-left text-12">
            <thead className="bg-surface-2 text-secondary">
              <tr>
                <th className="px-4 py-2 font-medium">Triggered</th>
                <th className="px-4 py-2 font-medium">Rule</th>
                <th className="px-4 py-2 font-medium">Work item</th>
                <th className="px-4 py-2 font-medium">Result</th>
                <th className="px-4 py-2 font-medium">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-subtle">
              {runs.map((run) => (
                <tr key={run.id} data-testid="automation-run">
                  <td className="px-4 py-2 text-secondary">{new Date(run.created_at).toLocaleString()}</td>
                  <td className="px-4 py-2 text-primary">{run.rule_name}</td>
                  <td className="px-4 py-2 text-accent-primary">{run.work_item_identifier || "—"}</td>
                  <td className="px-4 py-2">
                    <span className="rounded-sm bg-layer-1 px-1.5 text-secondary">{run.status}</span>
                  </td>
                  <td className="px-4 py-2 text-secondary">{run.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <ModalCore
        isOpen={modalOpen}
        handleClose={() => setModalOpen(false)}
        width={EModalWidth.XXXL}
        className="max-h-[85vh] overflow-y-auto"
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="border-b border-subtle px-6 py-5">
            <h3 className="text-16 font-medium text-primary">
              {draft.id ? "Edit automation rule" : "New automation rule"}
            </h3>
            <p className="mt-1 text-13 text-secondary">Define what happens when a work item event matches.</p>
          </div>
          <div className="space-y-5 px-6 py-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="automation-name" className="mb-1 block text-12 font-medium text-primary">
                  Name
                </label>
                <input
                  id="automation-name"
                  aria-label="Rule name"
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder="Enter a rule name"
                  className="w-full rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13 focus:border-accent-strong focus:outline-none"
                />
              </div>
              <div>
                <label htmlFor="automation-trigger" className="mb-1 block text-12 font-medium text-primary">
                  Trigger
                </label>
                <select
                  id="automation-trigger"
                  aria-label="Trigger"
                  value={draft.trigger}
                  onChange={(e) => setDraft({ ...draft, trigger: e.target.value })}
                  className="w-full rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13 focus:border-accent-strong focus:outline-none"
                >
                  {TRIGGERS.map((trigger) => (
                    <option key={trigger.value} value={trigger.value}>
                      {trigger.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label htmlFor="automation-description" className="mb-1 block text-12 font-medium text-primary">
                Description
              </label>
              <textarea
                id="automation-description"
                aria-label="Rule description"
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                rows={2}
                className="w-full rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13 focus:border-accent-strong focus:outline-none"
              />
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-13 font-medium text-primary">Conditions</p>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  aria-label="Add condition"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      conditions: [...draft.conditions, { field: "state", operator: "is", value: "" }],
                    })
                  }
                >
                  <Plus className="size-4" aria-hidden="true" /> Add condition
                </Button>
              </div>
              {draft.conditions.map((condition, index) => {
                const choices = optionsForField(condition.field, options);
                return (
                  <div key={JSON.stringify(condition)} className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
                    <select
                      aria-label={`Condition ${index + 1} field`}
                      value={condition.field}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          conditions: draft.conditions.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, field: e.target.value, value: "" } : item
                          ),
                        })
                      }
                      className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13"
                    >
                      {CONDITION_FIELDS.map((field) => (
                        <option key={field} value={field}>
                          {field}
                        </option>
                      ))}
                    </select>
                    <select
                      aria-label={`Condition ${index + 1} operator`}
                      value={condition.operator}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          conditions: draft.conditions.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, operator: e.target.value } : item
                          ),
                        })
                      }
                      className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13"
                    >
                      {OPERATORS.map((operator) => (
                        <option key={operator} value={operator}>
                          {operator}
                        </option>
                      ))}
                    </select>
                    {choices.length > 0 ? (
                      <select
                        aria-label={`Condition ${index + 1} value`}
                        value={condition.value}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            conditions: draft.conditions.map((item, itemIndex) =>
                              itemIndex === index ? { ...item, value: e.target.value } : item
                            ),
                          })
                        }
                        className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13"
                      >
                        <option value="">Select a value</option>
                        {choices.map((choice) => (
                          <option key={choice} value={choice}>
                            {choice}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        aria-label={`Condition ${index + 1} value`}
                        value={condition.value}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            conditions: draft.conditions.map((item, itemIndex) =>
                              itemIndex === index ? { ...item, value: e.target.value } : item
                            ),
                          })
                        }
                        className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13"
                      />
                    )}
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      aria-label={`Remove condition ${index + 1}`}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          conditions: draft.conditions.filter((_, itemIndex) => itemIndex !== index),
                        })
                      }
                    >
                      <Trash2 className="size-4" aria-hidden="true" />
                    </Button>
                  </div>
                );
              })}
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-13 font-medium text-primary">Actions</p>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  aria-label="Add action"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      actions: [...draft.actions, { type: "add_comment", value: "" }],
                    })
                  }
                >
                  <Plus className="size-4" aria-hidden="true" /> Add action
                </Button>
              </div>
              {draft.actions.map((action, index) => {
                const choices = optionsForAction(action.type, options);
                return (
                  <div key={JSON.stringify(action)} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                    <select
                      aria-label={`Action ${index + 1} type`}
                      value={action.type}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          actions: draft.actions.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, type: e.target.value, value: "" } : item
                          ),
                        })
                      }
                      className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13"
                    >
                      {ACTION_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {type.replace(/_/g, " ")}
                        </option>
                      ))}
                    </select>
                    {choices.length > 0 ? (
                      <select
                        aria-label={`Action ${index + 1} value`}
                        value={action.value}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            actions: draft.actions.map((item, itemIndex) =>
                              itemIndex === index ? { ...item, value: e.target.value } : item
                            ),
                          })
                        }
                        className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13"
                      >
                        <option value="">Select a value</option>
                        {choices.map((choice) => (
                          <option key={choice} value={choice}>
                            {choice}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        aria-label={`Action ${index + 1} value`}
                        value={action.value}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            actions: draft.actions.map((item, itemIndex) =>
                              itemIndex === index ? { ...item, value: e.target.value } : item
                            ),
                          })
                        }
                        className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13"
                      />
                    )}
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      aria-label={`Remove action ${index + 1}`}
                      onClick={() =>
                        setDraft({ ...draft, actions: draft.actions.filter((_, itemIndex) => itemIndex !== index) })
                      }
                    >
                      <Trash2 className="size-4" aria-hidden="true" />
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>
          <div className="flex justify-end gap-2 border-t border-subtle px-6 py-4">
            <Button type="button" variant="secondary" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" aria-label="Save automation rule">
              Save rule
            </Button>
          </div>
        </form>
      </ModalCore>

      <AlertModalCore
        isOpen={deleteTarget !== null}
        handleClose={() => setDeleteTarget(null)}
        handleSubmit={() => void remove()}
        isSubmitting={false}
        title="Delete automation rule?"
        content={`${deleteTarget?.name ?? "This rule"} will be removed from the project.`}
      />
    </section>
  );
}
