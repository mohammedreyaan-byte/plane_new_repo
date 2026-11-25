/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { WORKSPACE_SETTINGS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Breadcrumbs } from "@plane/ui";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { SettingsPageHeader } from "@/components/settings/page-header";
import { WORKSPACE_SETTINGS_ICONS } from "@/components/settings/workspace/sidebar/item-icon";

export const SlackWorkspaceSettingsHeader = observer(function SlackWorkspaceSettingsHeader() {
  const { t } = useTranslation();
  const { workspaceSlug } = useParams();
  const integrations = WORKSPACE_SETTINGS.integrations;
  const slack = WORKSPACE_SETTINGS.slack;
  const IntegrationsIcon = WORKSPACE_SETTINGS_ICONS.integrations;
  const SlackIcon = WORKSPACE_SETTINGS_ICONS.slack;

  return (
    <SettingsPageHeader
      leftItem={
        <div className="flex items-center gap-2">
          <Breadcrumbs>
            <Breadcrumbs.Item
              component={
                <BreadcrumbLink
                  label={t(integrations.i18n_label)}
                  href={`/${workspaceSlug}/settings/integrations/`}
                  icon={<IntegrationsIcon className="size-4 text-tertiary" />}
                />
              }
            />
            <Breadcrumbs.Item
              component={<BreadcrumbLink label={t(slack.i18n_label)} icon={<SlackIcon className="size-4 text-tertiary" />} isLast />}
              isLast
            />
          </Breadcrumbs>
        </div>
      }
    />
  );
});
