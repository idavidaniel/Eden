import type {
  ActivityEvent,
  Channel,
  ChatMessage,
  Commit,
  Company,
  Document,
  Employee,
  EmployeeDetail,
  FileEntry,
  PreviewState,
  Project,
  ProjectDetail,
  Role,
  Run,
  Ticket,
} from "./types";

const BASE = "/api/backend";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
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
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep the status-based message */
    }
    throw new ApiError(detail, response.status);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
const del = (path: string) => request<void>(path, { method: "DELETE" });

export const api = {
  health: () => request<{ status: string; model: string; llm_configured: boolean }>("/health"),
  roles: () => request<Role[]>("/roles"),

  companies: {
    list: () => request<Company[]>("/companies"),
    get: (id: string) => request<Company>(`/companies/${id}`),
    create: (body: Partial<Company> & { name: string; starting_team?: string[] }) =>
      post<Company>("/companies", body),
    update: (id: string, body: Partial<Company>) => patch<Company>(`/companies/${id}`, body),
    remove: (id: string) => del(`/companies/${id}`),
    activity: (id: string, params: { cursor?: number; limit?: number } = {}) =>
      request<{ events: ActivityEvent[]; cursor: number }>(
        `/companies/${id}/activity?cursor=${params.cursor ?? 0}&limit=${params.limit ?? 60}`,
      ),
  },

  employees: {
    list: (companyId: string) => request<Employee[]>(`/companies/${companyId}/employees`),
    get: (id: string) => request<EmployeeDetail>(`/employees/${id}`),
    hire: (companyId: string, body: Record<string, unknown>) =>
      post<Employee>(`/companies/${companyId}/employees`, body),
    update: (id: string, body: Record<string, unknown>) => patch<Employee>(`/employees/${id}`, body),
    remove: (id: string) => del(`/employees/${id}`),
    credentials: (id: string) =>
      request<{ accounts: { tool: string; username: string; password: string; token: string }[] }>(
        `/employees/${id}/credentials`,
      ),
    rotate: (id: string, tool: string) =>
      post<{ tool: string; username: string; password: string; token: string }>(
        `/employees/${id}/credentials/${tool}/rotate`,
      ),
  },

  projects: {
    list: (companyId: string) => request<Project[]>(`/companies/${companyId}/projects`),
    get: (id: string) => request<ProjectDetail>(`/projects/${id}`),
    update: (id: string, body: Partial<Project>) => patch<Project>(`/projects/${id}`, body),
    create: (companyId: string, body: { name: string; brief: string; key?: string }) =>
      post<Project>(`/companies/${companyId}/projects`, body),
    tickets: (id: string) => request<Ticket[]>(`/projects/${id}/tickets`),
    createTicket: (id: string, body: Record<string, unknown>) =>
      post<Ticket>(`/projects/${id}/tickets`, body),
    startRun: (id: string, brief?: string) => post<Run>(`/projects/${id}/runs`, { brief }),
    packages: (id: string) => request<{ packages: string[] }>(`/projects/${id}/packages`),
    preview: (id: string) => request<PreviewState>(`/projects/${id}/preview`),
    buildPreview: (id: string, pkg: string) =>
      post<PreviewState>(`/projects/${id}/preview`, { package: pkg }),
    autofix: (id: string, body: { command?: string; cwd?: string; max_attempts?: number } = {}) =>
      post<{ status: string; command: string }>(`/projects/${id}/autofix`, body),
  },

  tickets: {
    get: (id: string) => request<Ticket>(`/tickets/${id}`),
    update: (id: string, body: Record<string, unknown>) => patch<Ticket>(`/tickets/${id}`, body),
    comment: (id: string, body: string) => post(`/tickets/${id}/comments`, { body }),
    remove: (id: string) => del(`/tickets/${id}`),
  },

  runs: {
    get: (id: string) => request<Run>(`/runs/${id}`),
    control: (id: string, action: "pause" | "resume" | "cancel") => post<Run>(`/runs/${id}/${action}`),
  },

  wiki: {
    list: (companyId: string) =>
      request<{ spaces: string[]; documents: Document[] }>(`/companies/${companyId}/documents`),
    get: (id: string) => request<Document>(`/documents/${id}`),
    create: (companyId: string, body: { title: string; body: string; space?: string }) =>
      post<Document>(`/companies/${companyId}/documents`, body),
    update: (id: string, body: Partial<Document>) => patch<Document>(`/documents/${id}`, body),
    remove: (id: string) => del(`/documents/${id}`),
  },

  chat: {
    channels: (companyId: string) => request<Channel[]>(`/companies/${companyId}/channels`),
    messages: (channelId: string) => request<ChatMessage[]>(`/channels/${channelId}/messages`),
    send: (channelId: string, body: string, replyFrom?: string) =>
      post<ChatMessage & { replying: Employee | null }>(`/channels/${channelId}/messages`, {
        body,
        reply_from: replyFrom,
      }),
  },

  workspace: {
    files: (projectId: string) =>
      request<{ root: string; entries: FileEntry[] }>(`/projects/${projectId}/files`),
    file: (projectId: string, path: string) =>
      request<{ path: string; content: string }>(
        `/projects/${projectId}/file?path=${encodeURIComponent(path)}`,
      ),
    save: (projectId: string, path: string, content: string, commitMessage?: string) =>
      put<{ path: string; bytes: number }>(`/projects/${projectId}/file`, {
        path,
        content,
        commit_message: commitMessage,
      }),
    commits: (projectId: string) => request<Commit[]>(`/projects/${projectId}/commits`),
    commit: (projectId: string, sha: string) =>
      request<{ sha: string; diff: string }>(`/projects/${projectId}/commits/${sha}`),
  },
};

/** Subscribe to the company's live activity stream. Returns an unsubscribe fn. */
export function subscribeToActivity(
  companyId: string,
  cursor: number,
  onEvent: (event: ActivityEvent) => void,
): () => void {
  const source = new EventSource(`${BASE}/companies/${companyId}/stream?cursor=${cursor}`);
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as ActivityEvent);
    } catch {
      /* ignore keep-alives and malformed frames */
    }
  };
  return () => source.close();
}
