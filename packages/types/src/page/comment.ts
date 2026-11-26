/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TPageCommentActor = {
  id: string;
  display_name?: string;
  first_name?: string;
  last_name?: string;
  avatar_url?: string | null;
};

export type TPageComment = {
  id: string;
  page: string;
  workspace: string;
  project: string;
  actor: string | null;
  actor_detail?: TPageCommentActor | null;
  parent: string | null;
  comment_html: string;
  comment_stripped: string;
  content: string;
  content_stripped: string;
  reply_count: number;
  is_own: boolean;
  edited_at: string | null;
  created_at: string;
  updated_at: string;
};

export type TPageCommentPayload = {
  comment_html: string;
  parent?: string | null;
};

export type TPageCommentPaginated = {
  count: number;
  total_count: number;
  next_cursor: string;
  prev_cursor: string;
  next_page_results: boolean;
  prev_page_results: boolean;
  total_pages: number;
  results: TPageComment[];
};
