export type Company = {
  id: string;
  name: string;
  slug: string;
  tagline: string | null;
  description: string | null;
  industry: string | null;
  mission: string | null;
  handbook: string | null;
  created_at: string;
  stats: {
    employees: number;
    projects: number;
    tickets: number;
    tickets_done: number;
    working_now: number;
  };
};

export type Account = { tool: string; username: string; last_used_at: string | null };

export type Employee = {
  id: string;
  company_id: string;
  name: string;
  title: string;
  department: string;
  seniority: string;
  role_key: string;
  persona: string;
  skills: string[];
  toolbelt: string[];
  manager_id: string | null;
  status: string;
  status_note: string | null;
  avatar: string;
  created_at: string;
  accounts: Account[];
};

export type EmployeeDetail = Employee & {
  manager: Employee | null;
  tickets: Ticket[];
  activity: ActivityEvent[];
};

export type Role = {
  key: string;
  title: string;
  department: string;
  avatar: string;
  summary: string;
  skills: string[];
  toolbelt: string[];
  persona: string;
};

export type Project = {
  id: string;
  company_id: string;
  name: string;
  key: string;
  brief: string;
  status: string;
  lead_id: string | null;
  created_at: string;
  counts: Record<string, number>;
};

export type ProjectDetail = Project & { runs: Run[] };

export type Ticket = {
  id: string;
  project_id: string;
  key: string;
  title: string;
  description: string;
  type: string;
  status: TicketStatus;
  priority: string;
  assignee_id: string | null;
  reporter_id: string | null;
  role_hint: string | null;
  acceptance_criteria: string[];
  order: number;
  result: string | null;
  created_at: string;
  updated_at: string;
  comments?: TicketComment[];
  steps?: RunStep[];
};

export type TicketComment = {
  id: string;
  author_id: string | null;
  author_label: string;
  body: string;
  created_at: string;
};

export type TicketStatus =
  | "backlog"
  | "todo"
  | "in_progress"
  | "in_review"
  | "done"
  | "blocked";

export type Run = {
  id: string;
  company_id: string;
  project_id: string;
  brief: string;
  status: string;
  phase: string;
  error: string | null;
  stats: Record<string, number>;
  created_at: string;
  steps?: RunStep[];
};

export type RunStep = {
  id: string;
  run_id: string;
  employee_id: string | null;
  ticket_id: string | null;
  kind: string;
  reasoning: string;
  output: string;
  tool_calls: { name: string; arguments: Record<string, unknown>; result: string }[];
  status: string;
  created_at: string;
};

export type ActivityEvent = {
  seq: number;
  company_id: string;
  project_id: string | null;
  run_id: string | null;
  employee_id: string | null;
  actor: string;
  kind: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Document = {
  id: string;
  company_id: string;
  project_id: string | null;
  space: string;
  title: string;
  slug: string;
  parent_id: string | null;
  author_id: string | null;
  version: number;
  body?: string;
  created_at: string;
  updated_at: string;
  history?: { version: number; author_label: string; created_at: string }[];
};

export type Channel = {
  id: string;
  company_id: string;
  project_id: string | null;
  name: string;
  purpose: string;
  kind: string;
};

export type ChatMessage = {
  id: string;
  channel_id: string;
  author_id: string | null;
  author_label: string;
  body: string;
  mentions: string[];
  created_at: string;
};

export type FileEntry = { path: string; name: string; type: "file" | "dir"; size: number };
export type Commit = { sha: string; author: string; when: string; subject: string };
