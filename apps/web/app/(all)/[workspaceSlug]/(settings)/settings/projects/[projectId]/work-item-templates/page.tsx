/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// components
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { SettingsHeading } from "@/components/settings/heading";
import { WorkItemTemplatesSettings } from "@/components/work-item-templates/work-item-templates-settings";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";

function ProjectWorkItemTemplatesPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const { currentProjectDetails } = useProject();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { t } = useTranslation();

  const canView = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );

  if (workspaceUserInfo && !canView) {
    return <NotAuthorizedView section="settings" isProjectView className="h-auto" />;
  }

  return (
    <SettingsContentWrapper>
      <PageHead
        title={currentProjectDetails?.name ? `${currentProjectDetails.name} - Work item templates` : undefined}
      />
      <SettingsHeading
        title={t("project_settings.work_item_templates.heading")}
        description={t("project_settings.work_item_templates.description")}
      />
      <div className="mt-6">
        <WorkItemTemplatesSettings workspaceSlug={workspaceSlug} projectId={projectId} canManage={canView} />
      </div>
    </SettingsContentWrapper>
  );
}

export default observer(ProjectWorkItemTemplatesPage);
