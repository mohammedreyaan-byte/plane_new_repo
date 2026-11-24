/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Button } from "@plane/propel/button";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";

type Props = {
  isOpen: boolean;
  stateName: string;
  onClose: () => void;
  onSubmit: (comment: string) => Promise<void>;
};

/** Asks for the comment that a workflow transition requires (for example reopening a bug). */
export function TransitionCommentModal({ isOpen, stateName, onClose, onSubmit }: Props) {
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const close = () => {
    setComment("");
    setIsSubmitting(false);
    onClose();
  };

  const submit = async () => {
    if (!comment.trim()) return;
    setIsSubmitting(true);
    try {
      await onSubmit(comment.trim());
      close();
    } catch {
      setIsSubmitting(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={close} position={EModalPosition.CENTER} width={EModalWidth.XL}>
      <div className="space-y-4 p-5">
        <div>
          <h3 className="text-16 font-medium text-primary">Move to {stateName}</h3>
          <p className="mt-1 text-13 text-secondary">This move needs a comment. It is added to the work item.</p>
        </div>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={4}
          placeholder="Why is this moving?"
          className="w-full resize-none rounded-md border border-subtle bg-surface-1 p-2 text-13 text-primary outline-none focus:border-accent-strong"
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={close} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={submit} loading={isSubmitting} disabled={!comment.trim()}>
            Move
          </Button>
        </div>
      </div>
    </ModalCore>
  );
}
