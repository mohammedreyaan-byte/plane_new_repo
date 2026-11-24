/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { Combobox } from "@headlessui/react";
import { CheckIcon, LockIcon } from "@plane/propel/icons";
import { cn } from "@plane/utils";

export type TStateOptionProps = {
  projectId: string | null | undefined;
  option: {
    value: string | undefined;
    query: string;
    content: React.ReactNode;
    disabled?: boolean;
    disabledReason?: string;
  };
  selectedValue: string | null | undefined;
  className?: string;
  filterAvailableStateIds?: boolean;
  isForWorkItemCreation?: boolean;
  alwaysAllowStateChange?: boolean;
};

export const StateOption = observer(function StateOption(props: TStateOptionProps) {
  const { option, className = "" } = props;
  const isDisabled = !!option.disabled;
  const reason = option.disabledReason ?? "This transition is not allowed for your role.";

  return (
    <Combobox.Option
      key={option.value}
      value={option.value}
      disabled={isDisabled}
      title={isDisabled ? reason : undefined}
      aria-disabled={isDisabled || undefined}
      className={({ active, selected }) =>
        cn(
          `${className} ${active ? "bg-layer-transparent-hover" : ""} ${selected ? "text-primary" : "text-secondary"}`,
          { "cursor-not-allowed opacity-60": isDisabled }
        )
      }
    >
      {({ selected }) => (
        <div className="flex w-full flex-col" aria-disabled={isDisabled || undefined}>
          <div className="flex w-full items-center gap-2">
            <span className="flex-grow truncate">{option.content}</span>
            {isDisabled && <LockIcon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />}
            {selected && <CheckIcon className="h-3.5 w-3.5 flex-shrink-0" />}
          </div>
          {isDisabled && <span className="pl-6 text-11 text-tertiary">{reason}</span>}
        </div>
      )}
    </Combobox.Option>
  );
});
