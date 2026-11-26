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
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";

function WorkspaceWorkItemTemplatesPage({ params }: Route.ComponentProps) {
  const { workspaceSlug } = params;
  const { currentWorkspace } = useWorkspace();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { t } = useTranslation();

  const canView = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.WORKSPACE,
    workspaceSlug
  );

  if (workspaceUserInfo && !canView) return <NotAuthorizedView section="settings" className="h-auto" />;

  return (
    <SettingsContentWrapper>
      <PageHead title={currentWorkspace?.name ? `${currentWorkspace.name} - Work item templates` : undefined} />
      <SettingsHeading
        title={t("workspace_settings.settings.work_item_templates.heading")}
        description={t("workspace_settings.settings.work_item_templates.description")}
      />
      <div className="mt-6">
        <WorkItemTemplatesSettings workspaceSlug={workspaceSlug} canManage={canView} />
      </div>
    </SettingsContentWrapper>
  );
}

export default observer(WorkspaceWorkItemTemplatesPage);
