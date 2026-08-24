"use client";

import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Plug, Server, ShieldAlert, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { keys } from "@/lib/hooks";
import {
  Badge,
  Button,
  Dialog,
  Empty,
  ErrorNote,
  Field,
  Input,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Skeleton,
  Textarea,
  Toggle,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function Connections({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const [connecting, setConnecting] = useState(false);
  const [addingServer, setAddingServer] = useState(false);

  const connections = useQuery({
    queryKey: keys.connections(companyId),
    queryFn: () => api.companies.connections(companyId),
  });

  if (connections.error) {
    return <ErrorNote error={connections.error} retry={() => connections.refetch()} />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Connections"
        hint="What this company's agents can reach, and where their writes actually land."
      />

      {connections.isLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <Egress companyId={companyId} egress={connections.data!.egress} />

          <Panel>
            <PanelHeader
              icon={<Plug size={14} />}
              title="Where work lands"
              hint="Connect a tracker and create_ticket starts creating real issues. Same tool, same prompt."
              action={
                <Button size="sm" onClick={() => setConnecting(true)}>
                  Connect something
                </Button>
              }
            />
            {connections.data!.connections.length ? (
              <ul className="divide-y divide-line">
                {connections.data!.connections.map((connection) => (
                  <li key={connection.id} className="flex items-center gap-3 px-4 py-3">
                    <Badge tone={connection.status === "connected" ? "pass" : "fail"}>
                      {connection.status}
                    </Badge>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm text-ink">
                        {connection.tool} → {connection.provider}
                      </span>
                      {connection.base_url ? (
                        <Mono className="block truncate text-xs text-faint">
                          {connection.base_url}
                        </Mono>
                      ) : null}
                    </span>
                    {connection.has_secret ? <Badge>credential set</Badge> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <Empty title="Everything stays in Eden">
                Work items, documents and chat live here. Connect GitHub or Jira and the tracker
                tools write there instead.
              </Empty>
            )}
          </Panel>

          <Panel>
            <PanelHeader
              icon={<Server size={14} />}
              title="MCP servers"
              hint="Their tools appear alongside the built-in ones, prefixed by server name."
              action={
                <Button size="sm" onClick={() => setAddingServer(true)}>
                  Add a server
                </Button>
              }
            />
            {connections.data!.mcp_servers.length ? (
              <ul className="divide-y divide-line">
                {connections.data!.mcp_servers.map((server) => (
                  <ServerRow key={server.id} companyId={companyId} server={server} />
                ))}
              </ul>
            ) : (
              <Empty title="No external servers">
                Anything an MCP server returns is treated as untrusted text, exactly like a web
                page.
              </Empty>
            )}
          </Panel>
        </>
      )}

      <ConnectDialog
        companyId={companyId}
        open={connecting}
        onClose={() => setConnecting(false)}
      />
      <ServerDialog
        companyId={companyId}
        open={addingServer}
        onClose={() => setAddingServer(false)}
      />
    </div>
  );
}

function Egress({
  companyId,
  egress,
}: {
  companyId: string;
  egress: { open: boolean; allow: string[]; default: string[] };
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [allow, setAllow] = useState(egress.allow.join("\n"));

  const save = useMutation({
    mutationFn: (body: { allow?: string[]; open?: boolean }) =>
      api.companies.egress(companyId, body),
    onSuccess: (result) => {
      client.invalidateQueries({ queryKey: keys.connections(companyId) });
      toast.show(result.warning ? "error" : "ok", result.warning ?? "Saved.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Panel>
      <PanelHeader
        icon={<Globe size={14} />}
        title="What agents may fetch"
        hint="Default-deny. Local and private addresses are never reachable, whatever is set here."
      />
      <div className="space-y-4 p-4">
        <Toggle
          checked={egress.open}
          onChange={(next) => save.mutate({ open: next })}
          label="Let them fetch anything"
          hint="An agent can then read a page written to manipulate it. Fetched text is still data and still cannot trigger an action in the same turn, but the allow-list is the stronger guard."
        />

        {egress.open ? (
          <p className="flex items-start gap-2 rounded-md border border-line bg-pending-wash px-3 py-2 text-xs text-pending">
            <ShieldAlert size={14} className="mt-0.5 shrink-0" />
            Open egress is on. Prefer naming the hosts the work actually needs.
          </p>
        ) : null}

        <Field
          label="Allowed hosts"
          hint="One per line. A leading *. matches subdomains — *.readthedocs.io allows any of them."
        >
          <Textarea
            value={allow}
            onChange={(event) => setAllow(event.target.value)}
            className="min-h-28 font-mono text-xs"
            placeholder={egress.default.join("\n")}
          />
        </Field>

        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => setAllow(egress.default.join("\n"))}
            className="text-xs text-accent hover:underline"
          >
            Use the default list
          </button>
          <Button
            size="sm"
            variant="primary"
            busy={save.isPending}
            onClick={() =>
              save.mutate({ allow: allow.split("\n").map((host) => host.trim()).filter(Boolean) })
            }
          >
            Save hosts
          </Button>
        </div>
      </div>
    </Panel>
  );
}

function ServerRow({
  companyId,
  server,
}: {
  companyId: string;
  server: {
    id: string;
    name: string;
    url: string;
    status: string;
    tools: string[];
    last_error: string | null;
    last_checked_at: string | null;
  };
}) {
  const client = useQueryClient();
  const toast = useToast();
  const invalidate = () => client.invalidateQueries({ queryKey: keys.connections(companyId) });

  const refresh = useMutation({
    mutationFn: () => api.connections.refreshMcp(server.id),
    onSuccess: invalidate,
    onError: (error: Error) => toast.show("error", error.message),
  });
  const remove = useMutation({
    mutationFn: () => api.connections.removeMcp(server.id),
    onSuccess: invalidate,
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <li className="px-4 py-3">
      <div className="flex items-center gap-3">
        <Badge tone={server.status === "connected" ? "pass" : "fail"}>{server.status}</Badge>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-ink">{server.name}</span>
          <Mono className="block truncate text-xs text-faint">{server.url}</Mono>
        </span>
        <span className="text-xs text-faint">{timeAgo(server.last_checked_at)}</span>
        <Button size="sm" variant="quiet" busy={refresh.isPending} onClick={() => refresh.mutate()}>
          Refresh
        </Button>
        <Button
          size="sm"
          variant="quiet"
          icon={<Trash2 size={12} />}
          busy={remove.isPending}
          onClick={() => remove.mutate()}
          aria-label={`Remove ${server.name}`}
        />
      </div>
      {server.last_error ? (
        <p className="mt-1.5 text-xs text-fail">{server.last_error}</p>
      ) : server.tools.length ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {server.tools.map((tool) => (
            <Badge key={tool} mono>
              {tool}
            </Badge>
          ))}
        </div>
      ) : null}
    </li>
  );
}

function ConnectDialog({
  companyId,
  open,
  onClose,
}: {
  companyId: string;
  open: boolean;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [provider, setProvider] = useState("github");
  const [values, setValues] = useState<Record<string, string>>({});

  const catalogue = useQuery({
    queryKey: ["catalogue"],
    queryFn: api.connections.catalogue,
    enabled: open,
  });
  const chosen = (catalogue.data?.providers ?? []).find(
    (entry) => (entry as { provider: string }).provider === provider,
  ) as
    | { provider: string; label: string; tools: string[]; fields: { key: string; label: string; secret?: boolean }[] }
    | undefined;

  const save = useMutation({
    mutationFn: () => {
      const secretField = chosen?.fields.find((field) => field.secret);
      const config = Object.fromEntries(
        Object.entries(values).filter(([key]) => key !== secretField?.key),
      );
      return api.companies.saveConnection(companyId, {
        tool: chosen?.tools[0] ?? "tracker",
        provider,
        config,
        secret: secretField ? values[secretField.key] : undefined,
        base_url: values.base_url,
      });
    },
    onSuccess: (result) => {
      client.invalidateQueries({ queryKey: keys.connections(companyId) });
      const ok = (result.test as { ok?: boolean })?.ok;
      toast.show(
        ok ? "ok" : "error",
        ok ? `${provider} is connected.` : String((result.test as { error?: string })?.error ?? ""),
      );
      if (ok) onClose();
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Connect a tool"
      hint="Credentials are sealed. Saving tests the connection immediately."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
            Connect and test
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Provider">
          <Select
            value={provider}
            onChange={(event) => {
              setProvider(event.target.value);
              setValues({});
            }}
          >
            {(catalogue.data?.providers ?? []).map((entry) => {
              const row = entry as { provider: string; label: string };
              return (
                <option key={row.provider} value={row.provider}>
                  {row.label}
                </option>
              );
            })}
          </Select>
        </Field>

        {chosen?.fields.map((field) => (
          <Field key={field.key} label={field.label}>
            <Input
              type={field.secret ? "password" : "text"}
              value={values[field.key] ?? ""}
              onChange={(event) =>
                setValues((current) => ({ ...current, [field.key]: event.target.value }))
              }
            />
          </Field>
        ))}
      </div>
    </Dialog>
  );
}

function ServerDialog({
  companyId,
  open,
  onClose,
}: {
  companyId: string;
  open: boolean;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");

  const add = useMutation({
    mutationFn: () => api.companies.addMcpServer(companyId, { name, url, token: token || undefined }),
    onSuccess: (server) => {
      client.invalidateQueries({ queryKey: keys.connections(companyId) });
      if (server.status === "connected") {
        toast.show("ok", `${server.name} offers ${server.tools.length} tool(s).`);
        onClose();
      } else {
        toast.show("error", server.last_error ?? "That server did not answer.");
      }
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add an MCP server"
      hint="Eden handshakes with it and caches its tool list, so a turn does not pay for discovery."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            busy={add.isPending}
            disabled={!name.trim() || !url.trim()}
            onClick={() => add.mutate()}
          >
            Add and connect
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name" hint="Used to prefix its tools, so two servers can both have a search.">
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="linear" />
        </Field>
        <Field label="URL">
          <Input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://mcp.example.com/rpc"
          />
        </Field>
        <Field label="Bearer token" hint="Optional. Sealed before it is stored.">
          <Input type="password" value={token} onChange={(event) => setToken(event.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}
