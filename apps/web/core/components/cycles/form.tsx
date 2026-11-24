/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
// plane imports
import { ETabIndices } from "@plane/constants";
// types
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import type { ICycle } from "@plane/types";
// ui
import { Input, TextArea } from "@plane/ui";
import { getTabIndex } from "@plane/utils";
// components
import { ProjectDropdown } from "@/components/dropdowns/project/dropdown";
// hooks
import { useUser } from "@/hooks/store/user/user-user";

type Props = {
  handleFormSubmit: (values: Partial<ICycle>) => Promise<void>;
  handleClose: () => void;
  status: boolean;
  projectId: string;
  setActiveProject: (projectId: string) => void;
  data?: ICycle | null;
  isMobile?: boolean;
};

const defaultValues: Partial<ICycle> = {
  name: "",
  description: "",
  start_date: null,
  end_date: null,
};

// ---------------------------------------------------------------------------
// Jira-style sprint dialog helpers. Dates are edited as a local date + time pair
// and stored/sent as a full ISO timestamp so the exact time is kept.
// ---------------------------------------------------------------------------
type TDuration = "1w" | "2w" | "3w" | "4w" | "custom";

const DURATION_OPTIONS: { value: TDuration; label: string; weeks?: number }[] = [
  { value: "1w", label: "1 week", weeks: 1 },
  { value: "2w", label: "2 weeks", weeks: 2 },
  { value: "3w", label: "3 weeks", weeks: 3 },
  { value: "4w", label: "4 weeks", weeks: 4 },
  { value: "custom", label: "custom" },
];

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const DEFAULT_START_TIME = "09:00";
const DEFAULT_END_TIME = "17:00";

const pad = (n: number) => String(n).padStart(2, "0");

/** ISO timestamp -> local { date: "YYYY-MM-DD", time: "HH:mm" } */
const splitLocal = (iso?: string | null): { date: string; time: string } => {
  if (!iso) return { date: "", time: "" };
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { date: "", time: "" };
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
  };
};

/** local date + time -> ISO timestamp (UTC) */
const joinLocal = (date: string, time: string): string | null => {
  if (!date) return null;
  const d = new Date(`${date}T${time || "00:00"}`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
};

const getDurationFromDates = (start?: string | null, end?: string | null): TDuration => {
  if (!start || !end) return "custom";
  const diff = new Date(end).getTime() - new Date(start).getTime();
  const match = DURATION_OPTIONS.find((o) => o.weeks && diff === o.weeks * WEEK_MS);
  return match?.value ?? "custom";
};

const roundedNowIso = () => {
  const d = new Date();
  d.setSeconds(0, 0);
  return d.toISOString();
};

const addWeeksIso = (iso: string, weeks: number) => new Date(new Date(iso).getTime() + weeks * WEEK_MS).toISOString();

const FIELD_BOX =
  "flex h-9 w-full items-center gap-2 rounded-md border border-strong bg-surface-1 px-3 text-14 text-primary focus-within:border-accent-strong";
const BARE_INPUT = "min-w-0 bg-transparent text-14 text-primary outline-none";

type TDateTimeFieldProps = {
  label: string;
  value?: string | null;
  defaultTime: string;
  onChange: (iso: string | null) => void;
  tabIndex?: number;
  /** earliest selectable date (YYYY-MM-DD); used to block past dates when creating a sprint */
  minDate?: string;
};

function DateTimeField(props: TDateTimeFieldProps) {
  const { label, value, defaultTime, onChange, tabIndex, minDate } = props;
  const { date, time } = splitLocal(value);

  return (
    <div className="space-y-1">
      <label className="text-13 font-semibold text-secondary">{label}</label>
      <div className={FIELD_BOX}>
        <input
          type="date"
          aria-label={`${label} (date)`}
          className={`${BARE_INPUT} flex-1`}
          value={date}
          min={minDate}
          tabIndex={tabIndex}
          onChange={(e) => onChange(joinLocal(e.target.value, time || defaultTime))}
        />
        <input
          type="time"
          aria-label={`${label} (time)`}
          className={`${BARE_INPUT} w-28`}
          value={time}
          disabled={!date}
          onChange={(e) => onChange(joinLocal(date, e.target.value))}
        />
        <button
          type="button"
          aria-label={`Clear ${label.toLowerCase()}`}
          className="shrink-0 text-tertiary hover:text-primary"
          onClick={() => onChange(null)}
        >
          ✕
        </button>
      </div>
      <p className="text-12 text-tertiary">Uses your local time zone.</p>
    </div>
  );
}

export function CycleForm(props: Props) {
  const { handleFormSubmit, handleClose, status, projectId, setActiveProject, data, isMobile = false } = props;
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const { projectsWithCreatePermissions } = useUser();
  // states
  const [duration, setDuration] = useState<TDuration>("custom");
  const [dateError, setDateError] = useState<string | null>(null);
  // form data
  const {
    formState: { errors, isSubmitting },
    handleSubmit,
    control,
    reset,
    getValues,
    setValue,
  } = useForm<ICycle>({
    defaultValues: {
      project_id: projectId,
      name: data?.name || "",
      description: data?.description || "",
      start_date: data?.start_date || null,
      end_date: data?.end_date || null,
    },
  });

  const { getIndex } = getTabIndex(ETabIndices.PROJECT_CYCLE, isMobile);
  // when creating, the date pickers start at today (past dates are not selectable)
  const minDate = data ? undefined : splitLocal(new Date().toISOString()).date;

  useEffect(() => {
    if (data) {
      reset({ ...defaultValues, ...data });
      setDuration(getDurationFromDates(data.start_date, data.end_date));
    } else {
      // new sprint: start now, 2 weeks long (like Jira)
      const start = roundedNowIso();
      reset({ ...defaultValues, project_id: projectId, start_date: start, end_date: addWeeksIso(start, 2) });
      setDuration("2w");
    }
    setDateError(null);
  }, [data, reset, projectId]);

  const applyDuration = (next: TDuration, start: string | null) => {
    setDuration(next);
    const weeks = DURATION_OPTIONS.find((o) => o.value === next)?.weeks;
    if (weeks && start) setValue("end_date", addWeeksIso(start, weeks), { shouldDirty: true });
  };

  const onSubmit = async (formData: ICycle) => {
    const { start_date, end_date } = formData;
    if (!!start_date !== !!end_date) {
      setDateError("Set both a start and an end date, or clear both to create a draft sprint.");
      return;
    }
    if (start_date && end_date && new Date(end_date).getTime() <= new Date(start_date).getTime()) {
      setDateError("End date must be after the start date.");
      return;
    }
    // New sprints can't be created in the past: a sprint whose end date has passed is shown as Completed
    if (!data) {
      const startOfToday = new Date();
      startOfToday.setHours(0, 0, 0, 0);
      if (start_date && new Date(start_date).getTime() < startOfToday.getTime()) {
        setDateError("Start date can't be in the past.");
        return;
      }
      if (end_date && new Date(end_date).getTime() <= Date.now()) {
        setDateError("This end date has already passed, so the sprint would be marked Completed. Pick a future end date.");
        return;
      }
    }
    setDateError(null);
    await handleFormSubmit(formData);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <div className="space-y-5 p-5">
        <div className="flex items-center gap-x-3">
          {!status && (
            <Controller
              control={control}
              name="project_id"
              render={({ field: { value, onChange } }) => (
                <div className="h-7">
                  <ProjectDropdown
                    value={value}
                    onChange={(val) => {
                      if (!Array.isArray(val)) {
                        onChange(val);
                        setActiveProject(val);
                      }
                    }}
                    multiple={false}
                    buttonVariant="border-with-text"
                    renderCondition={(projectId) => !!projectsWithCreatePermissions?.[projectId]}
                    tabIndex={getIndex("cover_image")}
                  />
                </div>
              )}
            />
          )}
          <h3 className="text-18 font-medium text-secondary">
            {status ? t("project_cycles.update_cycle") : t("project_cycles.create_cycle")}
          </h3>
        </div>
        <p className="text-12 text-tertiary">
          Required fields are marked with an asterisk <span className="text-danger-primary">*</span>
        </p>
        <div className="space-y-4">
          {/* Sprint name */}
          <div className="space-y-1">
            <label htmlFor="sprint-name" className="text-13 font-semibold text-secondary">
              Sprint name <span className="text-danger-primary">*</span>
            </label>
            <Controller
              name="name"
              control={control}
              rules={{
                required: t("title_is_required"),
                maxLength: {
                  value: 255,
                  message: t("title_should_be_less_than_255_characters"),
                },
              }}
              render={({ field: { value, onChange } }) => (
                <Input
                  id="sprint-name"
                  name="name"
                  type="text"
                  className="w-full text-14"
                  value={value}
                  inputSize="md"
                  onChange={onChange}
                  hasError={Boolean(errors?.name)}
                  tabIndex={getIndex("description")}
                  autoFocus
                />
              )}
            />
            <span className="text-11 text-danger-primary">{errors?.name?.message}</span>
          </div>

          {/* Duration */}
          <div className="space-y-1">
            <label htmlFor="sprint-duration" className="text-13 font-semibold text-secondary">
              Duration
            </label>
            <select
              id="sprint-duration"
              className={`${FIELD_BOX} appearance-none`}
              value={duration}
              onChange={(e) => applyDuration(e.target.value as TDuration, getValues("start_date"))}
            >
              {DURATION_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          {/* Start date + time */}
          <Controller
            control={control}
            name="start_date"
            render={({ field: { value, onChange } }) => (
              <DateTimeField
                label="Start date"
                value={value}
                minDate={minDate}
                defaultTime={DEFAULT_START_TIME}
                tabIndex={getIndex("date_range")}
                onChange={(iso) => {
                  onChange(iso);
                  const weeks = DURATION_OPTIONS.find((o) => o.value === duration)?.weeks;
                  // keep the chosen duration when the start moves
                  if (weeks && iso) setValue("end_date", addWeeksIso(iso, weeks), { shouldDirty: true });
                }}
              />
            )}
          />

          {/* End date + time */}
          <Controller
            control={control}
            name="end_date"
            render={({ field: { value, onChange } }) => (
              <DateTimeField
                label="End date"
                value={value}
                minDate={minDate}
                defaultTime={DEFAULT_END_TIME}
                onChange={(iso) => {
                  onChange(iso);
                  // editing the end date by hand switches to a custom duration
                  setDuration("custom");
                }}
              />
            )}
          />
          {dateError && <p className="text-12 text-danger-primary">{dateError}</p>}

          {/* Sprint goal */}
          <div className="space-y-1">
            <label htmlFor="sprint-goal" className="text-13 font-semibold text-secondary">
              Sprint goal
            </label>
            <Controller
              name="description"
              control={control}
              render={({ field: { value, onChange } }) => (
                <TextArea
                  id="sprint-goal"
                  name="description"
                  className="min-h-20 w-full resize-none text-14"
                  hasError={Boolean(errors?.description)}
                  value={value}
                  onChange={onChange}
                  tabIndex={getIndex("description")}
                />
              )}
            />
          </div>
        </div>
      </div>
      <div className="flex items-center justify-end gap-2 border-t-[0.5px] border-subtle px-5 py-4">
        <Button variant="secondary" size="lg" onClick={handleClose} tabIndex={getIndex("cancel")}>
          {t("common.cancel")}
        </Button>
        <Button variant="primary" size="lg" type="submit" loading={isSubmitting} tabIndex={getIndex("submit")}>
          {data
            ? isSubmitting
              ? t("common.updating")
              : t("common.update")
            : isSubmitting
              ? t("common.creating")
              : t("project_cycles.create_cycle")}
        </Button>
      </div>
    </form>
  );
}
