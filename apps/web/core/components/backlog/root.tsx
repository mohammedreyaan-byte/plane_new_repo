/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useMemo, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { ChevronDown, ChevronRight, Plus, Search } from "lucide-react";
import useSWR from "swr";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { ICycle, TIssue } from "@plane/types";
import { Avatar } from "@plane/ui";
import { cn, getFileURL } from "@plane/utils";
// components
import { CycleCreateUpdateModal } from "@/components/cycles/modal";
import { IssueTypeIcon, resolveIssueTypeIcon } from "@/components/issues/issue-type-icon";
// hooks
import { useCycle } from "@/hooks/store/use-cycle";
import { useMember } from "@/hooks/store/use-member";
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";
import { useIssueTypes } from "@/hooks/use-issue-types";
// services
import { IssueService } from "@/services/issue";

const issueService = new IssueService();

type Props = { workspaceSlug: string; projectId: string };

const BACKLOG_KEY = "__backlog__";
const GROUP_PILL: Record<string, string> = {
  backlog: "bg-layer-2 text-secondary",
  unstarted: "bg-layer-2 text-secondary",
  started: "bg-[#cfe1fd] text-[#0c66e4]",
  completed: "bg-[#dcfff1] text-[#216e4e]",
  cancelled: "bg-[#ffd5d2] text-[#ae2e24]",
};

const fmt = (d: string | null | undefined) =>
  d ? new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";

/** Jira-style Backlog: one section per sprint (cycle) plus the unplanned backlog; drag work items between them. */
export const BacklogRoot = observer(function BacklogRoot({ workspaceSlug, projectId }: Props) {
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [creatingIn, setCreatingIn] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [sprintModal, setSprintModal] = useState(false);

  const { getProjectById } = useProject();
  const { getProjectCycleIds, getCycleById, fetchAllCycles, updateCycleDetails } = useCycle();
  const { getStateById, fetchProjectStates } = useProjectState();
  const { getUserDetails } = useMember();
  const { getIssueTypeById } = useIssueTypes();
  const project = getProjectById(projectId);

  useSWR(`BACKLOG_STATES_${projectId}`, () => fetchProjectStates(workspaceSlug, projectId), {
    revalidateOnFocus: false,
  });
  useSWR(`BACKLOG_CYCLES_${projectId}`, () => fetchAllCycles(workspaceSlug, projectId), { revalidateOnFocus: false });
  const { data: issues, mutate } = useSWR<TIssue[]>(
    `BACKLOG_ISSUES_${projectId}`,
    async () => {
      const res: any = await issueService.getIssues(workspaceSlug, projectId, { per_page: 1000 } as any);
      return (Array.isArray(res) ? res : (res?.results ?? [])) as TIssue[];
    },
    { revalidateOnFocus: false }
  );

  const cycleIds = getProjectCycleIds(projectId);
  const cycles = (cycleIds ?? [])
    .map((id) => getCycleById(id))
    .filter((c): c is ICycle => !!c && !c.archived_at && c.status !== "completed")
    // active sprint first, then by start date, drafts last
    .sort((a, b) => {
      if (a.status === "current" && b.status !== "current") return -1;
      if (b.status === "current" && a.status !== "current") return 1;
      return (a.start_date ?? "9999").localeCompare(b.start_date ?? "9999");
    });

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const map: Record<string, TIssue[]> = {};
    (issues ?? [])
      .filter(
        (i) =>
          !q || i.name.toLowerCase().includes(q) || `${project?.identifier}-${i.sequence_id}`.toLowerCase().includes(q)
      )
      .forEach((i) => {
        const key = i.cycle_id ?? BACKLOG_KEY;
        (map[key] ||= []).push(i);
      });
    return map;
  }, [issues, search, project?.identifier]);

  const moveIssue = useCallback(
    async (issueId: string, target: string) => {
      const issue = issues?.find((i) => i.id === issueId);
      if (!issue) return;
      const from = issue.cycle_id ?? BACKLOG_KEY;
      if (from === target) return;
      try {
        if (target === BACKLOG_KEY) await issueService.removeIssueFromCycle(workspaceSlug, projectId, from, issueId);
        else await issueService.addIssueToCycle(workspaceSlug, projectId, target, { issues: [issueId] });
        await mutate(
          (curr) =>
            (curr ?? []).map((i) => (i.id === issueId ? { ...i, cycle_id: target === BACKLOG_KEY ? null : target } : i)),
          { revalidate: false }
        );
      } catch (e: any) {
        setToast({ type: TOAST_TYPE.ERROR, title: "Could not move work item", message: e?.error ?? "Try again." });
      }
    },
    [issues, mutate, projectId, workspaceSlug]
  );

  const startSprint = async (c: ICycle) => {
    const now = new Date();
    const end =
      c.end_date && new Date(c.end_date) > now ? c.end_date : new Date(now.getTime() + 14 * 864e5).toISOString();
    try {
      await updateCycleDetails(workspaceSlug, projectId, c.id, { start_date: now.toISOString(), end_date: end });
      await fetchAllCycles(workspaceSlug, projectId);
    } catch (e: any) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Could not start sprint",
        message: e?.error ?? "Its dates may overlap another sprint.",
      });
    }
  };

  const completeSprint = async (c: ICycle) => {
    try {
      await updateCycleDetails(workspaceSlug, projectId, c.id, { end_date: new Date().toISOString() });
      await fetchAllCycles(workspaceSlug, projectId);
    } catch (e: any) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Could not complete sprint", message: e?.error ?? "Try again." });
    }
  };

  const createIssue = async (cycleId: string) => {
    const name = newTitle.trim();
    if (!name) return setCreatingIn(null);
    try {
      const created = await issueService.createIssue(workspaceSlug, projectId, { name, project_id: projectId });
      if (cycleId !== BACKLOG_KEY)
        await issueService.addIssueToCycle(workspaceSlug, projectId, cycleId, { issues: [created.id] });
      await mutate();
      setNewTitle("");
      setCreatingIn(null);
    } catch (e: any) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Could not create work item", message: e?.error ?? "Try again." });
    }
  };

  const sprintButton = "ml-2 rounded-md border border-subtle bg-surface-1 px-3 py-1 text-13 font-medium hover:bg-layer-2";

  const renderSection = (key: string, cycle: ICycle | null) => {
    const items = grouped[key] ?? [];
    const open = !collapsed[key];
    const counts = { todo: 0, doing: 0, done: 0 };
    items.forEach((i) => {
      const g = getStateById(i.state_id)?.group;
      if (g === "completed") counts.done++;
      else if (g === "started") counts.doing++;
      else counts.todo++;
    });
    const dates = cycle?.start_date && cycle?.end_date ? `${fmt(cycle.start_date)} – ${fmt(cycle.end_date)}` : "";
    return (
      <section
        key={key}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(key);
        }}
        onDragLeave={() => setDragOver((d) => (d === key ? null : d))}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(null);
          const id = e.dataTransfer.getData("text/plain");
          if (id) void moveIssue(id, key);
        }}
        className={cn("rounded-xl bg-layer-1 p-3", { "ring-2 ring-[#388bff]": dragOver === key })}
      >
        <div className="flex items-center gap-2 px-1 pb-2">
          <button onClick={() => setCollapsed((c) => ({ ...c, [key]: open }))} className="text-secondary">
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
          <span className="text-14 font-semibold text-primary">{cycle ? cycle.name : "Backlog"}</span>
          {dates && <span className="text-13 text-tertiary">{dates}</span>}
          <span className="text-13 text-tertiary">({items.length} work items)</span>
          <div className="ml-auto flex items-center gap-1.5">
            <span className="rounded bg-layer-2 px-1.5 text-12 font-medium text-secondary">{counts.todo}</span>
            <span className="rounded bg-[#cfe1fd] px-1.5 text-12 font-medium text-[#0c66e4]">{counts.doing}</span>
            <span className="rounded bg-[#dcfff1] px-1.5 text-12 font-medium text-[#216e4e]">{counts.done}</span>
            {cycle && cycle.status === "current" && (
              <button onClick={() => completeSprint(cycle)} className={sprintButton}>
                Complete sprint
              </button>
            )}
            {cycle && cycle.status !== "current" && (
              <button onClick={() => startSprint(cycle)} className={sprintButton}>
                Start sprint
              </button>
            )}
          </div>
        </div>
        {open && (
          <>
            <div className="overflow-hidden rounded-lg border border-subtle bg-surface-1">
              {items.length === 0 && (
                <div className="m-2 rounded-lg border border-dashed border-subtle p-6 text-center text-13 text-secondary">
                  {cycle ? "Plan a sprint by dragging work items into it." : "Your backlog is empty."}
                </div>
              )}
              {items.map((issue) => {
                const state = getStateById(issue.state_id);
                const type = resolveIssueTypeIcon(getIssueTypeById(issue.type_id));
                const assignee = issue.assignee_ids?.[0] ? getUserDetails(issue.assignee_ids[0]) : undefined;
                return (
                  <div
                    key={issue.id}
                    draggable
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", issue.id)}
                    className="flex cursor-grab items-center gap-3 border-b border-subtle px-4 py-2 last:border-b-0 hover:bg-layer-1"
                  >
                    <IssueTypeIcon icon={type.icon} color={type.color} size="md" />
                    <span className="w-24 shrink-0 text-13 text-secondary">
                      {project?.identifier}-{issue.sequence_id}
                    </span>
                    <Link
                      href={`/${workspaceSlug}/browse/${project?.identifier}-${issue.sequence_id}/`}
                      className="min-w-0 flex-1 truncate text-14 text-primary hover:underline"
                    >
                      {issue.name}
                    </Link>
                    <span
                      className={cn("rounded px-2 py-0.5 text-12 font-medium", GROUP_PILL[state?.group ?? "unstarted"])}
                    >
                      {state?.name ?? "—"}
                    </span>
                    <span className="w-12 text-center text-13 text-secondary">
                      {issue.target_date ? fmt(issue.target_date) : "–"}
                    </span>
                    <Avatar size="md" name={assignee?.display_name} src={getFileURL(assignee?.avatar_url ?? "")} />
                  </div>
                );
              })}
            </div>
            {creatingIn === key ? (
              <input
                autoFocus
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void createIssue(key);
                  if (e.key === "Escape") setCreatingIn(null);
                }}
                onBlur={() => !newTitle && setCreatingIn(null)}
                placeholder="What needs to be done?"
                className="mt-2 w-full rounded-md border border-[#388bff] bg-surface-1 px-3 py-2 text-14 outline-none"
              />
            ) : (
              <button
                onClick={() => {
                  setNewTitle("");
                  setCreatingIn(key);
                }}
                className="mt-2 flex items-center gap-1.5 px-2 py-1 text-14 text-secondary hover:text-primary"
              >
                <Plus className="size-4" /> Create
              </button>
            )}
          </>
        )}
      </section>
    );
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 rounded-md border border-subtle px-3 py-1.5">
          <Search className="size-4 text-tertiary" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search backlog"
            className="bg-transparent text-14 outline-none"
          />
        </div>
        <button
          onClick={() => setSprintModal(true)}
          className="ml-auto rounded-md bg-[#1868db] px-3 py-1.5 text-13 font-medium text-white hover:bg-[#0c66e4]"
        >
          Create sprint
        </button>
      </div>
      {cycles.map((c) => renderSection(c.id, c))}
      {renderSection(BACKLOG_KEY, null)}
      <CycleCreateUpdateModal
        isOpen={sprintModal}
        handleClose={() => setSprintModal(false)}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
      />
    </div>
  );
});
