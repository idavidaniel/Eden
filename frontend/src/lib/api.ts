import type {
  ActivityEvent,
  AgentCard,
  AgentMessage,
  AgentTask,
  AgentToken,
  Approval,
  Artifact,
  ChainVerdict,
  Channel,
  ChatMessage,
  Check,
  CheckResult,
  Commit,
  Company,
  Connections,
  Document,
  Employee,
  FileEntry,
  LedgerEntry,
  Meeting,
  Memory,
  MemoryBlock,
  MintedToken,
  OpsSnapshot,
  Pack,
  Performance,
  PreviewState,
  ProofReport,
  Project,
  Role,
  Source,
  ToolCall,
  Usage,
  WorkItem,
} from "./types";

export const BASE = "/api/backend";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail =
        typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep the status-based message */
    }
    throw new ApiError(detail, response.status);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
const del = (path: string) => request<void>(path, { method: "DELETE" });

const query = (params: Record<string, string | number | boolean | undefined>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
};

export const api = {
  health: () =>
    get<{
      status: string;
      model: string;
      llm_configured: boolean;
      embeddings: { available: boolean; reason?: string };
      clock: OpsSnapshot["clock"];
      runners: Record<string, unknown>;
    }>("/health"),

  packs: () => get<{ packs: Pack[] }>("/packs"),

  companies: {
    list: () => get<Company[]>("/companies"),
    get: (id: string) => get<Company>(`/companies/${id}`),
    create: (body: Record<string, unknown>) => post<Company>("/companies", body),
    update: (id: string, body: Partial<Company>) => patch<Company>(`/companies/${id}`, body),
    remove: (id: string) => del(`/companies/${id}`),
    activity: (id: string, cursor = 0, limit = 60) =>
      get<{ events: ActivityEvent[]; cursor: number }>(
        `/companies/${id}/activity${query({ cursor, limit })}`,
      ),
    pack: (id: string) => get<Pack>(`/companies/${id}/pack`),
    reapplyPack: (id: string, packKey?: string) =>
      post<{ pack: string; roles: number; checks: number }>(
        `/companies/${id}/pack/reapply${query({ pack_key: packKey })}`,
      ),
    ops: (id: string) => get<OpsSnapshot>(`/companies/${id}/ops`),
    halt: (id: string, halted: boolean, reason = "") =>
      post<Company>(`/companies/${id}/halt`, { halted, reason }),
    autonomy: (id: string, enabled: boolean) =>
      post<{ autonomous: boolean }>(`/companies/${id}/autonomy${query({ enabled })}`),
    inbox: (id: string) =>
      get<{ approvals: Approval[]; blocked_items: WorkItem[]; count: number }>(
        `/companies/${id}/inbox`,
      ),
    messages: (id: string, limit = 100) =>
      get<AgentMessage[]>(`/companies/${id}/messages${query({ limit })}`),
    toolCalls: (id: string, limit = 100) =>
      get<ToolCall[]>(`/companies/${id}/tool-calls${query({ limit })}`),
    sources: (id: string, limit = 100) => get<Source[]>(`/companies/${id}/sources${query({ limit })}`),
    performance: (id: string) => get<{ employees: Performance[] }>(`/companies/${id}/performance`),
    artifacts: (id: string, kind?: string) =>
      get<{ artifacts: Artifact[]; by_kind: Record<string, number> }>(
        `/companies/${id}/artifacts${query({ kind })}`,
      ),
    ledger: (id: string, limit = 100) =>
      get<{ entries: LedgerEntry[]; head: string | null }>(`/companies/${id}/ledger${query({ limit })}`),
    verifyLedger: (id: string) => post<ChainVerdict>(`/companies/${id}/ledger/verify`),
    meetings: (id: string) => get<Meeting[]>(`/companies/${id}/meetings`),
    hold: (id: string, body: Record<string, unknown>) => post<Meeting>(`/companies/${id}/meetings`, body),
    connections: (id: string) => get<Connections>(`/companies/${id}/connections`),
    saveConnection: (id: string, body: Record<string, unknown>) =>
      put<{ tool: string; provider: string; status: string; test: Record<string, unknown> }>(
        `/companies/${id}/connections`,
        body,
      ),
    addMcpServer: (id: string, body: Record<string, unknown>) =>
      post<{ id: string; name: string; status: string; tools: string[]; last_error: string | null }>(
        `/companies/${id}/mcp-servers`,
        body,
      ),
    egress: (id: string, body: { allow?: string[]; open?: boolean }) =>
      put<{ open: boolean; allow: string[]; warning: string | null }>(
        `/companies/${id}/egress`,
        body,
      ),
  },

  employees: {
    list: (companyId: string) => get<Employee[]>(`/companies/${companyId}/employees`),
    get: (id: string) => get<Employee>(`/employees/${id}`),
    hire: (companyId: string, body: Record<string, unknown>) =>
      post<Employee>(`/companies/${companyId}/employees`, body),
    update: (id: string, body: Record<string, unknown>) => patch<Employee>(`/employees/${id}`, body),
    remove: (id: string) => del(`/employees/${id}`),
    performance: (id: string) => get<Performance>(`/employees/${id}/performance`),
    coach: (id: string) =>
      post<{ proposals: { field: string; from: string; to: string; why: string }[] }>(
        `/employees/${id}/coach`,
      ),
  },

  /** Every employee is addressable here, with or without a token. */
  agents: {
    card: (id: string) => get<AgentCard>(`/agents/${id}/card`),
    prompt: (id: string, projectId?: string) =>
      get<{ system_prompt: string }>(`/agents/${id}/prompt${query({ project_id: projectId })}`),
    message: (id: string, body: Record<string, unknown>) =>
      post<{
        task_id: string;
        reply: string;
        status: string;
        tool_calls: { name: string; ok: boolean }[];
        context: Record<string, number | Record<string, number>>;
        step_id: string;
      }>(`/agents/${id}/messages`, body),
    tasks: (id: string) => get<AgentTask[]>(`/agents/${id}/tasks`),
    task: (id: string, taskId: string) => get<AgentTask>(`/agents/${id}/tasks/${taskId}`),
    enqueue: (id: string, body: Record<string, unknown>) => post<AgentTask>(`/agents/${id}/tasks`, body),
    cancel: (id: string, taskId: string) => post<AgentTask>(`/agents/${id}/tasks/${taskId}/cancel`),
    memory: (id: string, search?: string) =>
      get<{
        blocks: MemoryBlock[];
        memories: Memory[];
        retrieval_mode: string;
        counts: Record<string, number>;
      }>(`/agents/${id}/memory${query({ query: search })}`),
    setBlock: (id: string, label: string, body: { content: string; pinned?: boolean }) =>
      put<MemoryBlock>(`/agents/${id}/memory/blocks/${label}`, body),
    teach: (id: string, body: Record<string, unknown>) => post<Memory>(`/agents/${id}/memory`, body),
    forget: (id: string, memoryId: string) => del(`/agents/${id}/memory/${memoryId}`),
    promote: (id: string, memoryId: string) => post<Memory>(`/agents/${id}/memory/${memoryId}/promote`),
    tokens: (id: string) => get<AgentToken[]>(`/agents/${id}/tokens`),
    mint: (id: string, body: Record<string, unknown>) => post<MintedToken>(`/agents/${id}/tokens`, body),
    revoke: (id: string, tokenId: string) => del(`/agents/${id}/tokens/${tokenId}`),
    usage: (id: string) => get<Usage>(`/agents/${id}/usage`),
    configure: (id: string, body: Record<string, unknown>) =>
      patch<Employee & { notes: string[] }>(`/agents/${id}/config`, body),
  },

  projects: {
    list: (companyId: string) => get<Project[]>(`/companies/${companyId}/projects`),
    get: (id: string) => get<Project & { work_items: WorkItem[] }>(`/projects/${id}`),
    create: (companyId: string, body: Record<string, unknown>) =>
      post<Project>(`/companies/${companyId}/projects`, body),
    update: (id: string, body: Partial<Project>) => patch<Project>(`/projects/${id}`, body),
    workItems: (id: string) => get<WorkItem[]>(`/projects/${id}/work-items`),
    createWorkItem: (id: string, body: Record<string, unknown>) =>
      post<WorkItem>(`/projects/${id}/work-items`, body),
    start: (id: string, brief?: string) => post<{ id: string }>(`/projects/${id}/runs`, { brief }),
    artifacts: (id: string) => get<Artifact[]>(`/projects/${id}/artifacts`),
    workRecord: (id: string) => get<Record<string, unknown>>(`/projects/${id}/work-record`),
    verify: (id: string) => post<ProofReport>(`/projects/${id}/ledger/verify`),
    packages: (id: string) => get<{ packages: string[] }>(`/projects/${id}/packages`),
    preview: (id: string) => get<PreviewState>(`/projects/${id}/preview`),
    buildPreview: (id: string, pkg: string) =>
      post<PreviewState>(`/projects/${id}/preview`, { package: pkg }),
    autofix: (id: string, body: Record<string, unknown> = {}) =>
      post<{ status: string; command: string }>(`/projects/${id}/autofix`, body),
  },

  workItems: {
    get: (id: string) => get<WorkItem>(`/work-items/${id}`),
    update: (id: string, body: Record<string, unknown>) => patch<WorkItem>(`/work-items/${id}`, body),
    comment: (id: string, body: string) => post(`/work-items/${id}/comments`, { body }),
    remove: (id: string) => del(`/work-items/${id}`),
    runChecks: (id: string) =>
      post<{ results: CheckResult[]; verdict: Record<string, unknown> }>(
        `/work-items/${id}/checks/run`,
      ),
    checks: (id: string) =>
      get<{
        checks: Check[];
        results: CheckResult[];
        verdict: Record<string, unknown> | null;
        artifacts: Artifact[];
      }>(`/work-items/${id}/checks`),
  },

  artifacts: {
    get: (id: string) =>
      get<
        Artifact & {
          checks: CheckResult[];
          versions: Artifact[];
          integrity: { state: string; detail: string; expected?: string; found?: string };
        }
      >(`/artifacts/${id}`),
  },

  approvals: {
    decide: (id: string, approved: boolean, note = "") =>
      post<Approval>(`/approvals/${id}/decide`, { approved, note }),
  },

  clock: {
    tick: () => post<{ reclaimed: number; created: number; dispatched: number }>("/clock/tick"),
  },

  wiki: {
    list: (companyId: string) =>
      get<{ spaces: string[]; documents: Document[] }>(`/companies/${companyId}/documents`),
    get: (id: string) => get<Document>(`/documents/${id}`),
    create: (companyId: string, body: Record<string, unknown>) =>
      post<Document>(`/companies/${companyId}/documents`, body),
    update: (id: string, body: Partial<Document>) => patch<Document>(`/documents/${id}`, body),
    remove: (id: string) => del(`/documents/${id}`),
  },

  chat: {
    channels: (companyId: string) => get<Channel[]>(`/companies/${companyId}/channels`),
    messages: (channelId: string) => get<ChatMessage[]>(`/channels/${channelId}/messages`),
    send: (channelId: string, body: string, replyFrom?: string) =>
      post<ChatMessage>(`/channels/${channelId}/messages`, { body, reply_from: replyFrom }),
  },

  workspace: {
    files: (projectId: string) =>
      get<{ root: string; entries: FileEntry[] }>(`/projects/${projectId}/files`),
    file: (projectId: string, path: string) =>
      get<{ path: string; content: string }>(
        `/projects/${projectId}/file${query({ path })}`,
      ),
    save: (projectId: string, path: string, content: string, commitMessage?: string) =>
      put<{ path: string; bytes: number }>(`/projects/${projectId}/file`, {
        path,
        content,
        commit_message: commitMessage,
      }),
    commits: (projectId: string) => get<Commit[]>(`/projects/${projectId}/commits`),
    commit: (projectId: string, sha: string) =>
      get<{ sha: string; diff: string }>(`/projects/${projectId}/commits/${sha}`),
  },

  connections: {
    catalogue: () =>
      get<{ providers: Record<string, unknown>[]; tools: string[]; runners: Record<string, unknown> }>(
        "/connections/catalogue",
      ),
    test: (id: string) => post<Record<string, unknown>>(`/connections/${id}/test`),
    remove: (id: string) => del(`/connections/${id}`),
    refreshMcp: (id: string) => post<Record<string, unknown>>(`/mcp-servers/${id}/refresh`),
    removeMcp: (id: string) => del(`/mcp-servers/${id}`),
  },

  roles: () => get<Role[]>("/roles"),
};
