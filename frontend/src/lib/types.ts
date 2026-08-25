/** Shapes the platform API actually returns. Kept in step with api/serializers.py. */

export type Verdict = "pass" | "fail" | "pending" | "error" | "skipped";
export type WorkStatus = "backlog" | "todo" | "in_progress" | "in_review" | "done" | "blocked";
export type CheckKind = "command" | "schema" | "assertion" | "citation" | "rubric" | "human";

export interface Company {
  id: string;
  name: string;
  slug: string;
  tagline: string;
  description: string;
  industry: string;
  mission: string;
  handbook: string;
  pack_key: string;
  departments: string[];
  work_item_kinds: string[];
  settings: Record<string, unknown>;
  halted: boolean;
  halt_reason: string | null;
  created_at: string | null;
  stats: Record<string, number>;
}

export interface Employee {
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
  capabilities: string[];
  model_policy: Record<string, string>;
  model: string;
  autonomy_level: string;
  budget_daily_micros: number | null;
  api_enabled: boolean;
  created_at: string | null;
  accounts: { tool: string; username: string; last_used_at: string | null }[];
}

export interface AgentCard {
  id: string;
  name: string;
  title: string;
  company: { id: string; name: string; slug: string; industry: string; pack: string };
  department: string;
  role_key: string;
  persona: string;
  skills: string[];
  capabilities: string[];
  tools: { name: string; group: string; description: string; read_only: boolean }[];
  models: Record<string, string>;
  autonomy_level: string;
  api_enabled: boolean;
  state: string;
  endpoints: Record<string, string>;
}

export interface Project {
  id: string;
  company_id: string;
  name: string;
  key: string;
  brief: string;
  status: string;
  lead_id: string | null;
  verify_command: string;
  preview: Record<string, unknown>;
  created_at: string | null;
  counts: Record<string, number>;
}

export interface WorkItem {
  id: string;
  project_id: string;
  key: string;
  title: string;
  description: string;
  kind: string;
  type: string;
  status: WorkStatus;
  priority: string;
  assignee_id: string | null;
  reporter_id: string | null;
  role_hint: string;
  acceptance_criteria: string[];
  capability_hint: string | null;
  depends_on: string[];
  deliverable_spec: Record<string, unknown>;
  approval_required: boolean;
  blocked_reason: string | null;
  rework_count: number;
  closed_at: string | null;
  order: number;
  result: string;
  created_at: string | null;
  updated_at: string | null;
  comments?: WorkItemComment[];
}

export interface WorkItemComment {
  id: string;
  author_id: string | null;
  author_label: string;
  body: string;
  created_at: string | null;
}

export interface Artifact {
  id: string;
  project_id: string | null;
  work_item_id: string | null;
  kind: string;
  name: string;
  title: string;
  storage: string;
  locator: string;
  version: number;
  content_hash: string;
  size_bytes: number;
  produced_by: string | null;
  superseded_by: string | null;
  meta: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  content?: string;
}

export interface Check {
  id: string;
  project_id: string | null;
  work_item_id: string | null;
  artifact_kind: string | null;
  key: string;
  name: string;
  kind: CheckKind;
  spec: Record<string, unknown>;
  required: boolean;
  enabled: boolean;
  position: number;
  created_by: string;
}

export interface CheckResult {
  id: string;
  check_id: string | null;
  check_key: string;
  check_kind: CheckKind;
  project_id: string | null;
  work_item_id: string | null;
  artifact_id: string | null;
  run_id: string | null;
  status: Verdict;
  score: number | null;
  detail: string;
  evidence: Record<string, unknown>;
  duration_ms: number;
  created_at: string | null;
}

export interface Memory {
  id: string;
  employee_id: string | null;
  kind: string;
  scope: string;
  title: string;
  body: string;
  outcome: string | null;
  confidence: number;
  uses: number;
  used_by: string[];
  tags: string[];
  source_kind: string | null;
  source_id: string | null;
  superseded_by: string | null;
  archived_at: string | null;
  has_embedding: boolean;
  last_used_at: string | null;
  created_by: string;
  created_at: string | null;
  score: number | null;
  similarity: number | null;
}

export interface MemoryBlock {
  id: string;
  label: string;
  content: string;
  char_limit: number;
  chars: number;
  pinned: boolean;
  version: number;
  updated_by: string;
  updated_at: string | null;
}

export interface AgentTask {
  id: string;
  employee_id: string;
  company_id: string;
  kind: string;
  source: string;
  status: string;
  priority: number;
  work_item_id: string | null;
  created_by: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  attempts: number;
  request?: Record<string, unknown>;
  result?: Record<string, unknown>;
}

export interface AgentToken {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_by: string;
  created_at: string | null;
}

export interface MintedToken extends AgentToken {
  token: string;
  note: string;
  example: string;
}

export interface Approval {
  id: string;
  company_id: string;
  project_id: string | null;
  work_item_id: string | null;
  subject_kind: string;
  subject_id: string | null;
  requested_by: string | null;
  requested_label: string;
  title: string;
  reason: string;
  capability: string | null;
  status: string;
  decided_by: string | null;
  decided_at: string | null;
  note: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface AgentMessage {
  id: string;
  company_id: string;
  kind: string;
  from_id: string | null;
  from_label: string;
  to_id: string;
  work_item_id: string | null;
  thread_id: string;
  hops: number;
  subject: string;
  body: string;
  read_at: string | null;
  handled_at: string | null;
  created_at: string | null;
}

export interface LedgerEntry {
  seq: number;
  height: number;
  company_id: string;
  project_id: string | null;
  kind: string;
  actor_id: string | null;
  actor_label: string;
  subject_kind: string | null;
  subject_id: string | null;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
  at: string | null;
}

export interface ChainVerdict {
  intact: boolean;
  entries: number;
  problems: { height: number; hash: string; problem: string; recomputed?: string }[];
  head?: string | null;
}

export interface ProofReport {
  project: { id: string; key: string; name: string };
  checked_at: string;
  chain: ChainVerdict;
  artifacts: {
    total: number;
    intact: number;
    changed: { id: string; name: string; state: string }[];
    missing: { id: string; name: string; state: string }[];
    not_in_ledger: string[];
  };
  checks: {
    replayed: ReplayedCheck[];
    skipped: { check_key: string; kind?: string; then: string; reason: string }[];
    disagreements: ReplayedCheck[];
  };
  proved: boolean;
  /** False when nothing has ever been checked — distinct from a failed proof. */
  has_evidence: boolean;
  note: string;
}

export interface ReplayedCheck {
  check_key: string;
  kind: string;
  work_item: string | null;
  artifact: string | null;
  artifact_hash: string | null;
  then: string;
  now: string;
  recorded_at: string | null;
  detail: string;
}

export interface ActivityEvent {
  seq: number;
  company_id: string;
  project_id: string | null;
  employee_id: string | null;
  actor: string;
  kind: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface RunStep {
  id: string;
  run_id: string | null;
  employee_id: string | null;
  work_item_id: string | null;
  kind: string;
  reasoning: string;
  output: string;
  tool_calls: { name: string; arguments?: Record<string, unknown>; ok?: boolean }[];
  status: string;
  created_at: string | null;
}

export interface ToolCall {
  id: string;
  employee_id: string | null;
  employee_label: string;
  tool: string;
  group: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  blocked_reason: string | null;
  result_preview: string;
  duration_ms: number;
  created_at: string | null;
}

export interface Source {
  id: string;
  url: string;
  title: string;
  content_hash: string;
  fetched_by: string | null;
  created_at: string | null;
}

export interface Role {
  key: string;
  title: string;
  department: string;
  avatar: string;
  summary: string;
  skills: string[];
  toolbelt: string[];
  capabilities: string[];
  manages: boolean;
  persona?: string;
  /** Absent from `/packs`, which serves pack definitions rather than DB rows. */
  position?: number;
}

export interface Pack {
  key: string;
  name: string;
  description: string;
  departments: string[];
  work_item_kinds: string[];
  roles: Role[];
  artifact_kinds: {
    key: string;
    name: string;
    storage: string;
    renderer: string;
    default_checks: string[];
    description: string;
  }[];
  checks: Check[];
}

export interface Meeting {
  id: string;
  company_id: string;
  project_id: string | null;
  kind: string;
  title: string;
  agenda: string;
  attendee_ids: string[];
  chair_id: string | null;
  status: string;
  outcome: Record<string, unknown>;
  transcript: { speaker: string; body: string }[];
  created_at: string | null;
  held_at: string | null;
}

export interface Usage {
  employee_id?: string;
  today: UsageWindow;
  month: UsageWindow;
  all_time: UsageWindow;
  budget_daily_micros?: number | null;
  over_budget?: boolean;
  formatted: Record<string, string>;
  note: string;
}

export interface UsageWindow {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_micros: number;
  /** Preformatted by the API, which owns the rate table. */
  display?: string;
}

export interface Performance {
  employee_id?: string;
  name?: string;
  items_considered: number;
  first_try_pass_rate: number | null;
  rework_rate: number | null;
  median_hours_to_done: number | null;
  tokens_per_artifact: number | null;
  note: string;
}

export interface Document {
  id: string;
  company_id: string;
  space: string;
  title: string;
  slug: string;
  body?: string;
  excerpt: string;
  author_id: string | null;
  updated_at: string | null;
}

export interface Channel {
  id: string;
  name: string;
  purpose: string;
  unread: number;
}

export interface ChatMessage {
  id: string;
  channel_id: string;
  author_id: string | null;
  author_label: string;
  body: string;
  created_at: string | null;
}

export interface FileEntry {
  path: string;
  name: string;
  is_dir: boolean;
  size: number;
}

export interface Commit {
  sha: string;
  message: string;
  author: string;
  at: string;
}

export interface PreviewState {
  status: string;
  url: string | null;
  package: string | null;
  log: string;
  error: string | null;
}

export interface Connections {
  connections: {
    id: string;
    tool: string;
    provider: string;
    base_url: string | null;
    config: Record<string, unknown>;
    has_secret: boolean;
    status: string;
  }[];
  mcp_servers: {
    id: string;
    name: string;
    url: string;
    status: string;
    enabled: boolean;
    last_error: string | null;
    tools: string[];
    last_checked_at: string | null;
  }[];
  egress: { open: boolean; allow: string[]; default: string[] };
}

export interface OpsSnapshot {
  halted: boolean;
  halt_reason: string | null;
  autonomous: boolean;
  clock: {
    running: boolean;
    ticks: number;
    dispatched: number;
    reclaimed: number;
    last_tick: string | null;
    last_error: string | null;
    tick_seconds: number;
  };
  /** The most recent tasks, newest first — not a count per status. */
  tasks: AgentTask[];
  in_flight: number;
  checks: CheckResult[];
  usage: { today: UsageWindow; month: UsageWindow; all_time: UsageWindow };
  by_employee: {
    employee_id: string;
    name: string;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    cost_micros: number;
    display: string;
  }[];
  cost_note: string;
}
