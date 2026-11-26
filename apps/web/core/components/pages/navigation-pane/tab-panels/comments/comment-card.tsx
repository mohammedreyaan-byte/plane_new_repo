/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { CommentReplyIcon, EditIcon, TrashIcon } from "@plane/propel/icons";
import { Tooltip } from "@plane/propel/tooltip";
import type { TPageComment } from "@plane/types";
import { Avatar } from "@plane/ui";
import { calculateTimeAgo, getFileURL, renderFormattedDate, renderFormattedTime } from "@plane/utils";
// components
import { LiteTextEditor } from "@/components/editor/lite-text";
// local imports
import { PageCommentEditor } from "./comment-editor";

type Props = {
  canDeleteAny: boolean;
  comment: TPageComment;
  isEditing: boolean;
  onDelete: (comment: TPageComment) => void;
  onEdit: (comment: TPageComment) => void;
  onReply: (comment: TPageComment) => void;
  onStopEditing: () => void;
  onUpdate: (commentId: string, commentHtml: string) => Promise<void>;
  projectId: string;
  workspaceId: string;
  workspaceSlug: string;
};

export const PageCommentCard = observer(function PageCommentCard(props: Props) {
  const {
    canDeleteAny,
    comment,
    isEditing,
    onDelete,
    onEdit,
    onReply,
    onStopEditing,
    onUpdate,
    projectId,
    workspaceId,
    workspaceSlug,
  } = props;
  // translation
  const { t } = useTranslation();
  // derived values
  const actorName = comment.actor_detail?.display_name ?? "";
  const canEdit = comment.is_own;
  const canDelete = comment.is_own || canDeleteAny;
  const formattedTimestamp = `${renderFormattedDate(comment.created_at)} at ${renderFormattedTime(comment.created_at)}`;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Avatar
          size="sm"
          name={actorName}
          src={getFileURL(comment.actor_detail?.avatar_url ?? "")}
          className="shrink-0"
        />
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5 gap-y-0.5">
          <span className="truncate text-caption-sm-medium">{actorName}</span>
          <Tooltip tooltipContent={formattedTimestamp} position="bottom">
            <span className="text-caption-sm-regular text-tertiary">
              {calculateTimeAgo(comment.created_at)}
              {comment.edited_at ? " (edited)" : ""}
            </span>
          </Tooltip>
        </div>
      </div>

      {isEditing ? (
        <PageCommentEditor
          commentId={comment.id}
          initialValue={comment.comment_html}
          onCancel={onStopEditing}
          onSubmit={(commentHtml) => onUpdate(comment.id, commentHtml)}
          pageId={comment.page}
          projectId={projectId}
          shouldFocus
          submitButtonText="common.save"
          workspaceId={workspaceId}
          workspaceSlug={workspaceSlug}
        />
      ) : (
        <LiteTextEditor
          editable={false}
          id={comment.id}
          initialValue={comment.comment_html}
          workspaceId={workspaceId}
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          containerClassName="!py-1"
          parentClassName="border-none"
          displayConfig={{
            fontSize: "small-font",
          }}
        />
      )}

      {!isEditing && (
        <div className="flex items-center gap-1 pl-8">
          <button
            type="button"
            className="flex items-center gap-1 rounded-sm px-1.5 py-1 text-caption-sm-regular text-secondary transition-colors hover:bg-layer-transparent-hover hover:text-primary"
            onClick={() => onReply(comment)}
          >
            <CommentReplyIcon className="size-3" />
            {t("common.actions.reply")}
          </button>
          {canEdit && (
            <button
              type="button"
              className="flex items-center gap-1 rounded-sm px-1.5 py-1 text-caption-sm-regular text-secondary transition-colors hover:bg-layer-transparent-hover hover:text-primary"
              onClick={() => onEdit(comment)}
            >
              <EditIcon className="size-3" />
              {t("common.actions.edit")}
            </button>
          )}
          {canDelete && (
            <button
              type="button"
              className="flex items-center gap-1 rounded-sm px-1.5 py-1 text-caption-sm-regular text-secondary transition-colors hover:bg-layer-transparent-hover hover:text-danger-primary"
              onClick={() => onDelete(comment)}
            >
              <TrashIcon className="size-3" />
              {t("common.actions.delete")}
            </button>
          )}
        </div>
      )}
    </div>
  );
});
