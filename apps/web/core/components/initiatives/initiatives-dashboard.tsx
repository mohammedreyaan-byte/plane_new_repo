/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { ArrowLeft, CalendarDays, Pencil, Target, Trash2 } from "lucide-react";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { AlertModalCore, EModalWidth, ModalCore } from "@plane/ui";
// services
import {
  gmcFeaturesService,
  type Initiative,
  type InitiativeChild,
  type InitiativeOptions,
  type InitiativeStatus,
} from "@/services/gmc-features.service";

export type { Initiative, InitiativeChild, InitiativeStatus };

type InitiativeDraft = {
  id?: string;
  name: string;
  description: string;
  status: InitiativeStatus;
  owner: string;
  module_ids: string[];
  epic_ids: string[];
  start_date: string;
  target_date: string;
};

const STATUSES: InitiativeStatus[] = ["planned", "active", "completed", "cancelled"];

const STATUS_CLASSES: Record<InitiativeStatus, string> = {
  planned: "bg-layer-2 text-secondary",
  active: "bg-layer-2 text-accent-primary",
  completed: "bg-success-subtle text-success-primary",
  cancelled: "bg-layer-1 text-tertiary",
};

const EMPTY_DRAFT: InitiativeDraft = {
  name: "",
  description: "",
  status: "planned",
  owner: "",
  module_ids: [],
  epic_ids: [],
  start_date: "",
  target_date: "",
};

const inputClass =
  "w-full rounded-sm border border-subtle bg-surface-2 px-2.5 py-2 text-12 text-primary placeholder:text-tertiary focus:border-accent-strong focus:outline-none";

const errorMessage = (error: unknown) => {
  const detail = error as { error?: string; message?: string } | undefined;
  return detail?.error ?? detail?.message ?? "The request could not be completed.";
};

const dateValue = (value: string | null) => {
  if (!value) return Number.NaN;
  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? Number.NaN : timestamp;
};

const formatDate = (value: string | null) => {
  const timestamp = dateValue(value);
  if (Number.isNaN(timestamp)) return "—";
  return new Date(timestamp).toLocaleDateString();
};

const StatusPill = ({ status }: { status: InitiativeStatus }) => (
  <span
    className={`rounded-sm px-2 py-0.5 text-10 font-medium capitalize ${STATUS_CLASSES[status] ?? STATUS_CLASSES.planned}`}
  >
    {status}
  </span>
);

const ProgressCell = ({ value, className = "" }: { value: number; className?: string }) => (
  <div className={`flex items-center gap-2 ${className}`}>
    <div className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-layer-2">
      <div className="h-full rounded-full bg-accent-primary" style={{ width: `${value}%` }} />
    </div>
    <span className="text-11 text-secondary tabular-nums">{value}%</span>
  </div>
);

type TimelineItem = {
  id: string;
  name: string;
  start_date: string | null;
  target_date: string | null;
  status: InitiativeStatus;
};

const Timeline = observer(function Timeline({ items, title }: { items: TimelineItem[]; title: string }) {
  const datedItems = items.filter((item) => !Number.isNaN(dateValue(item.start_date)));
  const bounds = datedItems.reduce(
    (result, item) => ({
      start: Math.min(result.start, dateValue(item.start_date)),
      end: Math.max(result.end, dateValue(item.target_date) || dateValue(item.start_date)),
    }),
    { start: Number.POSITIVE_INFINITY, end: Number.NEGATIVE_INFINITY }
  );
  const hasRange = Number.isFinite(bounds.start) && Number.isFinite(bounds.end) && bounds.end > bounds.start;

  if (datedItems.length === 0) {
    return (
      <div className="rounded-sm border border-dashed border-subtle px-4 py-6 text-center text-12 text-secondary">
        No dated items to show on the roadmap yet.
      </div>
    );
  }

  const percent = (value: number) =>
    Math.min(100, Math.max(0, ((value - bounds.start) / (bounds.end - bounds.start)) * 100));
  const midpoint = bounds.start + (bounds.end - bounds.start) / 2;

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[640px]">
        <div className="mb-2 flex justify-between text-10 tracking-wide text-tertiary uppercase">
          <span>{formatDate(new Date(bounds.start).toISOString())}</span>
          <span>{formatDate(new Date(midpoint).toISOString())}</span>
          <span>{formatDate(new Date(bounds.end).toISOString())}</span>
        </div>
        <div className="space-y-2">
          {items.map((item) => {
            const start = dateValue(item.start_date);
            const target = dateValue(item.target_date) || start;
            const left = hasRange && !Number.isNaN(start) ? percent(start) : 0;
            const width = hasRange && !Number.isNaN(target) ? Math.max(3, percent(target) - left) : 3;
            return (
              <div key={item.id} className="grid grid-cols-[180px_1fr] items-center gap-3" data-testid="roadmap-row">
                <span className="truncate text-11 text-secondary" title={item.name}>
                  {item.name}
                </span>
                <div className="relative h-6 rounded-sm bg-layer-1">
                  <div
                    className={`absolute inset-y-1 rounded-sm ${STATUS_CLASSES[item.status] ?? STATUS_CLASSES.planned}`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    title={`${item.start_date ?? "—"} → ${item.target_date ?? "—"}`}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <p className="mt-3 text-11 text-tertiary">{title}</p>
      </div>
    </div>
  );
});

type WorkspaceProps = {
  workspaceSlug: string;
  projectId: string;
  canEdit?: boolean;
};

export const InitiativesWorkspace = observer(function InitiativesWorkspace({
  workspaceSlug,
  projectId,
  canEdit = true,
}: WorkspaceProps) {
  const [initiatives, setInitiatives] = useState<Initiative[]>([]);
  const [options, setOptions] = useState<InitiativeOptions>({ members: [], modules: [], epics: [] });
  const [isLoading, setIsLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<"all" | InitiativeStatus>("all");
  const [draft, setDraft] = useState<InitiativeDraft>(EMPTY_DRAFT);
  const [formOpen, setFormOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Initiative | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [records, availableOptions] = await Promise.all([
        gmcFeaturesService.getInitiatives(workspaceSlug, projectId),
        gmcFeaturesService.getInitiativeOptions(workspaceSlug, projectId),
      ]);
      setInitiatives(records);
      setOptions(availableOptions);
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to load initiatives", message: errorMessage(error) });
    } finally {
      setIsLoading(false);
    }
  }, [projectId, workspaceSlug]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(
    () => (statusFilter === "all" ? initiatives : initiatives.filter((item) => item.status === statusFilter)),
    [initiatives, statusFilter]
  );
  const averageProgress = initiatives.length
    ? Math.round(initiatives.reduce((sum, item) => sum + (item.progress ?? 0), 0) / initiatives.length)
    : 0;
  const activeCount = initiatives.filter((item) => item.status === "active").length;

  const openNew = () => {
    setDraft({ ...EMPTY_DRAFT, module_ids: [], epic_ids: [] });
    setFormOpen(true);
  };

  const openEdit = (initiative: Initiative) => {
    setDraft({
      id: initiative.id,
      name: initiative.name,
      description: initiative.description,
      status: initiative.status,
      owner: initiative.owner ?? "",
      module_ids: initiative.module_ids,
      epic_ids: initiative.epic_ids,
      start_date: initiative.start_date ?? "",
      target_date: initiative.target_date ?? "",
    });
    setFormOpen(true);
  };

  const save = async () => {
    if (!draft.name.trim() || !draft.owner) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Missing details", message: "Name and owner are required." });
      return;
    }
    if (draft.start_date && draft.target_date && draft.target_date < draft.start_date) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Invalid dates",
        message: "Target date must be after the start date.",
      });
      return;
    }
    const payload = {
      name: draft.name.trim(),
      description: draft.description.trim(),
      status: draft.status,
      owner: draft.owner,
      module_ids: draft.module_ids,
      epic_ids: draft.epic_ids,
      start_date: draft.start_date || null,
      target_date: draft.target_date || null,
    };
    try {
      if (draft.id) await gmcFeaturesService.updateInitiative(workspaceSlug, projectId, draft.id, payload);
      else await gmcFeaturesService.createInitiative(workspaceSlug, projectId, payload);
      await load();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: draft.id ? "Initiative updated" : "Initiative created",
        message: `${draft.name.trim()} is ready on the roadmap.`,
      });
      setFormOpen(false);
      setDraft({ ...EMPTY_DRAFT });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to save initiative", message: errorMessage(error) });
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    try {
      await gmcFeaturesService.deleteInitiative(workspaceSlug, projectId, deleteTarget.id);
      await load();
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Initiative deleted", message: `${deleteTarget.name} was removed.` });
      setDeleteTarget(null);
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to delete initiative", message: errorMessage(error) });
    }
  };

  return (
    <section className="space-y-6" aria-label="Initiatives roadmap">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-md border border-subtle px-4 py-3">
          <p className="text-11 text-secondary">Initiatives</p>
          <p className="mt-1 text-18 font-medium text-primary">{initiatives.length}</p>
        </div>
        <div className="rounded-md border border-subtle px-4 py-3">
          <p className="text-11 text-secondary">Active</p>
          <p className="mt-1 text-18 font-medium text-primary">{activeCount}</p>
        </div>
        <div className="rounded-md border border-subtle px-4 py-3">
          <p className="text-11 text-secondary">Average progress</p>
          <ProgressCell value={averageProgress} className="mt-2" />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Target className="size-4 text-tertiary" aria-hidden="true" />
          <h2 className="text-16 font-medium text-primary">Strategic initiatives</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-12 text-secondary">
            Status
            <select
              aria-label="Filter initiatives by status"
              className="rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-12 text-primary focus:border-accent-strong focus:outline-none"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as "all" | InitiativeStatus)}
            >
              <option value="all">All statuses</option>
              {STATUSES.map((status) => (
                <option key={status} value={status} className="capitalize">
                  {status}
                </option>
              ))}
            </select>
          </label>
          {canEdit && (
            <Button variant="primary" size="sm" onClick={openNew} aria-label="Create initiative">
              <Target className="size-4" aria-hidden="true" /> New initiative
            </Button>
          )}
        </div>
      </div>

      <div className="overflow-x-auto rounded-md border border-subtle">
        <table className="w-full min-w-[760px] text-left text-12">
          <thead className="bg-surface-2 text-secondary">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Progress</th>
              <th className="px-4 py-2 font-medium">Owner</th>
              <th className="px-4 py-2 font-medium">Dates</th>
              {canEdit && <th className="px-4 py-2 text-right font-medium">Actions</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-subtle">
            {filtered.map((initiative) => (
              <tr key={initiative.id} data-testid="initiative-row">
                <td className="max-w-[260px] px-4 py-3">
                  <Link
                    href={`/${workspaceSlug}/projects/${projectId}/initiatives/${initiative.id}`}
                    className="font-medium text-accent-primary hover:underline"
                  >
                    {initiative.name}
                  </Link>
                  <p className="mt-0.5 truncate text-11 text-tertiary" title={initiative.description}>
                    {initiative.description || "No description"}
                  </p>
                </td>
                <td className="px-4 py-3">
                  <StatusPill status={initiative.status} />
                </td>
                <td className="px-4 py-3">
                  <ProgressCell value={initiative.progress ?? 0} />
                </td>
                <td className="px-4 py-3 text-secondary">{initiative.owner_detail?.display_name ?? "Unassigned"}</td>
                <td className="px-4 py-3 text-secondary">
                  <span className="flex items-center gap-1.5">
                    <CalendarDays className="size-3.5 text-tertiary" aria-hidden="true" />
                    {formatDate(initiative.start_date)} → {formatDate(initiative.target_date)}
                  </span>
                </td>
                {canEdit && (
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => openEdit(initiative)}
                        aria-label={`Edit ${initiative.name}`}
                        className="rounded-sm p-1.5 text-tertiary hover:bg-layer-1 hover:text-primary"
                      >
                        <Pencil className="size-3.5" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteTarget(initiative)}
                        aria-label={`Delete ${initiative.name}`}
                        className="rounded-sm p-1.5 text-tertiary hover:bg-layer-1 hover:text-primary"
                      >
                        <Trash2 className="size-3.5" aria-hidden="true" />
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="border-t border-subtle px-4 py-8 text-center text-12 text-secondary">
            {isLoading ? "Loading initiatives..." : "No initiatives match this status filter."}
          </div>
        )}
      </div>

      <div className="rounded-md border border-subtle">
        <div className="border-b border-subtle px-4 py-3">
          <h3 className="text-14 font-medium text-primary">Roadmap timeline</h3>
          <p className="text-12 text-secondary">Dates are read from the selected initiatives.</p>
        </div>
        <div className="px-4 py-4">
          <Timeline title="Bars show each initiative’s planned start and target date." items={filtered} />
        </div>
      </div>

      <ModalCore isOpen={formOpen} handleClose={() => setFormOpen(false)} width={EModalWidth.XXL}>
        <form
          className="space-y-4 p-6"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="flex items-center gap-2">
            <Target className="size-5 text-primary" aria-hidden="true" />
            <h3 className="text-16 font-medium text-primary">{draft.id ? "Edit initiative" : "New initiative"}</h3>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-11 text-secondary sm:col-span-2">
              Name
              <input
                aria-label="Initiative name"
                className={inputClass}
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                placeholder="Enter an initiative name"
              />
            </label>
            <label className="space-y-1 text-11 text-secondary sm:col-span-2">
              Description
              <textarea
                aria-label="Initiative description"
                className={`${inputClass} min-h-20 resize-none`}
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                placeholder="What outcome does this initiative deliver?"
              />
            </label>
            <label className="space-y-1 text-11 text-secondary">
              Status
              <select
                aria-label="Initiative status"
                className={inputClass}
                value={draft.status}
                onChange={(event) => setDraft({ ...draft, status: event.target.value as InitiativeStatus })}
              >
                {STATUSES.map((status) => (
                  <option key={status} value={status} className="capitalize">
                    {status}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-11 text-secondary">
              Owner
              <select
                aria-label="Initiative owner"
                className={inputClass}
                value={draft.owner}
                onChange={(event) => setDraft({ ...draft, owner: event.target.value })}
              >
                <option value="">Select an owner</option>
                {options.members.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-11 text-secondary sm:col-span-2">
              Linked modules
              <select
                aria-label="Initiative modules"
                multiple
                className={`${inputClass} min-h-20`}
                value={draft.module_ids}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    module_ids: Array.from(event.target.selectedOptions, (option) => option.value),
                  })
                }
              >
                {options.modules.map((module) => (
                  <option key={module.id} value={module.id}>
                    {module.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-11 text-secondary sm:col-span-2">
              Linked epics
              <select
                aria-label="Initiative epics"
                multiple
                className={`${inputClass} min-h-20`}
                value={draft.epic_ids}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    epic_ids: Array.from(event.target.selectedOptions, (option) => option.value),
                  })
                }
              >
                {options.epics.map((epic) => (
                  <option key={epic.id} value={epic.id}>
                    {epic.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-11 text-secondary">
              Start date
              <input
                aria-label="Initiative start date"
                type="date"
                className={inputClass}
                value={draft.start_date}
                onChange={(event) => setDraft({ ...draft, start_date: event.target.value })}
              />
            </label>
            <label className="space-y-1 text-11 text-secondary">
              Target date
              <input
                aria-label="Initiative target date"
                type="date"
                className={inputClass}
                value={draft.target_date}
                onChange={(event) => setDraft({ ...draft, target_date: event.target.value })}
              />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" type="button" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" aria-label="Save initiative">
              {draft.id ? "Save changes" : "Create initiative"}
            </Button>
          </div>
        </form>
      </ModalCore>

      <AlertModalCore
        isOpen={deleteTarget !== null}
        handleClose={() => setDeleteTarget(null)}
        handleSubmit={() => void remove()}
        isSubmitting={false}
        title="Delete initiative?"
        content={`${deleteTarget?.name ?? "This initiative"} will be removed from the roadmap. Its child links will be deleted with it.`}
      />
    </section>
  );
});

type DetailProps = WorkspaceProps & { initiativeId: string };

export const InitiativeDetailView = observer(function InitiativeDetailView({
  workspaceSlug,
  projectId,
  initiativeId,
  canEdit = true,
}: DetailProps) {
  const [initiative, setInitiative] = useState<Initiative | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const records = await gmcFeaturesService.getInitiatives(workspaceSlug, projectId);
      setInitiative(records.find((item) => item.id === initiativeId) ?? null);
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to load initiative", message: errorMessage(error) });
    } finally {
      setIsLoading(false);
    }
  }, [initiativeId, projectId, workspaceSlug]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!initiative) {
    return (
      <div className="rounded-md border border-subtle px-6 py-12 text-center">
        <h2 className="text-16 font-medium text-primary">
          {isLoading ? "Loading initiative" : "Initiative not found"}
        </h2>
        <p className="mt-1 text-12 text-secondary">
          {isLoading
            ? "Fetching the latest initiative record."
            : "It may have been deleted or the link may be outdated."}
        </p>
        <Link
          href={`/${workspaceSlug}/projects/${projectId}/initiatives`}
          className="mt-4 inline-flex items-center gap-1.5 text-12 text-accent-primary hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden="true" /> Back to initiatives
        </Link>
      </div>
    );
  }

  const progress = initiative.progress ?? 0;

  return (
    <div className="space-y-6" aria-label={`${initiative.name} detail`}>
      <Link
        href={`/${workspaceSlug}/projects/${projectId}/initiatives`}
        className="inline-flex items-center gap-1.5 text-12 text-secondary hover:text-primary"
      >
        <ArrowLeft className="size-4" aria-hidden="true" /> All initiatives
      </Link>

      <div className="rounded-md border border-subtle">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-subtle px-5 py-5">
          <div className="max-w-2xl">
            <div className="flex flex-wrap items-center gap-2">
              <Target className="size-5 text-accent-primary" aria-hidden="true" />
              <h1 className="text-20 font-medium text-primary">{initiative.name}</h1>
              <StatusPill status={initiative.status} />
            </div>
            <p className="mt-2 text-13 text-secondary">{initiative.description || "No description provided."}</p>
          </div>
          <div className="w-full max-w-xs">
            <div className="mb-1.5 flex items-center justify-between text-12">
              <span className="text-secondary">Overall progress</span>
              <span className="font-medium text-primary tabular-nums" data-testid="initiative-progress">
                {progress}%
              </span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-layer-2">
              <div className="h-full rounded-full bg-accent-primary" style={{ width: `${progress}%` }} />
            </div>
            <p className="mt-1.5 text-11 text-tertiary">Computed from completed child modules and epics.</p>
          </div>
        </div>
        <div className="grid gap-4 px-5 py-4 sm:grid-cols-4">
          <div>
            <p className="text-11 text-tertiary">Owner</p>
            <p className="mt-0.5 text-12 text-primary">{initiative.owner_detail?.display_name ?? "Unassigned"}</p>
          </div>
          <div>
            <p className="text-11 text-tertiary">Start date</p>
            <p className="mt-0.5 text-12 text-primary">{formatDate(initiative.start_date)}</p>
          </div>
          <div>
            <p className="text-11 text-tertiary">Target date</p>
            <p className="mt-0.5 text-12 text-primary">{formatDate(initiative.target_date)}</p>
          </div>
          <div>
            <p className="text-11 text-tertiary">Children complete</p>
            <p className="mt-0.5 text-12 text-primary">
              {initiative.children.filter((child) => child.completed).length} of {initiative.children.length}
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-md border border-subtle">
        <div className="border-b border-subtle px-4 py-3">
          <h2 className="text-14 font-medium text-primary">Child modules &amp; epics</h2>
          <p className="text-12 text-secondary">
            Completion is read from the linked module status and epic state; edit those records to update progress.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-12">
            <thead className="bg-surface-2 text-secondary">
              <tr>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Owner</th>
                <th className="px-4 py-2 font-medium">Dates</th>
                <th className="px-4 py-2 font-medium">Completion</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-subtle">
              {initiative.children.map((child) => (
                <tr key={child.id} data-testid="initiative-child">
                  <td className="px-4 py-3">
                    <span className="rounded-sm bg-layer-1 px-1.5 py-0.5 text-10 text-secondary uppercase">
                      {child.type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-primary">{child.name}</td>
                  <td className="px-4 py-3 text-secondary">{child.owner || "Unassigned"}</td>
                  <td className="px-4 py-3 text-secondary">
                    {formatDate(child.start_date)} → {formatDate(child.target_date)}
                  </td>
                  <td className="px-4 py-3 text-11 text-secondary">{child.completed ? "Complete" : "In progress"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {initiative.children.length === 0 && (
            <p className="border-t border-subtle px-4 py-6 text-center text-12 text-secondary">
              No modules or epics have been linked to this initiative yet.
            </p>
          )}
        </div>
      </div>

      <div className="rounded-md border border-subtle">
        <div className="border-b border-subtle px-4 py-3">
          <h2 className="text-14 font-medium text-primary">Child timeline</h2>
          <p className="text-12 text-secondary">Roadmap view of linked modules and epics.</p>
        </div>
        <div className="px-4 py-4">
          <Timeline
            title="Bars show each child item’s planned start and target date."
            items={initiative.children.map((child) => ({
              id: child.id,
              name: child.name,
              start_date: child.start_date,
              target_date: child.target_date,
              status: child.completed ? "completed" : "active",
            }))}
          />
        </div>
      </div>
      {canEdit && (
        <p className="text-11 text-tertiary">
          Use the initiatives list to change the owner, status, dates and linked records for this initiative.
        </p>
      )}
    </div>
  );
});
