/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// components
import { InitiativesWorkspace } from "@/components/initiatives/initiatives-dashboard";
import { PageHead } from "@/components/core/page-title";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";

function ProjectInitiativesPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const { getProjectById } = useProject();
  const { allowPermissions } = useUserPermissions();
  const project = getProjectById(projectId);
  const canEdit = allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.PROJECT);

  return (
    <>
      <PageHead title={project?.name ? `${project.name} - Initiatives` : "Initiatives"} />
      <div className="h-full w-full p-6">
        <InitiativesWorkspace workspaceSlug={workspaceSlug} projectId={projectId} canEdit={canEdit} />
      </div>
    </>
  );
}

export default observer(ProjectInitiativesPage);
