/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { IssueTypeIcon } from "@/components/issues/issue-type-icon";

export const TYPE_ICON_CHOICES = [
  { key: "task", color: "#1868DB" },
  { key: "bug", color: "#C9372C" },
  { key: "story", color: "#5B9A1F" },
  { key: "epic", color: "#904EE2" },
  { key: "improvement", color: "#0C8A87" },
  { key: "feature", color: "#22A06B" },
  { key: "spike", color: "#D97008" },
  { key: "test", color: "#6554C0" },
  { key: "incident", color: "#C9372C" },
  { key: "support", color: "#5E6C84" },
] as const;

type Props = {
  value: string;
  color?: string;
  disabled?: boolean;
  label?: string;
  onChange: (icon: string, color: string) => void;
};

/** Small, dependency-free picker backed by the existing IssueTypeIcon glyphs. */
export function TypeIconPicker(props: Props) {
  const { value, color, disabled = false, label = "Icon", onChange } = props;
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-11 uppercase text-tertiary">{label}</legend>
      <div className="flex flex-wrap items-center gap-1" role="group" aria-label={label}>
        {TYPE_ICON_CHOICES.map((choice) => {
          const selected = value === choice.key;
          return (
            <button
              key={choice.key}
              type="button"
              aria-label={choice.key}
              aria-pressed={selected}
              onClick={() => onChange(choice.key, color ?? choice.color)}
              className={`flex h-8 w-8 items-center justify-center rounded-md border ${
                selected ? "border-accent-strong bg-layer-1" : "border-subtle hover:bg-layer-1"
              }`}
            >
              <IssueTypeIcon icon={choice.key} color={selected ? color ?? choice.color : undefined} size="md" />
            </button>
          );
        })}
        <input
          aria-label="Icon colour"
          type="color"
          value={color ?? TYPE_ICON_CHOICES[0].color}
          onChange={(event) => onChange(value, event.target.value)}
          className="h-8 w-9 cursor-pointer rounded-md border border-subtle bg-transparent"
        />
      </div>
    </fieldset>
  );
}
