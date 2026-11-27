export interface StateRecord {
  id: string;
  name: string;
  group?: string;
}

export interface TypeRecord {
  id: string;
  key: string;
  name: string;
}

export interface WorkflowRecord {
  id: string;
  issueTypeId: string;
  name: string;
}

export interface ProjectCatalog {
  workspaceSlug: string;
  projectId: string;
  projectName: string;
  identifier: string;
  states: Record<string, StateRecord>;
  types: Record<string, TypeRecord>;
  workflows: Record<string, WorkflowRecord>;
}
