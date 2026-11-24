/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { TFilterProperty } from "@plane/types";
import { COLLECTION_OPERATOR, EQUALITY_OPERATOR } from "@plane/types";
// local imports
import type { IFilterIconConfig, TCreateFilterConfig, TCreateFilterConfigParams } from "../../../rich-filters";
import { createFilterConfig, createOperatorConfigEntry, getMultiSelectConfig } from "../../../rich-filters";

// ------------ Work item type filter ------------

export type TWorkItemTypeFilterOption = { id: string; name: string };

export type TCreateWorkItemTypeFilterParams = TCreateFilterConfigParams &
  IFilterIconConfig<TWorkItemTypeFilterOption> & {
    workItemTypes: TWorkItemTypeFilterOption[];
  };

/**
 * Get the work item type filter config
 * @param key - The filter key to use
 */
export const getWorkItemTypeFilterConfig =
  <P extends TFilterProperty>(key: P): TCreateFilterConfig<P, TCreateWorkItemTypeFilterParams> =>
  (params: TCreateWorkItemTypeFilterParams) =>
    createFilterConfig<P>({
      id: key,
      label: "Type",
      ...params,
      icon: params.filterIcon,
      supportedOperatorConfigsMap: new Map([
        createOperatorConfigEntry(COLLECTION_OPERATOR.IN, params, (updatedParams) =>
          getMultiSelectConfig<TWorkItemTypeFilterOption, string, TWorkItemTypeFilterOption>(
            {
              items: params.workItemTypes,
              getId: (type) => type.id,
              getLabel: (type) => type.name,
              getValue: (type) => type.id,
              getIconData: (type) => type,
            },
            { singleValueOperator: EQUALITY_OPERATOR.EXACT, ...updatedParams },
            { ...updatedParams }
          )
        ),
      ]),
    });
