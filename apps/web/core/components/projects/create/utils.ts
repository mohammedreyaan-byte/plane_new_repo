/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { PROJECT_AVATARS } from "@plane/propel/emoji-icon-picker";
import type { IProject } from "@plane/types";
import { getRandomCoverImage } from "@/helpers/cover-image.helper";

export const getProjectFormValues = (): Partial<IProject> => ({
  cover_image_url: getRandomCoverImage(),
  description: "",
  // new projects start with a random coloured avatar (can be changed or removed in the picker)
  logo_props: {
    in_use: "avatar",
    avatar: {
      name: PROJECT_AVATARS[Math.floor(Math.random() * PROJECT_AVATARS.length)].name,
    },
  },
  identifier: "GMC",
  name: "",
  network: 2,
  project_lead: null,
});
