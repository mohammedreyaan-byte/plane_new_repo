/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import type { Control } from "react-hook-form";
import { Controller, useWatch } from "react-hook-form";
import type { TIssue } from "@plane/types";
import { WorkItemTypeSelect } from "@/components/work-item-types";
import { useProjectWorkItemTypes } from "@/hooks/use-work-item-types";

type Props = {
  control: Control<TIssue>;
  disabled?: boolean;
  handleFormChange: () => void;
  onTypeCleared?: () => void;
};

/** Work item type field of the create/edit modal. Hidden when the project has types switched off. */
export const IssueTypeSelect = observer(function IssueTypeSelect(props: Props) {
  const { control, disabled = false, handleFormChange } = props;
  const projectId = useWatch({ control, name: "project_id" });
  const typeId = useWatch({ control, name: "type_id" });
  const { rows, isEnabled } = useProjectWorkItemTypes(projectId);

  // A type picked for another project may not be enabled here. Clear it so the project default applies.
  const typeStillValid = !typeId || rows.some((row) => row.is_enabled && row.issue_type.id === typeId);
  useEffect(() => {
    if (isEnabled && !typeStillValid) props.onTypeCleared?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEnabled, typeStillValid]);

  return (
    <Controller
      control={control}
      name="type_id"
      render={({ field: { value, onChange } }) => (
        <WorkItemTypeSelect
          projectId={projectId}
          value={typeStillValid ? value : null}
          disabled={disabled}
          onChange={(id) => {
            onChange(id);
            handleFormChange();
          }}
        />
      )}
    />
  );
});
