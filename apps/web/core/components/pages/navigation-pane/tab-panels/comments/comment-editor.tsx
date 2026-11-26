/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useRef } from "react";
import { observer } from "mobx-react";
import { Controller, useForm } from "react-hook-form";
// plane imports
import type { EditorRefApi } from "@plane/editor";
import { useTranslation } from "@plane/i18n";
import { EFileAssetType } from "@plane/types";
import { cn, isCommentEmpty } from "@plane/utils";
// components
import { LiteTextEditor } from "@/components/editor/lite-text";
// hooks
import { useEditorAsset } from "@/hooks/store/use-editor-asset";

type Props = {
  commentId?: string;
  initialValue?: string;
  onCancel?: () => void;
  onSubmit: (commentHtml: string) => Promise<void>;
  pageId: string;
  placeholder?: string;
  projectId?: string;
  shouldFocus?: boolean;
  submitButtonText?: string;
  workspaceId: string;
  workspaceSlug: string;
};

type TCommentForm = {
  comment_html: string;
};

export const PageCommentEditor = observer(function PageCommentEditor(props: Props) {
  const {
    commentId,
    initialValue = "<p></p>",
    onCancel,
    onSubmit,
    pageId,
    placeholder,
    projectId,
    shouldFocus = false,
    submitButtonText = "common.comment",
    workspaceId,
    workspaceSlug,
  } = props;
  // translation
  const { t } = useTranslation();
  // refs
  const editorRef = useRef<EditorRefApi>(null);
  // store hooks
  const { uploadEditorAsset, duplicateEditorAsset } = useEditorAsset();
  // form info
  const {
    control,
    formState: { isSubmitting },
    handleSubmit,
    reset,
    watch,
  } = useForm<TCommentForm>({
    defaultValues: {
      comment_html: initialValue,
    },
  });
  const commentHtml = watch("comment_html");
  const isEmpty = isCommentEmpty(commentHtml);
  const entityIdentifier = commentId ?? pageId;

  const handleFormSubmit = async (formData: TCommentForm) => {
    try {
      await onSubmit(formData.comment_html);
      reset({ comment_html: "<p></p>" });
      editorRef.current?.clearEditor();
    } catch (error) {
      console.error("Failed to save page comment", error);
    }
  };

  return (
    <form
      className={cn("flex flex-col gap-2")}
      onSubmit={(event) => event.preventDefault()}
      onKeyDown={(event) => {
        if (
          event.key === "Enter" &&
          !event.shiftKey &&
          !event.ctrlKey &&
          !event.metaKey &&
          !isEmpty &&
          !isSubmitting &&
          editorRef.current?.isEditorReadyToDiscard()
        ) {
          event.preventDefault();
          void handleSubmit(handleFormSubmit)(event);
        }
      }}
    >
      <Controller
        name="comment_html"
        control={control}
        render={({ field: { onChange, value } }) => (
          <LiteTextEditor
            editable
            autofocus={shouldFocus}
            workspaceId={workspaceId}
            workspaceSlug={workspaceSlug}
            projectId={projectId}
            id={`page-comment-editor-${commentId ?? pageId}`}
            initialValue={value ?? "<p></p>"}
            value={null}
            placeholder={placeholder}
            ref={editorRef}
            onChange={(_json, html) => onChange(html)}
            onEnterKeyPress={(event) => {
              if (!isEmpty && !isSubmitting) {
                void handleSubmit(handleFormSubmit)(event);
              }
            }}
            isSubmitting={isSubmitting}
            showToolbarInitially={shouldFocus}
            showSubmitButton
            submitButtonText={submitButtonText}
            parentClassName="p-2"
            displayConfig={{
              fontSize: "small-font",
            }}
            uploadFile={async (blockId, file) => {
              const { asset_id } = await uploadEditorAsset({
                blockId,
                data: {
                  entity_identifier: entityIdentifier,
                  entity_type: EFileAssetType.COMMENT_DESCRIPTION,
                },
                file,
                projectId,
                workspaceSlug,
              });
              return asset_id;
            }}
            duplicateFile={async (assetId) => {
              const { asset_id } = await duplicateEditorAsset({
                assetId,
                entityId: entityIdentifier,
                entityType: EFileAssetType.COMMENT_DESCRIPTION,
                projectId,
                workspaceSlug,
              });
              return asset_id;
            }}
          />
        )}
      />
      {onCancel && (
        <button
          type="button"
          className="self-end text-caption-sm-medium text-secondary transition-colors hover:text-primary"
          onClick={onCancel}
          disabled={isSubmitting}
        >
          {t("common.cancel")}
        </button>
      )}
    </form>
  );
});
