/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// components
import { InitiativeDetailView } from "@/components/initiatives/initiatives-dashboard";
import { PageHead } from "@/components/core/page-title";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";

function InitiativeDetailPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId, initiativeId } = params;
  const { allowPermissions } = useUserPermissions();
  const canEdit = allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.PROJECT);

  return (
    <>
      <PageHead title="Initiative detail" />
      <div className="h-full w-full p-6">
        <InitiativeDetailView
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          initiativeId={initiativeId}
          canEdit={canEdit}
        />
      </div>
    </>
  );
}

export default observer(InitiativeDetailPage);
