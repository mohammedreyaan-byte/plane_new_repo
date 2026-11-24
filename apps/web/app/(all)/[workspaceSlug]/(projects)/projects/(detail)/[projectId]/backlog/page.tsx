/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { BacklogRoot } from "@/components/backlog/root";

function ProjectBacklogPage() {
  const { workspaceSlug, projectId } = useParams();
  if (!workspaceSlug || !projectId) return null;
  return <BacklogRoot workspaceSlug={workspaceSlug.toString()} projectId={projectId.toString()} />;
}

export default observer(ProjectBacklogPage);
