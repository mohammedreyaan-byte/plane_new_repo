/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// components
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { WorkspaceGitIntegrations } from "@/components/integration/workspace-git-integrations";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { SettingsHeading } from "@/components/settings/heading";
// hooks
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";
import { IntegrationsWorkspaceSettingsHeader } from "./header";

function WorkspaceIntegrationsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug } = params;
  const { t } = useTranslation();
  const { currentWorkspace } = useWorkspace();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  // Resolve the role against the route slug. Relying on the router store alone
  // leaves the page dimmed/greyed out during direct navigation before hydration.
  const canPerformWorkspaceAdminActions = allowPermissions(
    [EUserPermissions.ADMIN],
    EUserPermissionsLevel.WORKSPACE,
    workspaceSlug
  );
  const pageTitle = currentWorkspace?.name
    ? `${currentWorkspace.name} - ${t("workspace_settings.settings.integrations.title")}`
    : undefined;

  if (workspaceUserInfo && !canPerformWorkspaceAdminActions) {
    return <NotAuthorizedView section="settings" className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<IntegrationsWorkspaceSettingsHeader />}>
      <PageHead title={pageTitle} />
      <section className="w-full">
        <SettingsHeading
          title={t("workspace_settings.settings.integrations.heading")}
          description={t("workspace_settings.settings.integrations.description")}
        />
        <div className="mb-4 flex justify-end">
          <Link
            href={`/${workspaceSlug}/settings/integrations/slack/`}
            className="inline-flex items-center gap-1.5 text-12 text-accent-primary hover:underline"
          >
            Configure Slack notifications <ExternalLink className="size-3.5" aria-hidden="true" />
          </Link>
        </div>
        <WorkspaceGitIntegrations workspaceSlug={workspaceSlug} />
      </section>
    </SettingsContentWrapper>
  );
}

export default observer(WorkspaceIntegrationsPage);
