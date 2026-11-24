/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { LockIcon } from "@plane/propel/icons";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
// local imports
import { IssueActivityBlockComponent } from "./";

type TIssueWorkflowOverrideActivity = { activityId: string; ends: "top" | "bottom" | undefined };

/** Durable admin-override audit entry written alongside the normal state activity. */
export const IssueWorkflowOverrideActivity = observer(function IssueWorkflowOverrideActivity(
  props: TIssueWorkflowOverrideActivity
) {
  const { activityId, ends } = props;
  const {
    activity: { getActivityById },
  } = useIssueDetail();
  const activity = getActivityById(activityId);

  if (!activity) return <></>;

  return (
    <IssueActivityBlockComponent
      activityId={activityId}
      ends={ends}
      icon={<LockIcon className="h-4 w-4 flex-shrink-0 text-secondary" aria-hidden="true" />}
    >
      <>
        used an{" "}
        <span className="rounded-sm border border-accent-strong px-1 py-0.5 font-medium text-primary">
          Admin override
        </span>{" "}
        to change the state.
      </>
    </IssueActivityBlockComponent>
  );
});
