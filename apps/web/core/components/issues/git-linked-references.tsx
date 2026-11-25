/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, GitBranch, Github, Plus, Trash2, X } from "lucide-react";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
// services
import { gmcFeaturesService, type WorkItemLink } from "@/services/gmc-features.service";

type Provider = "github" | "gitlab" | "other";
type ReferenceType = "pr" | "commit" | "link";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  workItemKey: string;
  disabled?: boolean;
};

type ReferenceForm = {
  provider: Exclude<Provider, "other">;
  type: Exclude<ReferenceType, "link">;
  title: string;
  url: string;
};

const EMPTY_FORM: ReferenceForm = {
  provider: "github",
  type: "pr",
  title: "",
  url: "",
};

const errorMessage = (error: unknown) => {
  const detail = error as { error?: string; message?: string } | undefined;
  return detail?.error ?? detail?.message ?? "The request could not be completed.";
};

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

const stringValue = (value: unknown) => (typeof value === "string" && value.trim() ? value.trim() : null);

const describeLink = (link: WorkItemLink) => {
  const metadata = asRecord(link.metadata);
  const rawProvider = stringValue(metadata.provider)?.toLowerCase();
  const provider: Provider =
    rawProvider === "github" || rawProvider === "gitlab"
      ? rawProvider
      : /github/i.test(link.url)
        ? "github"
        : /gitlab/i.test(link.url)
          ? "gitlab"
          : "other";
  const metadataType = stringValue(metadata.git_type)?.toLowerCase();
  const isCommit = metadataType === "commit" || /\/commit(?:s)?\//i.test(link.url);
  const isPullRequest = metadataType === "pr" || /\/pull\//i.test(link.url);
  const isMergeRequest = /\/merge_requests\//i.test(link.url);
  const type: ReferenceType = isCommit ? "commit" : isPullRequest || isMergeRequest ? "pr" : "link";

  return {
    id: link.id,
    title: stringValue(link.title) ?? link.url,
    provider,
    type,
    status: stringValue(metadata.status) ?? "linked",
    sha: stringValue(metadata.sha),
    url: link.url,
  };
};

/** Work item detail section backed by the real issue-links API. */
export function GitLinkedReferences({ workspaceSlug, projectId, issueId, workItemKey, disabled = false }: Props) {
  const [links, setLinks] = useState<WorkItemLink[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ReferenceForm>(EMPTY_FORM);

  const loadLinks = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await gmcFeaturesService.getIssueLinks(workspaceSlug, projectId, issueId);
      setLinks(response ?? []);
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to load Git links", message: errorMessage(error) });
    } finally {
      setIsLoading(false);
    }
  }, [issueId, projectId, workspaceSlug]);

  useEffect(() => {
    void loadLinks();
  }, [loadLinks]);

  const saveReference = async () => {
    const title = form.title.trim();
    const url = form.url.trim();
    if (!title || !url) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Missing details", message: "Enter a title and a source URL." });
      return;
    }

    try {
      await gmcFeaturesService.createIssueLink(workspaceSlug, projectId, issueId, {
        title,
        url,
        metadata: {
          provider: form.provider,
          git_type: form.type,
          status: "manual",
        },
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Reference linked",
        message: `Linked to ${workItemKey}.`,
      });
      await loadLinks();
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to link reference", message: errorMessage(error) });
    }
  };

  const removeReference = async (linkId: string) => {
    try {
      await gmcFeaturesService.deleteIssueLink(workspaceSlug, projectId, issueId, linkId);
      setLinks((previous) => previous.filter((link) => link.id !== linkId));
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to remove reference", message: errorMessage(error) });
    }
  };

  const references = links.map(describeLink);
  const inputClass =
    "w-full rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-12 text-primary focus:border-accent-strong focus:outline-none";

  return (
    <div className="mt-6" aria-label="Linked PRs and commits">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <GitBranch className="size-4 text-tertiary" aria-hidden="true" />
          <h6 className="text-body-xs-medium text-primary">Linked PRs &amp; commits</h6>
          <span className="rounded-sm bg-layer-1 px-1.5 py-0.5 text-11 text-secondary">{references.length}</span>
        </div>
        <Button
          variant="secondary"
          size="sm"
          disabled={disabled}
          onClick={() => setShowForm((previous) => !previous)}
          aria-label="Add Git reference"
        >
          {showForm ? <X className="size-4" aria-hidden="true" /> : <Plus className="size-4" aria-hidden="true" />}
          {showForm ? "Close" : "Add"}
        </Button>
      </div>

      {showForm && !disabled && (
        <div className="mb-3 space-y-2 rounded-sm border border-subtle p-3">
          <div className="grid grid-cols-2 gap-2">
            <label className="text-11 text-secondary">
              Provider
              <select
                aria-label="Reference provider"
                className={inputClass}
                value={form.provider}
                onChange={(event) => setForm({ ...form, provider: event.target.value as Exclude<Provider, "other"> })}
              >
                <option value="github">GitHub</option>
                <option value="gitlab">GitLab</option>
              </select>
            </label>
            <label className="text-11 text-secondary">
              Type
              <select
                aria-label="Reference type"
                className={inputClass}
                value={form.type}
                onChange={(event) => setForm({ ...form, type: event.target.value as Exclude<ReferenceType, "link"> })}
              >
                <option value="pr">Pull / merge request</option>
                <option value="commit">Commit</option>
              </select>
            </label>
          </div>
          <input
            aria-label="Reference title"
            className={inputClass}
            placeholder="Reference title"
            value={form.title}
            onChange={(event) => setForm({ ...form, title: event.target.value })}
          />
          <input
            aria-label="Reference URL"
            className={inputClass}
            placeholder="https://"
            value={form.url}
            onChange={(event) => setForm({ ...form, url: event.target.value })}
          />
          <Button variant="primary" size="sm" onClick={saveReference} aria-label="Save Git reference">
            Link reference
          </Button>
        </div>
      )}

      {isLoading ? (
        <p className="rounded-sm border border-dashed border-subtle px-3 py-4 text-center text-12 text-secondary">
          Loading Git references...
        </p>
      ) : references.length === 0 ? (
        <p className="rounded-sm border border-dashed border-subtle px-3 py-4 text-center text-12 text-secondary">
          No Git references link to {workItemKey} yet.
        </p>
      ) : (
        <div className="space-y-2">
          {references.map((reference) => (
            <div
              key={reference.id}
              className="flex items-start justify-between gap-2 rounded-sm border-[0.5px] border-subtle bg-surface-2 px-3 py-2"
              data-testid="git-linked-reference"
            >
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  {reference.provider === "github" ? (
                    <Github className="size-3.5 shrink-0 text-tertiary" aria-hidden="true" />
                  ) : (
                    <GitBranch className="size-3.5 shrink-0 text-tertiary" aria-hidden="true" />
                  )}
                  <span className="rounded-sm bg-layer-1 px-1.5 py-0.5 text-10 font-medium text-secondary uppercase">
                    {reference.type === "commit"
                      ? "Commit"
                      : reference.type === "link"
                        ? "Link"
                        : reference.provider === "gitlab"
                          ? "MR"
                          : "PR"}
                  </span>
                  <span className="rounded-sm bg-layer-1 px-1.5 py-0.5 text-10 text-secondary">{reference.status}</span>
                  {reference.sha && <span className="font-mono text-10 text-tertiary">{reference.sha}</span>}
                </div>
                <a
                  href={reference.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-12 text-accent-primary hover:underline"
                >
                  <span className="truncate">{reference.title}</span>
                  <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
                </a>
              </div>
              {!disabled && (
                <button
                  type="button"
                  onClick={() => removeReference(reference.id)}
                  aria-label={`Remove ${reference.title}`}
                  className="shrink-0 rounded-sm p-1 text-tertiary hover:bg-layer-1 hover:text-primary"
                >
                  <Trash2 className="size-3.5" aria-hidden="true" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
