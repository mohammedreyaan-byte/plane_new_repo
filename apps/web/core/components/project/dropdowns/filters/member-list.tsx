/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Button } from "@plane/propel/button";
import { ChevronDownIcon } from "@plane/propel/icons";
import { EUserProjectRoles } from "@plane/types";
// plane ui
import { CustomMenu } from "@plane/ui";
// components
import { FilterHeader, FilterOption } from "@/components/issues/issue-layouts/filters";

interface IRoleOption {
  value: string;
  label: string;
}

type Props = {
  appliedFilters: string[] | null;
  handleUpdate: (role: string) => void;
  memberType: "project" | "workspace";
};

const PROJECT_ROLE_OPTIONS: IRoleOption[] = [
  { value: String(EUserProjectRoles.ADMIN), label: "Admin" },
  { value: String(EUserProjectRoles.MEMBER), label: "Member" },
  { value: "12", label: "Developer" },
  { value: "11", label: "QA" },
  { value: String(EUserProjectRoles.GUEST), label: "Guest" },
  { value: "2", label: "Viewer" },
];

const WORKSPACE_ROLE_OPTIONS: IRoleOption[] = [
  { value: "admin", label: "Admin" },
  { value: "member", label: "Member" },
  { value: "developer", label: "Developer" },
  { value: "qa", label: "QA" },
  { value: "guest", label: "Guest" },
  { value: "viewer", label: "Viewer" },
];

const WORKSPACE_STATUS_OPTIONS: IRoleOption[] = [
  { value: "active", label: "Active" },
  { value: "pending", label: "Pending invitations" },
  { value: "suspended", label: "Suspended" },
];

// Role filter group component
const RoleFilterGroup = observer(function RoleFilterGroup({
  appliedFilters,
  handleUpdate,
  memberType,
}: {
  appliedFilters: string[] | null;
  handleUpdate: (role: string) => void;
  memberType: "project" | "workspace";
}) {
  const [isExpanded, setIsExpanded] = useState(true);
  const appliedFiltersCount = appliedFilters?.length ?? 0;
  const roleOptions = memberType === "project" ? PROJECT_ROLE_OPTIONS : WORKSPACE_ROLE_OPTIONS;

  return (
    <div className="space-y-2">
      <FilterHeader
        title={`Roles${appliedFiltersCount > 0 ? ` (${appliedFiltersCount})` : ""}`}
        isPreviewEnabled={isExpanded}
        handleIsPreviewEnabled={() => setIsExpanded(!isExpanded)}
      />

      {isExpanded && (
        <div className="space-y-1">
          {roleOptions.map((role) => {
            const isSelected = appliedFilters?.includes(role.value) ?? false;
            return (
              <FilterOption
                key={`role-${role.value}`}
                isChecked={isSelected}
                title={role.label}
                onClick={() => handleUpdate(role.value)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
});

export const MemberListFilters = observer(function MemberListFilters(props: Props) {
  const { appliedFilters, handleUpdate, memberType } = props;

  return (
    <div className="space-y-4">
      {/* Role Filter Group */}
      <RoleFilterGroup appliedFilters={appliedFilters} handleUpdate={handleUpdate} memberType={memberType} />
      {memberType === "workspace" && (
        <div className="space-y-2">
          <FilterHeader title="Status" isPreviewEnabled handleIsPreviewEnabled={() => {}} />
          <div className="space-y-1">
            {WORKSPACE_STATUS_OPTIONS.map((option) => (
              <FilterOption
                key={`status-${option.value}`}
                isChecked={appliedFilters?.includes(option.value) ?? false}
                title={option.label}
                onClick={() => handleUpdate(option.value)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

// Dropdown component for member list filters
export const MemberListFiltersDropdown = observer(function MemberListFiltersDropdown(props: Props) {
  const { appliedFilters, handleUpdate, memberType } = props;

  const appliedFiltersCount = appliedFilters?.length ?? 0;

  return (
    <CustomMenu
      customButton={
        <div className="relative">
          <Button variant="secondary" size="lg" className="flex items-center gap-2">
            <span>Filters</span>
            <ChevronDownIcon className="h-3 w-3" />
          </Button>
          {appliedFiltersCount > 0 && (
            <div className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-accent-primary" />
          )}
        </div>
      }
      placement="bottom-start"
    >
      <MemberListFilters appliedFilters={appliedFilters} handleUpdate={handleUpdate} memberType={memberType} />
    </CustomMenu>
  );
});
