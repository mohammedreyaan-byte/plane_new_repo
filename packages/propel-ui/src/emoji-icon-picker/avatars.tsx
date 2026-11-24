/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { cn } from "../utils/classname";

/**
 * Project avatars: simple white glyphs on coloured rounded squares.
 * Glyphs are drawn on a 24x24 grid (stroke based) and scaled into the square.
 */
type TAvatar = { name: string; label: string; bg: string; glyph: ReactNode };

export const PROJECT_AVATARS: TAvatar[] = [
  {
    name: "rocket",
    label: "Rocket",
    bg: "#2F6FEB",
    glyph: (
      <>
        <path d="M12 3c3 2 4.5 5 4.5 8.5L14 15h-4l-2.5-3.5C7.5 8 9 5 12 3Z" />
        <circle cx="12" cy="9.5" r="1.5" />
        <path d="M8 14l-3 3v2l3-1M16 14l3 3v2l-3-1M10.5 18.5 12 21l1.5-2.5" />
      </>
    ),
  },
  {
    name: "planet",
    label: "Planet",
    bg: "#7B61D1",
    glyph: (
      <>
        <circle cx="12" cy="12" r="4.5" />
        <ellipse cx="12" cy="12" rx="9" ry="3.2" transform="rotate(-25 12 12)" />
      </>
    ),
  },
  {
    name: "star",
    label: "Star",
    bg: "#F4B400",
    glyph: <polygon points="12 3.5 14.6 9.2 20.8 9.9 16.2 14.1 17.5 20.2 12 17.1 6.5 20.2 7.8 14.1 3.2 9.9 9.4 9.2" />,
  },
  {
    name: "heart",
    label: "Heart",
    bg: "#E8478A",
    glyph: <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z" />,
  },
  { name: "bolt", label: "Bolt", bg: "#F0562B", glyph: <path d="M13 3 5.5 13.5H11L10 21l8-11h-5.5L13 3Z" /> },
  { name: "flag", label: "Flag", bg: "#D6336C", glyph: <path d="M6 21V4M6 5h11l-2.5 3.5L17 12H6" /> },
  {
    name: "cloud",
    label: "Cloud",
    bg: "#1E9BD7",
    glyph: <path d="M7 18a4 4 0 0 1-.6-8A5.5 5.5 0 0 1 17 8.5 4.8 4.8 0 0 1 17.5 18H7Z" />,
  },
  { name: "leaf", label: "Leaf", bg: "#0F9D58", glyph: <path d="M5 19c0-8 5-13 14-14 0 9-5 14-13 14M5 19l6-6" /> },
  {
    name: "compass",
    label: "Compass",
    bg: "#00A3A3",
    glyph: (
      <>
        <circle cx="12" cy="12" r="9" />
        <polygon points="15.5 8.5 13.5 13.5 8.5 15.5 10.5 10.5" />
      </>
    ),
  },
  {
    name: "gear",
    label: "Gear",
    bg: "#5E6C84",
    glyph: (
      <>
        <circle cx="12" cy="12" r="3.5" />
        <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
      </>
    ),
  },
  {
    name: "target",
    label: "Target",
    bg: "#E5493A",
    glyph: (
      <>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1.2" />
      </>
    ),
  },
  {
    name: "bulb",
    label: "Idea",
    bg: "#FF7A45",
    glyph: (
      <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3Z" />
    ),
  },
  {
    name: "shield",
    label: "Shield",
    bg: "#18B894",
    glyph: (
      <>
        <path d="M12 3l7 3v5.5c0 4.5-3 8-7 9.5-4-1.5-7-5-7-9.5V6l7-3Z" />
        <path d="m9 12 2.2 2.2L15 10" />
      </>
    ),
  },
  { name: "code", label: "Code", bg: "#6C5CE7", glyph: <path d="m8 7-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14" /> },
  { name: "chart", label: "Chart", bg: "#2F6FEB", glyph: <path d="M4 20V4M4 20h16M8 16v-4M12 16V8M16 16v-6" /> },
  { name: "mountain", label: "Mountain", bg: "#0F9D58", glyph: <path d="M3 19 9.5 8l4 6.5L16 11l5 8H3Z" /> },
  {
    name: "coffee",
    label: "Coffee",
    bg: "#A0522D",
    glyph: <path d="M5 9h11v5a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5V9ZM16 10h2a2.5 2.5 0 0 1 0 5h-2M8 3v2M12 3v2" />,
  },
  {
    name: "globe",
    label: "Globe",
    bg: "#1E9BD7",
    glyph: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" />
      </>
    ),
  },
  {
    name: "camera",
    label: "Camera",
    bg: "#D6336C",
    glyph: (
      <>
        <path d="M4 8h3l1.5-2.5h7L17 8h3v11H4V8Z" />
        <circle cx="12" cy="13" r="3.2" />
      </>
    ),
  },
  {
    name: "book",
    label: "Book",
    bg: "#F0562B",
    glyph: <path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4ZM5 17a3 3 0 0 1 3-3h10" />,
  },
  {
    name: "music",
    label: "Music",
    bg: "#7B61D1",
    glyph: (
      <path d="M9 18V6l10-2v12M9 18a2.5 2.5 0 1 1-2.5-2.5A2.5 2.5 0 0 1 9 18ZM19 16a2.5 2.5 0 1 1-2.5-2.5A2.5 2.5 0 0 1 19 16Z" />
    ),
  },
  {
    name: "cube",
    label: "Cube",
    bg: "#00A3A3",
    glyph: <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3ZM12 12l8-4.5M12 12v9M12 12 4 7.5" />,
  },
  {
    name: "flame",
    label: "Flame",
    bg: "#E5493A",
    glyph: <path d="M12 3c1 4 5 5.5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 .3 1.5 1 2 2 2 0-3-.5-5 1-8Z" />,
  },
  {
    name: "anchor",
    label: "Anchor",
    bg: "#2F6FEB",
    glyph: (
      <>
        <circle cx="12" cy="5.5" r="2" />
        <path d="M12 7.5V21M7 11h10M4 14a8 8 0 0 0 16 0" />
      </>
    ),
  },
];

const FALLBACK_AVATAR = PROJECT_AVATARS[0];

type TAvatarIconProps = {
  name?: string;
  size?: number;
  className?: string;
};

/** Coloured rounded-square avatar with a white glyph. Unknown names fall back to the first avatar. */
export function AvatarIcon({ name, size = 16, className }: TAvatarIconProps) {
  const avatar = PROJECT_AVATARS.find((a) => a.name === name) ?? FALLBACK_AVATAR;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role="img"
      aria-label={avatar.label}
      className={cn("shrink-0", className)}
    >
      <rect width="24" height="24" rx="6" fill={avatar.bg} />
      <g
        transform="translate(3.6 3.6) scale(0.7)"
        fill="none"
        stroke="#fff"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {avatar.glyph}
      </g>
    </svg>
  );
}

type TAvatarRootProps = {
  selected?: string;
  onChange: (value: { name: string }) => void;
};

/** "Select an avatar" grid shown in the picker's Avatar tab. */
export function AvatarRoot({ selected, onChange }: TAvatarRootProps) {
  return (
    <div className="p-3.5">
      <p className="pb-2.5 text-13 font-semibold text-primary">Select an avatar</p>
      <div className="grid grid-cols-6 gap-2">
        {PROJECT_AVATARS.map((avatar) => (
          <button
            key={avatar.name}
            type="button"
            title={avatar.label}
            aria-label={avatar.label}
            aria-pressed={selected === avatar.name}
            onClick={() => onChange({ name: avatar.name })}
            className={cn(
              "flex items-center justify-center rounded-lg p-0.5 outline-none hover:scale-105 focus-visible:ring-2 focus-visible:ring-[#1868db]",
              { "ring-2 ring-[#1868db]": selected === avatar.name }
            )}
          >
            <AvatarIcon name={avatar.name} size={36} />
          </button>
        ))}
      </div>
    </div>
  );
}
