/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssueTypeIconKey } from "@/services/issue/issue_type.service";

const ICON_COLORS: Record<TIssueTypeIconKey, string> = {
  epic: "#904EE2",
  story: "#5B9A1F",
  task: "#1868DB",
  bug: "#C9372C",
  subtask: "#1868DB",
  improvement: "#0C8A87",
  feature: "#22A06B",
  spike: "#D97008",
  test: "#6554C0",
  incident: "#C9372C",
  support: "#5E6C84",
};

const SIZE_MAP = { xs: 14, sm: 16, md: 18, lg: 20 } as const;

type Props = {
  icon?: TIssueTypeIconKey | string;
  color?: string;
  size?: keyof typeof SIZE_MAP;
  className?: string;
};

type TIssueTypeLike = { key?: string | null; name?: string | null; logo_props?: unknown };

/**
 * Works out which icon + colour a work item type should use.
 * Handles both stored shapes of `logo_props`:
 *   { icon: "bug", color: "#EF4444" }                       (workspace seeder)
 *   { in_use: "icon", icon: { name: "bug", color: "..." } } (API default types)
 * and falls back to the type's `key` / `name` (bug, task, story, epic, subtask...).
 */
export function resolveIssueTypeIcon(type?: TIssueTypeLike | null): { icon: string; color?: string } {
  const logo = (type?.logo_props ?? {}) as { icon?: string | { name?: string; color?: string }; color?: string };
  const nested = typeof logo.icon === "object" && logo.icon !== null ? logo.icon : undefined;
  const candidates = [
    typeof logo.icon === "string" ? logo.icon : nested?.name,
    type?.key,
    type?.name?.toLowerCase().replace(/[\s-]+/g, ""),
  ];
  const icon = candidates.find((c): c is string => !!c && c in ICON_COLORS) ?? "task";
  return { icon, color: logo.color ?? nested?.color };
}

/** Jira-style issue type icon: an outlined coloured glyph (no filled background). */
export function IssueTypeIcon(props: Props) {
  const { icon = "task", color, size = "sm", className } = props;
  const key = (icon in ICON_COLORS ? icon : "task") as TIssueTypeIconKey;
  const stroke = color ?? ICON_COLORS[key];
  const px = SIZE_MAP[size];

  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 16 16"
      role="img"
      aria-label={key}
      className={className}
      fill="none"
      stroke={stroke}
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0 }}
    >
      {/* Epic: lightning bolt */}
      {key === "epic" && <path d="M9.4 1.8 3.8 9h4.1l-.9 5.2L12.6 7H8.5l.9-5.2Z" />}
      {/* Story: bookmark */}
      {key === "story" && <path d="M4 2.2h8v11.6l-4-3-4 3V2.2Z" />}
      {/* Task: checkbox */}
      {key === "task" && (
        <>
          <rect x="2" y="2" width="12" height="12" rx="2.2" />
          <path d="m5.2 8.2 2 2 3.8-4" />
        </>
      )}
      {/* Bug: beetle */}
      {key === "bug" && (
        <>
          <ellipse cx="8" cy="9.2" rx="3" ry="3.8" />
          <path d="M6.3 4.4a1.9 1.9 0 0 1 3.4 0M8 6v7M2.2 7.2l2.9 1M2 10.6h3.1M2.8 13.6l2.5-1.6M13.8 7.2l-2.9 1M14 10.6h-3.1M13.2 13.6l-2.5-1.6" />
        </>
      )}
      {/* Sub-task: two nested squares */}
      {key === "subtask" && (
        <>
          <rect x="2" y="2" width="7" height="7" rx="1.5" />
          <rect x="7" y="7" width="7" height="7" rx="1.5" />
        </>
      )}
      {/* Improvement: arrow up */}
      {key === "improvement" && <path d="M8 13.5V3M3.8 7.2 8 3l4.2 4.2" />}
      {/* New feature: plus in a circle */}
      {key === "feature" && (
        <>
          <circle cx="8" cy="8" r="6" />
          <path d="M8 5v6M5 8h6" />
        </>
      )}
      {/* Spike / research: magnifying glass */}
      {key === "spike" && (
        <>
          <circle cx="7" cy="7" r="4" />
          <path d="m10 10 3.8 3.8" />
        </>
      )}
      {/* Test: flask */}
      {key === "test" && <path d="M6 2h4M6.6 2v4.4L3.2 12.2a1.2 1.2 0 0 0 1 1.8h7.6a1.2 1.2 0 0 0 1-1.8L9.4 6.4V2" />}
      {/* Incident: warning triangle */}
      {key === "incident" && <path d="M8 2.4 14.2 13H1.8L8 2.4ZM8 6.6v3M8 11.3v.1" />}
      {/* Support: question mark in a circle */}
      {key === "support" && (
        <>
          <circle cx="8" cy="8" r="6" />
          <path d="M6.2 6.4a1.9 1.9 0 1 1 2.9 1.6c-.7.4-1.1.8-1.1 1.5M8 11.4v.1" />
        </>
      )}
    </svg>
  );
}
