/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { SettingsHeading } from "@/components/settings/heading";
import { WorkspaceWorkItemTypesSettings } from "@/components/work-item-types";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useUserPermissions } from "@/hooks/store/user";
import type { Route } from "./+types/page";
import { WorkspaceWorkItemTypesHeader } from "./header";

function WorkspaceWorkItemTypesPage({ params }: Route.ComponentProps) {
  const { workspaceSlug } = params;
  const { currentWorkspace } = useWorkspace();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { t } = useTranslation();
  const canView = allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.WORKSPACE);
  const canManage = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  if (workspaceUserInfo && !canView) return <NotAuthorizedView section="settings" className="h-auto" />;

  return (
    <SettingsContentWrapper header={<WorkspaceWorkItemTypesHeader />}>
      <PageHead title={currentWorkspace?.name ? `${currentWorkspace.name} - Work item types` : undefined} />
      <SettingsHeading title={t("work_item_types.label")} description={t("work_item_types.settings.description")} />
      <div className="mt-6">
        <WorkspaceWorkItemTypesSettings workspaceSlug={workspaceSlug} canManage={canManage} />
      </div>
    </SettingsContentWrapper>
  );
}

export default observer(WorkspaceWorkItemTypesPage);
