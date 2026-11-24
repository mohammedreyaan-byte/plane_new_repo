/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export enum EAuthenticationPageType {
  STATIC = "STATIC",
  NOT_AUTHENTICATED = "NOT_AUTHENTICATED",
  AUTHENTICATED = "AUTHENTICATED",
}

export enum EInstancePageType {
  PRE_SETUP = "PRE_SETUP",
  POST_SETUP = "POST_SETUP",
}

export enum EUserStatus {
  ERROR = "ERROR",
  AUTHENTICATION_NOT_DONE = "AUTHENTICATION_NOT_DONE",
  NOT_YET_READY = "NOT_YET_READY",
}

export type TUserStatus = {
  status: EUserStatus | undefined;
  message?: string;
};

export enum EUserPermissionsLevel {
  WORKSPACE = "WORKSPACE",
  PROJECT = "PROJECT",
}

export type TUserPermissionsLevel = EUserPermissionsLevel;

export enum EUserPermissions {
  ADMIN = 20,
  MEMBER = 15,
  GUEST = 5,
}
export type TUserPermissions = EUserPermissions;

// Roles added for the internal team. The API stores them as integers next to the legacy three.
// Developer and QA behave like Member in the UI (the API still limits Member-only actions with
// capabilities); Viewer behaves like Guest. See apps/api/plane/utils/role_compat.py.
export const DEVELOPER_ROLE = 12 as EUserPermissions;
export const QA_ROLE = 11 as EUserPermissions;
export const VIEWER_ROLE = 2 as EUserPermissions;

/** Widen a list of allowed roles so Developer/QA pass wherever Member does and Viewer wherever Guest does. */
export const expandRolesForUi = (roles: readonly number[]): number[] => {
  const expanded = new Set<number>(roles);
  if (expanded.has(EUserPermissions.MEMBER)) {
    expanded.add(DEVELOPER_ROLE);
    expanded.add(QA_ROLE);
  }
  if (expanded.has(EUserPermissions.GUEST)) expanded.add(VIEWER_ROLE);
  return Array.from(expanded);
};

export type TUserAllowedPermissionsObject = {
  create: TUserPermissions[];
  update: TUserPermissions[];
  delete: TUserPermissions[];
  read: TUserPermissions[];
};
export type TUserAllowedPermissions = {
  workspace: {
    [key: string]: Partial<TUserAllowedPermissionsObject>;
  };
  project: {
    [key: string]: Partial<TUserAllowedPermissionsObject>;
  };
};

export const USER_ALLOWED_PERMISSIONS: TUserAllowedPermissions = {
  workspace: {
    dashboard: {
      read: [EUserPermissions.ADMIN, EUserPermissions.MEMBER, EUserPermissions.GUEST],
    },
  },
  project: {},
};
