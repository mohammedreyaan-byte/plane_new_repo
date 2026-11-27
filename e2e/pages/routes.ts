import { ProjectCatalog } from "../support/types";

export function projectPath(catalog: ProjectCatalog, suffix = "issues"): string {
  return `/${catalog.workspaceSlug}/projects/${catalog.projectId}/${suffix.replace(/^\//, "")}`;
}

export function settingsPath(catalog: ProjectCatalog, suffix = ""): string {
  const base = `/${catalog.workspaceSlug}/settings`;
  return suffix ? `${base}/${suffix.replace(/^\//, "")}` : base;
}

export function projectSettingsPath(catalog: ProjectCatalog, suffix: string): string {
  return `/${catalog.workspaceSlug}/settings/projects/${catalog.projectId}/${suffix.replace(/^\//, "")}`;
}

export function issuePath(catalog: ProjectCatalog, issueId: string): string {
  return projectPath(catalog, `issues/${issueId}`);
}
