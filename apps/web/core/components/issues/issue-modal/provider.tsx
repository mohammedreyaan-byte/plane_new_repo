/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { DEFAULT_WORK_ITEM_FORM_VALUES } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { ISearchIssueResponse, TIssue } from "@plane/types";
// components
import { IssueModalContext, type THandleTemplateChangeProps } from "@/components/issues/issue-modal/context";
// hooks
import { useUser } from "@/hooks/store/user/user-user";
// services
import { workItemTemplatesService } from "@/services/work-item-templates.service";

export type TIssueModalProviderProps = {
  templateId?: string;
  dataForPreload?: Partial<TIssue>;
  allowedProjectIds?: string[];
  children: React.ReactNode;
};

export const IssueModalProvider = observer(function IssueModalProvider(props: TIssueModalProviderProps) {
  const { children, allowedProjectIds, templateId, dataForPreload } = props;
  // states
  const [selectedParentIssue, setSelectedParentIssue] = useState<ISearchIssueResponse | null>(null);
  const [workItemTemplateId, setWorkItemTemplateId] = useState<string | null>(templateId ?? null);
  const [isApplyingTemplate, setIsApplyingTemplate] = useState(false);
  // router
  const { projectId } = useParams();
  // store hooks
  const { projectsWithCreatePermissions } = useUser();
  const { t } = useTranslation();
  // derived values
  const projectIdsWithCreatePermissions = Object.keys(projectsWithCreatePermissions ?? {});

  const handleTemplateChange = async ({ workspaceSlug, reset, editorRef }: THandleTemplateChangeProps) => {
    if (!workItemTemplateId || !workspaceSlug) return;
    setIsApplyingTemplate(true);
    try {
      const template = projectId
        ? await workItemTemplatesService
            .getProjectTemplate(workspaceSlug, projectId.toString(), workItemTemplateId)
            .catch(() => workItemTemplatesService.getWorkspaceTemplate(workspaceSlug, workItemTemplateId))
        : await workItemTemplatesService.getWorkspaceTemplate(workspaceSlug, workItemTemplateId);

      const values: Partial<TIssue> = {
        ...DEFAULT_WORK_ITEM_FORM_VALUES,
        ...dataForPreload,
        project_id: projectId?.toString() ?? dataForPreload?.project_id ?? "",
      };
      const data = template.template_data;
      if (data.title_template) values.name = data.title_template;
      if (data.description_template) values.description_html = data.description_template;
      if (data.priority) values.priority = data.priority as TIssue["priority"];
      if (data.type_id) values.type_id = data.type_id;
      if (data.state_id) values.state_id = data.state_id;
      if (data.label_ids?.length) values.label_ids = data.label_ids;
      if (data.assignee_id) values.assignee_ids = [data.assignee_id];
      if (data.module_id) values.module_ids = [data.module_id];
      if (data.cycle_id) values.cycle_id = data.cycle_id;

      reset(values as TIssue);
      if (data.description_template) editorRef.current?.setEditorValue(data.description_template, true);
      else editorRef.current?.clearEditor();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: t("success"),
        message: `${template.name} template applied.`,
      });
    } catch (error) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("error"),
        message: error instanceof Error ? error.message : "Unable to apply the template.",
      });
    } finally {
      setIsApplyingTemplate(false);
    }
  };

  return (
    <IssueModalContext.Provider
      // oxlint-disable-next-line react/jsx-no-constructed-context-values
      value={{
        allowedProjectIds: allowedProjectIds ?? projectIdsWithCreatePermissions,
        workItemTemplateId,
        setWorkItemTemplateId,
        isApplyingTemplate,
        setIsApplyingTemplate,
        selectedParentIssue,
        setSelectedParentIssue,
        issuePropertyValues: {},
        setIssuePropertyValues: () => {},
        issuePropertyValueErrors: {},
        setIssuePropertyValueErrors: () => {},
        getIssueTypeIdOnProjectChange: () => null,
        getActiveAdditionalPropertiesLength: () => 0,
        handlePropertyValuesValidation: () => true,
        handleCreateUpdatePropertyValues: () => Promise.resolve(),
        handleProjectEntitiesFetch: () => Promise.resolve(),
        handleTemplateChange,
        handleConvert: () => Promise.resolve(),
        handleCreateSubWorkItem: () => Promise.resolve(),
      }}
    >
      {children}
    </IssueModalContext.Provider>
  );
});
