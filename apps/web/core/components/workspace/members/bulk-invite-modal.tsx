/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import useSWR from "swr";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import { Button } from "@plane/propel/button";
import type { IRole } from "@plane/types";
import { WorkspaceService } from "@/services/workspace.service";

const workspaceService = new WorkspaceService();
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type TInviteResult = { email: string; status: string; member_id?: string | null; error?: string; updated?: boolean };
type Props = {
  workspaceSlug: string;
  isOpen: boolean;
  onClose: () => void;
  onInvited: () => Promise<void>;
};

export function BulkInviteModal({ workspaceSlug, isOpen, onClose, onInvited }: Props) {
  const [rawEmails, setRawEmails] = useState("");
  const [roleKey, setRoleKey] = useState("guest");
  const [results, setResults] = useState<TInviteResult[] | null>(null);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { data: roles } = useSWR<IRole[]>(
    workspaceSlug ? `WORKSPACE_ROLES_${workspaceSlug}` : null,
    () => workspaceService.fetchWorkspaceRoles(workspaceSlug)
  );

  const preview = useMemo(() => {
    const seen = new Set<string>();
    return rawEmails
      .split(/[\s,;]+/)
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean)
      .map((email) => {
        const duplicate = seen.has(email);
        seen.add(email);
        return { email, duplicate, valid: EMAIL_PATTERN.test(email) && !duplicate };
      });
  }, [rawEmails]);

  const handleClose = () => {
    setRawEmails("");
    setResults(null);
    setError("");
    onClose();
  };

  const submit = async () => {
    const validEmails = preview.filter((item) => item.valid).map(({ email }) => ({ email, role_key: roleKey }));
    if (validEmails.length === 0) {
      setError("Enter at least one valid email address.");
      return;
    }
    setIsSubmitting(true);
    setError("");
    try {
      const response = await workspaceService.bulkInviteWorkspace(workspaceSlug, { emails: validEmails });
      setResults([
        ...response.results,
        ...preview
          .filter((item) => !item.valid)
          .map((item) => ({
            email: item.email,
            status: item.duplicate ? "already_member" : "invalid",
            error: item.duplicate ? "Duplicate address in this list" : "Invalid email address",
          })),
      ]);
      await onInvited();
    } catch {
      setError("Invitations could not be sent. Check your access and try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} position={EModalPosition.TOP} width={EModalWidth.XXL}>
      <div className="space-y-5 p-5">
        <div>
          <h2 className="text-body-md-medium text-primary">Invite workspace members</h2>
          <p className="mt-1 text-body-xs-regular text-secondary">
            Paste email addresses separated by commas, spaces, or new lines. Duplicate and invalid addresses are marked before sending.
          </p>
        </div>

        {results ? (
          <div className="space-y-2" aria-live="polite">
            <p className="text-13 text-secondary">Invited {results.filter((item) => item.status === "invited").length}; needs attention {results.filter((item) => item.status !== "invited").length}.</p>
            <div className="max-h-64 divide-y divide-subtle overflow-auto rounded-md border border-subtle">
              {results.map((item, index) => (
                <div key={`${item.email}-${index}`} className="flex items-center justify-between gap-3 px-3 py-2 text-13">
                  <span className="truncate text-primary">{item.email}</span>
                  <span className={item.status !== "invited" ? "shrink-0 text-danger-primary" : "shrink-0 text-secondary"}>
                    {item.error ?? (item.updated ? "Invitation updated" : item.status)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <>
            <label className="block space-y-1.5">
              <span className="text-13 text-secondary">Email addresses</span>
              <textarea
                value={rawEmails}
                onChange={(event) => setRawEmails(event.target.value)}
                rows={5}
                placeholder="alex@company.com\nqa@company.com"
                className="w-full resize-y rounded-md border border-subtle bg-surface-1 px-3 py-2 text-13 text-primary outline-none focus:border-accent-strong"
              />
            </label>
            <label className="flex items-center gap-3 text-13 text-secondary">
              <span className="shrink-0">Workspace role</span>
              <select value={roleKey} onChange={(event) => setRoleKey(event.target.value)} className="h-8 rounded-md border border-subtle bg-surface-1 px-2 text-primary">
                {(roles ?? []).map((role) => <option key={role.key} value={role.key}>{role.name}</option>)}
              </select>
            </label>
            <div className="space-y-2">
              <p className="text-13 font-medium text-primary">Preview · {preview.length} address{preview.length === 1 ? "" : "es"}</p>
              {preview.length > 0 && (
                <div className="max-h-40 divide-y divide-subtle overflow-auto rounded-md border border-subtle">
                  {preview.map((item, index) => (
                    <div key={`${item.email}-${index}`} className="flex items-center justify-between gap-3 px-3 py-2 text-13">
                      <span className="truncate text-primary">{item.email}</span>
                      <span className={item.valid ? "shrink-0 text-secondary" : "shrink-0 text-danger-primary"}>
                        {item.duplicate ? "Duplicate" : item.valid ? "Ready" : "Invalid email"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {error && <p role="alert" className="text-13 text-danger-primary">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="lg" onClick={handleClose}>Close</Button>
          {!results && <Button variant="primary" size="lg" loading={isSubmitting} disabled={isSubmitting || preview.every((item) => !item.valid)} onClick={submit}>Send invitations</Button>}
        </div>
      </div>
    </ModalCore>
  );
}
