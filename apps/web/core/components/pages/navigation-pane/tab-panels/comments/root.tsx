/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { sortBy } from "lodash-es";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TPageComment } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useWorkspace } from "@/hooks/store/use-workspace";
// services
import { ProjectPageService } from "@/services/page/project-page.service";
// store
import type { TPageInstance } from "@/store/pages/base-page";
// local imports
import { PageCommentCard } from "./comment-card";
import { PageCommentEditor } from "./comment-editor";

const COMMENTS_PER_PAGE = 100;

type Props = {
  page: TPageInstance;
};

const getCreatedAtTimestamp = (comment: TPageComment) => new Date(comment.created_at).getTime();

export const PageNavigationPaneCommentsTabPanel = observer(function PageNavigationPaneCommentsTabPanel(props: Props) {
  const { page } = props;
  // params
  const { workspaceSlug, projectId: routeProjectId } = useParams<{
    workspaceSlug: string;
    projectId?: string;
  }>();
  // translation
  const { t } = useTranslation();
  // states
  const [comments, setComments] = useState<TPageComment[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [replyToId, setReplyToId] = useState<string | null>(null);
  // store hooks
  const { currentProjectDetails } = useProject();
  const { getWorkspaceBySlug } = useWorkspace();
  // derived values
  const pageId = page.id;
  const mutatePageProperties = page.mutateProperties;
  const projectId = routeProjectId ?? page.project_ids?.[0];
  const workspaceId = getWorkspaceBySlug(workspaceSlug)?.id ?? page.workspace ?? "";
  const canDeleteAny = currentProjectDetails?.member_role === 20;
  // services
  const pageService = useMemo(() => new ProjectPageService(), []);

  const fetchComments = useCallback(
    async (cursor?: string, append = false) => {
      if (!workspaceSlug || !projectId || !pageId) return;

      if (append) setIsLoadingMore(true);
      else setIsLoading(true);
      setError(null);

      try {
        const response = await pageService.fetchComments(workspaceSlug, projectId, pageId, {
          cursor,
          perPage: COMMENTS_PER_PAGE,
        });
        setComments((prevComments) => (append ? [...prevComments, ...response.results] : response.results));
        setNextCursor(response.next_cursor || null);
        setHasMore(response.next_page_results);
        // Keep the toolbar count in sync without making the mutable page object
        // a callback dependency. Depending on `page` here retriggers the effect
        // after this update and creates a fetch loop.
        mutatePageProperties({ comment_count: response.total_count }, false);
      } catch (err) {
        console.error("Failed to fetch page comments", err);
        setError(err instanceof Error ? err.message : t("common.error.label"));
      } finally {
        setIsLoading(false);
        setIsLoadingMore(false);
      }
    },
    [mutatePageProperties, pageId, pageService, projectId, t, workspaceSlug]
  );

  useEffect(() => {
    void fetchComments();
  }, [fetchComments]);

  const refreshComments = useCallback(async () => {
    await fetchComments();
  }, [fetchComments]);

  const handleCreate = useCallback(
    async (commentHtml: string) => {
      if (!workspaceSlug || !projectId || !page.id) return;
      await pageService.createComment(workspaceSlug, projectId, page.id, { comment_html: commentHtml });
      await refreshComments();
    },
    [page.id, pageService, projectId, refreshComments, workspaceSlug]
  );

  const handleReply = useCallback(
    async (parent: TPageComment, commentHtml: string) => {
      if (!workspaceSlug || !projectId || !page.id) return;
      await pageService.createComment(workspaceSlug, projectId, page.id, {
        comment_html: commentHtml,
        parent: parent.id,
      });
      setReplyToId(null);
      await refreshComments();
    },
    [page.id, pageService, projectId, refreshComments, workspaceSlug]
  );

  const handleUpdate = useCallback(
    async (commentId: string, commentHtml: string) => {
      if (!workspaceSlug || !projectId || !page.id) return;
      await pageService.updateComment(workspaceSlug, projectId, page.id, commentId, { comment_html: commentHtml });
      setEditingId(null);
      await refreshComments();
    },
    [page.id, pageService, projectId, refreshComments, workspaceSlug]
  );

  const handleDelete = useCallback(
    async (comment: TPageComment) => {
      if (!workspaceSlug || !projectId || !page.id) return;
      try {
        await pageService.deleteComment(workspaceSlug, projectId, page.id, comment.id);
        await refreshComments();
        setToast({
          title: t("common.success"),
          type: TOAST_TYPE.SUCCESS,
          message: t("common.actions.delete"),
        });
      } catch (err) {
        console.error("Failed to delete page comment", err);
        setToast({
          title: t("common.error.label"),
          type: TOAST_TYPE.ERROR,
          message: err instanceof Error ? err.message : t("common.error.label"),
        });
      }
    },
    [page.id, pageService, projectId, refreshComments, t, workspaceSlug]
  );

  const handleLoadMore = useCallback(async () => {
    if (!nextCursor || isLoadingMore) return;
    await fetchComments(nextCursor, true);
  }, [fetchComments, isLoadingMore, nextCursor]);

  const { rootComments, repliesByParentId } = useMemo(() => {
    const commentIds = new Set(comments.map((comment) => comment.id));
    const replies = new Map<string, TPageComment[]>();

    comments.forEach((comment) => {
      if (!comment.parent || !commentIds.has(comment.parent)) return;
      const siblings = replies.get(comment.parent) ?? [];
      siblings.push(comment);
      replies.set(comment.parent, siblings);
    });
    replies.forEach((siblings, parentId) => replies.set(parentId, sortBy(siblings, getCreatedAtTimestamp)));

    return {
      rootComments: sortBy(
        comments.filter((comment) => !comment.parent || !commentIds.has(comment.parent)),
        getCreatedAtTimestamp
      ),
      repliesByParentId: replies,
    };
  }, [comments]);

  const renderComment = (comment: TPageComment, depth = 0): ReactNode => {
    const replies = repliesByParentId.get(comment.id) ?? [];

    return (
      <div key={comment.id} className="flex flex-col gap-3">
        <PageCommentCard
          canDeleteAny={canDeleteAny}
          comment={comment}
          isEditing={editingId === comment.id}
          onDelete={handleDelete}
          onEdit={(selectedComment) => {
            setEditingId(selectedComment.id);
            setReplyToId(null);
          }}
          onReply={(selectedComment) => {
            setReplyToId((currentId) => (currentId === selectedComment.id ? null : selectedComment.id));
            setEditingId(null);
          }}
          onStopEditing={() => setEditingId(null)}
          onUpdate={handleUpdate}
          projectId={projectId ?? ""}
          workspaceId={workspaceId}
          workspaceSlug={workspaceSlug ?? ""}
        />
        {replyToId === comment.id && (
          <div className="pl-8">
            <PageCommentEditor
              onCancel={() => setReplyToId(null)}
              onSubmit={(commentHtml) => handleReply(comment, commentHtml)}
              pageId={comment.page}
              projectId={projectId}
              shouldFocus
              workspaceId={workspaceId}
              workspaceSlug={workspaceSlug ?? ""}
            />
          </div>
        )}
        {replies.length > 0 && (
          <div className={cn("flex flex-col gap-3", depth < 3 && "ml-4 border-l border-subtle pl-3")}>
            {replies.map((reply) => renderComment(reply, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  if (!workspaceSlug || !projectId || !workspaceId || !page.id) return null;

  return (
    <div className="flex size-full flex-col overflow-hidden">
      <div className="flex items-center justify-between px-3 pb-2 text-caption-sm-medium text-secondary">
        <span>{t("common.comments")}</span>
        <span>{comments.length}</span>
      </div>
      {error && (
        <div className="mx-3 mb-2 rounded-sm bg-danger-subtle px-2 py-1.5 text-caption-sm-regular text-danger-primary">
          {error}
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        {isLoading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-12 rounded-md bg-layer-transparent-hover" />
            <div className="h-12 rounded-md bg-layer-transparent-hover" />
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {rootComments.map((comment) => renderComment(comment))}
            {hasMore && (
              <button
                type="button"
                className="self-start rounded-sm px-1.5 py-1 text-caption-sm-medium text-accent-primary transition-colors hover:bg-layer-transparent-hover"
                onClick={handleLoadMore}
                disabled={isLoadingMore}
              >
                {t("common.load_more")}
              </button>
            )}
          </div>
        )}
      </div>
      <div className="border-t border-subtle px-3 pt-3">
        <PageCommentEditor
          onSubmit={handleCreate}
          pageId={page.id}
          projectId={projectId}
          workspaceId={workspaceId}
          workspaceSlug={workspaceSlug}
        />
      </div>
    </div>
  );
});
