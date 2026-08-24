"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, KeyRound, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { timeAgo, titleCase } from "@/lib/format";
import { keys } from "@/lib/hooks";
import type { MintedToken } from "@/lib/types";
import {
  Badge,
  Button,
  Dialog,
  Empty,
  Field,
  Input,
  Mono,
  Panel,
  PanelHeader,
  Reveal,
  Skeleton,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

const SCOPES = [
  { key: "agent:message", hint: "Ask them to do a turn now" },
  { key: "agent:task", hint: "Queue and cancel work" },
  { key: "agent:read", hint: "Read their card, tasks and usage" },
  { key: "memory:read", hint: "Read what they remember" },
  { key: "memory:write", hint: "Teach them facts" },
  { key: "tools:*", hint: "Use their whole toolbelt" },
];

export function AgentTools({ employeeId }: { employeeId: string }) {
  const [minting, setMinting] = useState(false);
  const [minted, setMinted] = useState<MintedToken | null>(null);

  const card = useQuery({ queryKey: keys.agent(employeeId), queryFn: () => api.agents.card(employeeId) });
  const tokens = useQuery({
    queryKey: keys.agentTokens(employeeId),
    queryFn: () => api.agents.tokens(employeeId),
  });

  const grouped = new Map<string, { name: string; description: string; read_only: boolean }[]>();
  for (const tool of card.data?.tools ?? []) {
    grouped.set(tool.group, [...(grouped.get(tool.group) ?? []), tool]);
  }

  return (
    <div className="space-y-5">
      <Panel>
        <PanelHeader
          icon={<KeyRound size={14} />}
          title="Tokens"
          hint="A token is the key to this one agent. It cannot be used to drive a colleague."
          action={
            <Button size="sm" variant="primary" icon={<Plus size={13} />} onClick={() => setMinting(true)}>
              Mint
            </Button>
          }
        />
        {tokens.data?.length ? (
          <Table>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Prefix</Th>
                <Th>Scopes</Th>
                <Th>Last used</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {tokens.data.map((token) => (
                <TokenRow key={token.id} employeeId={employeeId} token={token} />
              ))}
            </tbody>
          </Table>
        ) : (
          <Empty icon={<KeyRound size={20} />} title="No tokens">
            Mint one to call this agent from anywhere — a script, a cron job, another product.
          </Empty>
        )}
      </Panel>

      <Panel>
        <PanelHeader
          icon={<ShieldCheck size={14} />}
          title="Toolbelt"
          hint="Exactly what this agent can do. Anything not listed is not reachable by them."
        />
        {card.data ? (
          <div className="divide-y divide-line">
            {[...grouped.entries()].map(([group, tools]) => (
              <div key={group} className="px-4 py-3">
                <h3 className="mb-2 text-xs font-semibold text-ink">{titleCase(group)}</h3>
                <ul className="grid gap-1.5 sm:grid-cols-2">
                  {tools.map((tool) => (
                    <li key={tool.name} className="flex items-start gap-2">
                      <Badge tone={tool.read_only ? "neutral" : "pending"} mono>
                        {tool.read_only ? "reads" : "writes"}
                      </Badge>
                      <span className="min-w-0">
                        <Mono className="block text-ink">{tool.name}</Mono>
                        <span className="block text-xs text-muted">{tool.description}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-2 p-4">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        )}
      </Panel>

      <MintDialog
        employeeId={employeeId}
        open={minting}
        onClose={() => setMinting(false)}
        onMinted={setMinted}
      />

      <Dialog
        open={Boolean(minted)}
        onClose={() => setMinted(null)}
        title="Copy this now"
        hint="The secret is not stored anywhere and cannot be shown again."
        wide
        footer={<Button onClick={() => setMinted(null)}>Done</Button>}
      >
        {minted ? (
          <div className="space-y-3">
            <Reveal label="Token" value={minted.token} />
            <Reveal label="Try it" value={minted.example} />
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}

function TokenRow({
  employeeId,
  token,
}: {
  employeeId: string;
  token: { id: string; name: string; prefix: string; scopes: string[]; last_used_at: string | null; revoked_at: string | null };
}) {
  const client = useQueryClient();
  const toast = useToast();
  const revoke = useMutation({
    mutationFn: () => api.agents.revoke(employeeId, token.id),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.agentTokens(employeeId) });
      toast.show("info", `${token.name} stops working immediately.`);
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <tr className={token.revoked_at ? "opacity-50" : undefined}>
      <Td>
        {token.name}
        {token.revoked_at ? <Badge tone="fail" className="ml-2">revoked</Badge> : null}
      </Td>
      <Td>
        <Mono className="text-muted">{token.prefix}…</Mono>
      </Td>
      <Td>
        <span className="flex flex-wrap gap-1">
          {token.scopes.map((scope) => (
            <Badge key={scope} mono>
              {scope}
            </Badge>
          ))}
        </span>
      </Td>
      <Td className="text-muted">{token.last_used_at ? timeAgo(token.last_used_at) : "never"}</Td>
      <Td align="right">
        {token.revoked_at ? null : (
          <Button
            size="sm"
            variant="quiet"
            icon={<Trash2 size={12} />}
            busy={revoke.isPending}
            onClick={() => revoke.mutate()}
            aria-label={`Revoke ${token.name}`}
          />
        )}
      </Td>
    </tr>
  );
}

function MintDialog({
  employeeId,
  open,
  onClose,
  onMinted,
}: {
  employeeId: string;
  open: boolean;
  onClose: () => void;
  onMinted: (token: MintedToken) => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>([
    "agent:message",
    "agent:task",
    "agent:read",
    "memory:read",
    "tools:*",
  ]);

  const mint = useMutation({
    mutationFn: () => api.agents.mint(employeeId, { name: name || "default", scopes }),
    onSuccess: (token) => {
      client.invalidateQueries({ queryKey: keys.agentTokens(employeeId) });
      onClose();
      onMinted(token);
      setName("");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Mint a token"
      hint="Give it only the scopes the caller actually needs."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={mint.isPending} onClick={() => mint.mutate()}>
            Mint
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="What is it for" hint="So you know which one to revoke later.">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="nightly report script"
            autoFocus
          />
        </Field>
        <fieldset>
          <legend className="mb-1.5 text-xs font-medium text-ink">Scopes</legend>
          <div className="space-y-1">
            {SCOPES.map((scope) => (
              <label
                key={scope.key}
                className="flex cursor-pointer items-start gap-2 rounded px-1.5 py-1 hover:bg-sunken"
              >
                <input
                  type="checkbox"
                  className="mt-1 accent-[var(--accent)]"
                  checked={scopes.includes(scope.key)}
                  onChange={(event) =>
                    setScopes((current) =>
                      event.target.checked
                        ? [...current, scope.key]
                        : current.filter((key) => key !== scope.key),
                    )
                  }
                />
                <span>
                  <Mono className="block text-ink">{scope.key}</Mono>
                  <span className="block text-xs text-muted">{scope.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>
    </Dialog>
  );
}

export const TOOLS_ICON = Eye;
