/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useState } from "react";
import { Download, FileSpreadsheet, Github, Upload } from "lucide-react";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
// services
import { gmcFeaturesService, type ImportJob } from "@/services/gmc-features.service";

type SourceType = ImportJob["service"];

type Props = { workspaceSlug: string; projectId: string };

const TARGET_FIELDS = [
  "title",
  "description",
  "state",
  "priority",
  "assignee_email",
  "label_names",
  "cycle_name",
  "module_name",
];

const TAB_LABELS: Record<SourceType, string> = {
  csv: "CSV",
  jira: "Jira",
  github: "GitHub",
};

const ACTIVE_STATUSES = new Set<ImportJob["status"]>(["queued", "processing"]);

const errorMessage = (error: unknown) => {
  const detail = error as { error?: string; message?: string } | undefined;
  return detail?.error ?? detail?.message ?? "The request could not be completed.";
};

const parseCsvLine = (line: string): string[] => {
  const values: string[] = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index++) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        current += '"';
        index++;
      } else {
        quoted = !quoted;
      }
    } else if (character === "," && !quoted) {
      values.push(current.trim());
      current = "";
    } else {
      current += character;
    }
  }
  values.push(current.trim());
  return values;
};

const jobDetails = (job: ImportJob) => {
  if (job.file_name) return `${TAB_LABELS[job.service]} import · ${job.file_name}`;
  const metadata = job.metadata as Record<string, unknown>;
  const name = metadata.project_key || metadata.repo;
  return name ? `${TAB_LABELS[job.service]} import · ${String(name)}` : `${TAB_LABELS[job.service]} import`;
};

/** Project settings > Import: real CSV/Jira/GitHub importer with backend job history. */
export function ProjectImportSettings({ workspaceSlug, projectId }: Props) {
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [tab, setTab] = useState<SourceType>("csv");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [csvRowCount, setCsvRowCount] = useState(0);
  const [jira, setJira] = useState({ site_url: "", email: "", api_token: "", project_key: "" });
  const [github, setGithub] = useState({ owner: "", repo: "", token: "", include_prs: true, include_issues: true });

  const load = useCallback(
    async (showErrors = true) => {
      try {
        setJobs(await gmcFeaturesService.getImports(workspaceSlug, projectId));
      } catch (error) {
        if (showErrors)
          setToast({ type: TOAST_TYPE.ERROR, title: "Unable to load imports", message: errorMessage(error) });
      } finally {
        setIsLoading(false);
      }
    },
    [projectId, workspaceSlug]
  );

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(false), 2000);
    return () => window.clearInterval(timer);
  }, [load]);

  const handleCsvFile = async (file: File | undefined) => {
    if (!file) return;
    setCsvFile(file);
    const text = await file.text();
    const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
    setCsvHeaders(lines[0] ? parseCsvLine(lines[0]) : []);
    setCsvRows(lines.slice(1, 6).map(parseCsvLine));
    setCsvRowCount(Math.max(lines.length - 1, 0));
  };

  const recordJob = (job: ImportJob) => {
    setJobs((previous) => [job, ...previous.filter((item) => item.id !== job.id)]);
  };

  const startCsvImport = async () => {
    if (!csvFile) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Choose a file",
        message: "Select a CSV file before starting the import.",
      });
      return;
    }
    try {
      recordJob(await gmcFeaturesService.createCsvImport(workspaceSlug, projectId, csvFile));
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Import queued", message: `${csvFile.name} is being processed.` });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Import failed to start", message: errorMessage(error) });
    }
  };

  const startJiraImport = async () => {
    if (!jira.site_url || !jira.email || !jira.api_token || !jira.project_key) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Missing details", message: "Fill in all Jira connection fields." });
      return;
    }
    try {
      const job = await gmcFeaturesService.createJiraImport(workspaceSlug, projectId, jira);
      recordJob(job);
      setJira((previous) => ({ ...previous, api_token: "" }));
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Import queued", message: `${jira.project_key} is being imported.` });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Import failed to start", message: errorMessage(error) });
    }
  };

  const startGithubImport = async () => {
    if (!github.owner || !github.repo || !github.token) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Missing details",
        message: "Enter the repository owner, name and access token.",
      });
      return;
    }
    if (!github.include_prs && !github.include_issues) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Nothing selected",
        message: "Include issues, pull requests, or both.",
      });
      return;
    }
    try {
      recordJob(await gmcFeaturesService.createGithubImport(workspaceSlug, projectId, github));
      setGithub((previous) => ({ ...previous, token: "" }));
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Import queued",
        message: `${github.owner}/${github.repo} is being imported.`,
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Import failed to start", message: errorMessage(error) });
    }
  };

  const downloadErrorLog = async (job: ImportJob) => {
    try {
      const content = await gmcFeaturesService.getImportErrors(workspaceSlug, projectId, job.id);
      const blob = new Blob([content], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${job.service}-import-errors.txt`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to load errors", message: errorMessage(error) });
    }
  };

  const inputClass =
    "w-full rounded-sm border border-subtle bg-surface-2 px-2 py-1.5 text-13 focus:border-accent-strong focus:outline-none";
  const running = jobs.some((job) => ACTIVE_STATUSES.has(job.status));

  return (
    <section className="mt-8 space-y-6" aria-label="Import work items">
      <div className="flex flex-wrap gap-2 border-b border-subtle" role="tablist" aria-label="Import source">
        {(Object.keys(TAB_LABELS) as SourceType[]).map((source) => (
          <button
            key={source}
            type="button"
            role="tab"
            aria-selected={tab === source}
            onClick={() => setTab(source)}
            className={`px-4 py-2 text-13 font-medium ${
              tab === source
                ? "border-accent-primary border-b-2 text-accent-primary"
                : "text-secondary hover:text-primary"
            }`}
          >
            {TAB_LABELS[source]}
          </button>
        ))}
      </div>

      {tab === "csv" && (
        <div role="tabpanel" aria-label="CSV import" className="space-y-5">
          <div className="rounded-md border border-subtle p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <FileSpreadsheet className="size-5 text-accent-primary" aria-hidden="true" />
                <div>
                  <p className="text-14 font-medium text-primary">CSV file</p>
                  <p className="text-12 text-secondary">Expected columns: {TARGET_FIELDS.join(", ")}.</p>
                </div>
              </div>
              <label
                className="cursor-pointer rounded-sm border border-subtle bg-surface-2 px-3 py-1.5 text-13 text-primary"
                htmlFor="csv-file-input"
              >
                Choose CSV
                <input
                  id="csv-file-input"
                  aria-label="Choose CSV file"
                  type="file"
                  accept=".csv,text/csv"
                  className="sr-only"
                  onChange={(event) => void handleCsvFile(event.target.files?.[0])}
                />
              </label>
            </div>
            {csvFile && (
              <p className="mt-3 text-13 text-secondary">
                Selected: <span className="text-primary">{csvFile.name}</span> · {csvRowCount} data rows
              </p>
            )}
          </div>

          {csvHeaders.length > 0 && (
            <div className="rounded-md border border-subtle">
              <div className="border-b border-subtle px-4 py-3">
                <p className="text-14 font-medium text-primary">Column mapping preview</p>
                <p className="text-12 text-secondary">Detected headers are matched to Plane fields by name.</p>
              </div>
              <table className="w-full text-left text-12">
                <thead className="bg-surface-2 text-secondary">
                  <tr>
                    <th className="px-4 py-2 font-medium">CSV column</th>
                    <th className="px-4 py-2 font-medium">Plane field</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-subtle">
                  {TARGET_FIELDS.map((field) => {
                    const matched = csvHeaders.find((header) => header.toLowerCase().replace(/[\s-]/g, "_") === field);
                    return (
                      <tr key={field} data-testid="csv-column-mapping">
                        <td className="px-4 py-2 text-secondary">{matched ?? "—"}</td>
                        <td className="px-4 py-2 text-primary">{field}</td>
                        <td className="px-4 py-2">
                          <span
                            className={`rounded-sm px-1.5 ${matched ? "bg-layer-1 text-success-primary" : "bg-layer-2 text-tertiary"}`}
                          >
                            {matched ? "Mapped" : "Missing"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {csvRows.length > 0 && (
                <div className="border-t border-subtle px-4 py-3">
                  <p className="mb-2 text-12 font-medium text-primary">First rows</p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-12">
                      <thead className="text-secondary">
                        <tr>
                          {csvHeaders.map((header) => (
                            <th key={header} className="px-2 py-1 font-medium">
                              {header}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-subtle">
                        {csvRows.map((row) => (
                          <tr key={JSON.stringify(row)}>
                            {csvHeaders.map((header) => (
                              <td key={header} className="px-2 py-1 text-secondary">
                                {row[csvHeaders.indexOf(header)] ?? ""}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          <Button
            variant="primary"
            size="sm"
            onClick={() => void startCsvImport()}
            disabled={running}
            aria-label="Start CSV import"
          >
            <Upload className="size-4" aria-hidden="true" /> Start CSV import
          </Button>
        </div>
      )}

      {tab === "jira" && (
        <div role="tabpanel" aria-label="Jira import" className="space-y-4 rounded-md border border-subtle p-4">
          <p className="text-13 text-secondary">Connect a Jira project and import its issues as work items.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="jira-url" className="mb-1 block text-12 font-medium text-primary">
                Jira URL
              </label>
              <input
                id="jira-url"
                aria-label="Jira URL"
                className={inputClass}
                value={jira.site_url}
                onChange={(e) => setJira({ ...jira, site_url: e.target.value })}
                placeholder="https://jira.example.com"
              />
            </div>
            <div>
              <label htmlFor="jira-username" className="mb-1 block text-12 font-medium text-primary">
                Username
              </label>
              <input
                id="jira-username"
                aria-label="Jira username"
                className={inputClass}
                value={jira.email}
                onChange={(e) => setJira({ ...jira, email: e.target.value })}
                placeholder="name@example.com"
              />
            </div>
            <div>
              <label htmlFor="jira-token" className="mb-1 block text-12 font-medium text-primary">
                API token
              </label>
              <input
                id="jira-token"
                aria-label="Jira API token"
                type="password"
                className={inputClass}
                value={jira.api_token}
                onChange={(e) => setJira({ ...jira, api_token: e.target.value })}
                placeholder="Jira API token"
              />
            </div>
            <div>
              <label htmlFor="jira-project-key" className="mb-1 block text-12 font-medium text-primary">
                Project key
              </label>
              <input
                id="jira-project-key"
                aria-label="Jira project key"
                className={inputClass}
                value={jira.project_key}
                onChange={(e) => setJira({ ...jira, project_key: e.target.value })}
                placeholder="Project key"
              />
            </div>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void startJiraImport()}
            disabled={running}
            aria-label="Start Jira import"
          >
            <Upload className="size-4" aria-hidden="true" /> Connect and import
          </Button>
        </div>
      )}

      {tab === "github" && (
        <div role="tabpanel" aria-label="GitHub import" className="space-y-4 rounded-md border border-subtle p-4">
          <p className="text-13 text-secondary">Import GitHub issues and pull requests and link them to work items.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="github-owner" className="mb-1 block text-12 font-medium text-primary">
                Owner
              </label>
              <input
                id="github-owner"
                aria-label="GitHub owner"
                className={inputClass}
                value={github.owner}
                onChange={(e) => setGithub({ ...github, owner: e.target.value })}
                placeholder="owner"
              />
            </div>
            <div>
              <label htmlFor="github-repo" className="mb-1 block text-12 font-medium text-primary">
                Repository
              </label>
              <input
                id="github-repo"
                aria-label="GitHub repository"
                className={inputClass}
                value={github.repo}
                onChange={(e) => setGithub({ ...github, repo: e.target.value })}
                placeholder="repository"
              />
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="github-token" className="mb-1 block text-12 font-medium text-primary">
                Access token
              </label>
              <input
                id="github-token"
                aria-label="GitHub access token"
                type="password"
                className={inputClass}
                value={github.token}
                onChange={(e) => setGithub({ ...github, token: e.target.value })}
                placeholder="GitHub token"
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-13 text-primary">
              <input
                type="checkbox"
                aria-label="Include pull requests"
                checked={github.include_prs}
                onChange={(e) => setGithub({ ...github, include_prs: e.target.checked })}
              />
              Include pull requests
            </label>
            <label className="flex items-center gap-2 text-13 text-primary">
              <input
                type="checkbox"
                aria-label="Include issues"
                checked={github.include_issues}
                onChange={(e) => setGithub({ ...github, include_issues: e.target.checked })}
              />
              Include issues
            </label>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void startGithubImport()}
            disabled={running}
            aria-label="Start GitHub import"
          >
            <Github className="size-4" aria-hidden="true" /> Connect and import
          </Button>
        </div>
      )}

      <div className="rounded-md border border-subtle">
        <div className="border-b border-subtle px-4 py-3">
          <h3 className="text-14 font-medium text-primary">Import history</h3>
          <p className="text-12 text-secondary">Jobs and progress are stored by the backend.</p>
        </div>
        {jobs.length === 0 ? (
          <p className="px-4 py-6 text-center text-13 text-secondary">
            {isLoading ? "Loading imports..." : "No imports yet."}
          </p>
        ) : (
          <div className="divide-y divide-subtle">
            {jobs.map((job) => (
              <div
                key={job.id}
                className="flex flex-wrap items-center justify-between gap-4 px-4 py-3"
                data-testid="import-job"
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-13 font-medium text-primary">{jobDetails(job)}</span>
                    <span className="rounded-sm bg-layer-1 px-1.5 py-0.5 text-11 text-secondary">
                      {TAB_LABELS[job.service]}
                    </span>
                    <span className="text-12 text-secondary">{job.status}</span>
                  </div>
                  <div className="flex max-w-md items-center gap-2">
                    <div
                      role="progressbar"
                      aria-label={`${jobDetails(job)} progress`}
                      aria-valuenow={job.progress}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      className="h-2 flex-1 rounded-full bg-layer-2"
                    >
                      <div className="h-2 rounded-full bg-accent-primary" style={{ width: `${job.progress}%` }} />
                    </div>
                    <span className="text-11 text-tertiary">{job.progress}%</span>
                  </div>
                  <p className="text-12 text-secondary">
                    {job.created_count} created · {job.error_count} failed · {new Date(job.created_at).toLocaleString()}
                  </p>
                </div>
                {job.status === "failed" && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => void downloadErrorLog(job)}
                    aria-label={`Download error log for ${jobDetails(job)}`}
                  >
                    <Download className="size-4" aria-hidden="true" /> Download error log
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
