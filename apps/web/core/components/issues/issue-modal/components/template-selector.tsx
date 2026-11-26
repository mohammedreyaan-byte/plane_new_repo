/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// hooks
import { useIssueModal } from "@/hooks/context/use-issue-modal";
// services
import { workItemTemplatesService, type WorkItemTemplate } from "@/services/work-item-templates.service";

type TemplateChoice = Pick<WorkItemTemplate, "id" | "name" | "scope">;

export const WorkItemTemplateSelector = observer(function WorkItemTemplateSelector() {
  const { workspaceSlug, projectId } = useParams();
  const { workItemTemplateId, setWorkItemTemplateId } = useIssueModal();
  const [templates, setTemplates] = useState<TemplateChoice[]>([]);

  useEffect(() => {
    if (!workspaceSlug) return;
    let cancelled = false;
    const load = async () => {
      try {
        const [projectTemplates, workspaceTemplates] = await Promise.all([
          projectId
            ? workItemTemplatesService.getProjectTemplates(workspaceSlug.toString(), projectId.toString())
            : Promise.resolve([]),
          workItemTemplatesService.getWorkspaceTemplates(workspaceSlug.toString()),
        ]);
        if (!cancelled) setTemplates([...projectTemplates, ...workspaceTemplates]);
      } catch {
        if (!cancelled) setTemplates([]);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId, workspaceSlug]);

  if (templates.length === 0) return null;

  const selected = templates.find((template) => template.id === workItemTemplateId);

  return (
    <div className="pb-3" data-testid="work-item-template-selector">
      <label htmlFor="work-item-template" className="mb-1 block text-11 font-medium text-tertiary">
        Create from template
      </label>
      <select
        id="work-item-template"
        aria-label="Create from template"
        value={workItemTemplateId ?? ""}
        onChange={(event) => setWorkItemTemplateId(event.target.value || null)}
        className="max-w-full rounded-sm border border-subtle bg-surface-2 px-2 py-1 text-12 text-primary"
      >
        <option value="">No template</option>
        {templates.map((template) => (
          <option key={template.id} value={template.id}>
            {template.name} ({template.scope})
          </option>
        ))}
      </select>
      {selected && (
        <p className="mt-1 text-11 text-tertiary">
          Applying <span className="font-medium text-secondary">{selected.name}</span> will pre-fill its configured
          fields. Values you enter in this form take priority.
        </p>
      )}
    </div>
  );
});
