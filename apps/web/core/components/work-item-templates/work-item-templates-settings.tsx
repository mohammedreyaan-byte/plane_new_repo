/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useState } from "react";
import { observer } from "mobx-react";
import { Pencil, Plus, Trash2 } from "lucide-react";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { AlertModalCore, EModalWidth, ModalCore } from "@plane/ui";
// services
import {
  workItemTemplatesService,
  type WorkItemTemplate,
  type WorkItemTemplateData,
  type WorkItemTemplateOptions,
  type WorkItemTemplatePayload,
} from "@/services/work-item-templates.service";

type Props = {
  workspaceSlug: string;
  projectId?: string;
  canManage: boolean;
};

type Draft = {
  id: string | null;
  name: string;
  description: string;
  is_public: boolean;
  template_data: WorkItemTemplateData;
};

const emptyDraft = (): Draft => ({
  id: null,
  name: "",
  description: "",
  is_public: true,
  template_data: {},
});

const errorMessage = (error: unknown) => {
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && error && "error" in error) return String((error as { error: unknown }).error);
  return "Please try again.";
};

const fieldLabel = (key: keyof WorkItemTemplateData) =>
  ({
    title_template: "Title",
    description_template: "Description",
    priority: "Priority",
    label_ids: "Labels",
    assignee_id: "Assignee",
    type_id: "Type",
    state_id: "State",
    module_id: "Module",
    cycle_id: "Cycle",
  })[key];

export const WorkItemTemplatesSettings = observer(function WorkItemTemplatesSettings(props: Props) {
  const { workspaceSlug, projectId, canManage } = props;
  const [templates, setTemplates] = useState<WorkItemTemplate[]>([]);
  const [workspaceTemplates, setWorkspaceTemplates] = useState<WorkItemTemplate[]>([]);
  const [options, setOptions] = useState<WorkItemTemplateOptions>({
    states: [],
    labels: [],
    members: [],
    types: [],
    modules: [],
    cycles: [],
    priorities: [],
  });
  const [isLoading, setIsLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [deleteTarget, setDeleteTarget] = useState<WorkItemTemplate | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [scoped, shared, templateOptions] = await Promise.all([
        projectId
          ? workItemTemplatesService.getProjectTemplates(workspaceSlug, projectId)
          : workItemTemplatesService.getWorkspaceTemplates(workspaceSlug),
        projectId ? workItemTemplatesService.getWorkspaceTemplates(workspaceSlug) : Promise.resolve([]),
        projectId
          ? workItemTemplatesService.getProjectOptions(workspaceSlug, projectId)
          : workItemTemplatesService.getWorkspaceOptions(workspaceSlug),
      ]);
      setTemplates(scoped);
      setWorkspaceTemplates(shared);
      setOptions(templateOptions);
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to load templates", message: errorMessage(error) });
    } finally {
      setIsLoading(false);
    }
  }, [projectId, workspaceSlug]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    const name = draft.name.trim();
    if (!name) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Name required", message: "Enter a name for this template." });
      return;
    }
    const payload: WorkItemTemplatePayload = {
      name,
      description: draft.description.trim(),
      template_data: draft.template_data,
      is_public: draft.is_public,
    };
    try {
      if (draft.id) {
        if (projectId)
          await workItemTemplatesService.updateProjectTemplate(workspaceSlug, projectId, draft.id, payload);
        else await workItemTemplatesService.updateWorkspaceTemplate(workspaceSlug, draft.id, payload);
      } else if (projectId) {
        await workItemTemplatesService.createProjectTemplate(workspaceSlug, projectId, payload);
      } else {
        await workItemTemplatesService.createWorkspaceTemplate(workspaceSlug, payload);
      }
      await load();
      setModalOpen(false);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Template saved",
        message: draft.id ? "Template updated." : "Template created.",
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to save template", message: errorMessage(error) });
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    try {
      if (projectId) await workItemTemplatesService.deleteProjectTemplate(workspaceSlug, projectId, deleteTarget.id);
      else await workItemTemplatesService.deleteWorkspaceTemplate(workspaceSlug, deleteTarget.id);
      await load();
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Template deleted", message: `${deleteTarget.name} was removed.` });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to delete template", message: errorMessage(error) });
    } finally {
      setDeleteTarget(null);
    }
  };

  const openEdit = (template: WorkItemTemplate) => {
    setDraft({
      id: template.id,
      name: template.name,
      description: template.description,
      is_public: template.is_public,
      template_data: { ...template.template_data, label_ids: template.template_data.label_ids ?? [] },
    });
    setModalOpen(true);
  };

  const updateData = (key: keyof WorkItemTemplateData, value: string | string[] | null) => {
    setDraft((current) => ({ ...current, template_data: { ...current.template_data, [key]: value } }));
  };

  const renderTemplate = (template: WorkItemTemplate, managed: boolean) => (
    <div
      key={template.id}
      className="flex flex-wrap items-start justify-between gap-4 px-4 py-4"
      data-testid="work-item-template"
    >
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-14 font-medium text-primary">{template.name}</span>
          <span className="rounded-sm bg-layer-1 px-1.5 py-0.5 text-11 text-secondary">
            {template.scope === "project" ? "Project" : "Workspace"}
          </span>
          <span className="rounded-sm bg-layer-2 px-1.5 py-0.5 text-11 text-secondary">
            {template.is_public ? "Public" : "Private"}
          </span>
        </div>
        {template.description && <p className="text-13 text-secondary">{template.description}</p>}
        <div className="flex flex-wrap gap-2">
          {Object.entries(template.template_data)
            .filter(([, value]) => value !== undefined && value !== null && value !== "")
            .map(([key, value]) => (
              <span key={key} className="rounded-sm bg-layer-1 px-2 py-1 text-11 text-accent-primary">
                {fieldLabel(key as keyof WorkItemTemplateData)}:{" "}
                {Array.isArray(value) ? value.length : typeof value === "string" ? value.slice(0, 40) : String(value)}
              </span>
            ))}
        </div>
      </div>
      {managed && canManage && (
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => openEdit(template)} aria-label={`Edit ${template.name}`}>
            <Pencil className="size-4" aria-hidden="true" /> Edit
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setDeleteTarget(template)}
            aria-label={`Delete ${template.name}`}
          >
            <Trash2 className="size-4" aria-hidden="true" /> Delete
          </Button>
        </div>
      )}
    </div>
  );

  const selectClass = "w-full rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13";

  return (
    <section className="space-y-6" aria-label="Work item templates">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-16 font-medium text-primary">
            {projectId ? "Project templates" : "Workspace templates"}
          </h3>
          <p className="mt-1 text-13 text-secondary">
            {projectId
              ? "Project templates appear in work item creation for this project. Workspace templates are also available."
              : "Workspace templates are available in every project in this workspace."}
          </p>
        </div>
        {canManage && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setDraft(emptyDraft());
              setModalOpen(true);
            }}
          >
            <Plus className="size-4" aria-hidden="true" /> New template
          </Button>
        )}
      </div>

      <div className="divide-y divide-subtle rounded-md border border-subtle">
        {templates.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-14 font-medium text-primary">
              {isLoading ? "Loading templates..." : "No templates yet"}
            </p>
            <p className="mt-1 text-13 text-secondary">Create a template to pre-fill new work items.</p>
          </div>
        ) : (
          templates.map((template) => renderTemplate(template, true))
        )}
      </div>

      {projectId && workspaceTemplates.length > 0 && (
        <div>
          <h4 className="mb-2 text-14 font-medium text-primary">Available workspace templates</h4>
          <div className="divide-y divide-subtle rounded-md border border-subtle">
            {workspaceTemplates.map((template) => renderTemplate(template, false))}
          </div>
        </div>
      )}

      <ModalCore
        isOpen={modalOpen}
        handleClose={() => setModalOpen(false)}
        width={EModalWidth.LG}
        className="max-h-[85vh] overflow-y-auto"
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="border-b border-subtle px-6 py-5">
            <h3 className="text-16 font-medium text-primary">{draft.id ? "Edit template" : "New template"}</h3>
            <p className="mt-1 text-13 text-secondary">Choose the fields this template should pre-fill.</p>
          </div>
          <div className="space-y-5 px-6 py-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="template-name" className="mb-1 block text-12 font-medium text-primary">
                  Name
                </label>
                <input
                  id="template-name"
                  aria-label="Template name"
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                  className={selectClass}
                />
              </div>
              <div>
                <label htmlFor="template-priority" className="mb-1 block text-12 font-medium text-primary">
                  Priority
                </label>
                <select
                  id="template-priority"
                  aria-label="Template priority"
                  value={draft.template_data.priority ?? ""}
                  onChange={(event) => updateData("priority", event.target.value || null)}
                  className={selectClass}
                >
                  <option value="">Don't set</option>
                  {options.priorities.map((priority) => (
                    <option key={priority.value} value={priority.value}>
                      {priority.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label htmlFor="template-description" className="mb-1 block text-12 font-medium text-primary">
                Description
              </label>
              <textarea
                id="template-description"
                aria-label="Template description"
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                rows={2}
                className={selectClass}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="template-title" className="mb-1 block text-12 font-medium text-primary">
                  Title template
                </label>
                <input
                  id="template-title"
                  aria-label="Title template"
                  value={draft.template_data.title_template ?? ""}
                  onChange={(event) => updateData("title_template", event.target.value)}
                  className={selectClass}
                />
              </div>
              <div>
                <label htmlFor="template-body" className="mb-1 block text-12 font-medium text-primary">
                  Description template
                </label>
                <input
                  id="template-body"
                  aria-label="Description template"
                  value={draft.template_data.description_template ?? ""}
                  onChange={(event) => updateData("description_template", event.target.value)}
                  className={selectClass}
                />
              </div>
            </div>
            {projectId && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="template-state" className="mb-1 block text-12 font-medium text-primary">
                    State
                  </label>
                  <select
                    id="template-state"
                    aria-label="Template state"
                    value={draft.template_data.state_id ?? ""}
                    onChange={(event) => updateData("state_id", event.target.value || null)}
                    className={selectClass}
                  >
                    <option value="">Don't set</option>
                    {options.states.map((state) => (
                      <option key={state.id} value={state.id}>
                        {state.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="template-type" className="mb-1 block text-12 font-medium text-primary">
                    Work item type
                  </label>
                  <select
                    id="template-type"
                    aria-label="Template work item type"
                    value={draft.template_data.type_id ?? ""}
                    onChange={(event) => updateData("type_id", event.target.value || null)}
                    className={selectClass}
                  >
                    <option value="">Don't set</option>
                    {options.types.map((type) => (
                      <option key={type.id} value={type.id}>
                        {type.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="template-assignee" className="mb-1 block text-12 font-medium text-primary">
                    Assignee
                  </label>
                  <select
                    id="template-assignee"
                    aria-label="Template assignee"
                    value={draft.template_data.assignee_id ?? ""}
                    onChange={(event) => updateData("assignee_id", event.target.value || null)}
                    className={selectClass}
                  >
                    <option value="">Don't set</option>
                    {options.members.map((member) => (
                      <option key={member.id} value={member.id}>
                        {member.display_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="template-labels" className="mb-1 block text-12 font-medium text-primary">
                    Labels
                  </label>
                  <select
                    id="template-labels"
                    aria-label="Template labels"
                    multiple
                    value={draft.template_data.label_ids ?? []}
                    onChange={(event) =>
                      updateData(
                        "label_ids",
                        Array.from(event.target.selectedOptions, (option) => option.value)
                      )
                    }
                    className={selectClass}
                  >
                    {options.labels.map((label) => (
                      <option key={label.id} value={label.id}>
                        {label.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="template-module" className="mb-1 block text-12 font-medium text-primary">
                    Module
                  </label>
                  <select
                    id="template-module"
                    aria-label="Template module"
                    value={draft.template_data.module_id ?? ""}
                    onChange={(event) => updateData("module_id", event.target.value || null)}
                    className={selectClass}
                  >
                    <option value="">Don't set</option>
                    {options.modules.map((module) => (
                      <option key={module.id} value={module.id}>
                        {module.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="template-cycle" className="mb-1 block text-12 font-medium text-primary">
                    Cycle
                  </label>
                  <select
                    id="template-cycle"
                    aria-label="Template cycle"
                    value={draft.template_data.cycle_id ?? ""}
                    onChange={(event) => updateData("cycle_id", event.target.value || null)}
                    className={selectClass}
                  >
                    <option value="">Don't set</option>
                    {options.cycles.map((cycle) => (
                      <option key={cycle.id} value={cycle.id}>
                        {cycle.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}
            <label className="flex items-center gap-2 text-13 text-primary">
              <input
                type="checkbox"
                aria-label="Template is public"
                checked={draft.is_public}
                onChange={(event) => setDraft({ ...draft, is_public: event.target.checked })}
                className="size-4"
              />
              Visible to all workspace members
            </label>
          </div>
          <div className="flex justify-end gap-2 border-t border-subtle px-6 py-4">
            <Button type="button" variant="secondary" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" aria-label="Save work item template">
              Save template
            </Button>
          </div>
        </form>
      </ModalCore>

      <AlertModalCore
        isOpen={deleteTarget !== null}
        handleClose={() => setDeleteTarget(null)}
        handleSubmit={() => void remove()}
        isSubmitting={false}
        title="Delete work item template?"
        content={`${deleteTarget?.name ?? "This template"} will be removed. Existing work items are unaffected.`}
      />
    </section>
  );
});
