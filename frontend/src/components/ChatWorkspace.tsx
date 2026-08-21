"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { Channel, ChatMessage, Employee } from "@/lib/types";
import { Avatar, Button, Card, ErrorNote, Input, Spinner } from "./ui";

/** Team chat. Mention someone (@Ada) and they actually answer. */
export default function ChatWorkspace({ companyId }: { companyId: string }) {
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const channels = useResource<Channel[]>(() => api.chat.channels(companyId), [companyId]);
  const employees = useResource<Employee[]>(() => api.employees.list(companyId), [companyId]);
  // The chosen channel wins; otherwise fall back to the first one that loads.
  const active =
    channels.data?.find((channel) => channel.id === chosenId) ?? channels.data?.[0] ?? null;
  const activeId = active?.id ?? null;

  const messages = useResource<ChatMessage[]>(
    () => (activeId ? api.chat.messages(activeId) : Promise.resolve([])),
    [activeId],
    { intervalMs: 3000 },
  );

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data?.length]);
  const peopleById = new Map((employees.data ?? []).map((employee) => [employee.id, employee]));

  const send = async () => {
    if (!activeId || !draft.trim()) return;
    const body = draft;
    setDraft("");
    setError("");
    try {
      const sent = await api.chat.send(activeId, body);
      setPending(sent.replying ? `${sent.replying.name} is replying…` : null);
      messages.reload();
      if (sent.replying) setTimeout(() => setPending(null), 30000);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-bold text-slate-100">Chat</h1>
        <p className="text-sm text-slate-400">
          Mention someone by name (<span className="font-mono">@Ada</span>) and they will pick it up,
          use their tools, and reply here.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[14rem_1fr]">
        <Card className="h-fit p-2">
          {channels.loading && <Spinner />}
          {channels.data?.map((channel) => (
            <button
              key={channel.id}
              onClick={() => setChosenId(channel.id)}
              className={`block w-full truncate rounded-md px-3 py-2 text-left text-sm transition-colors ${
                activeId === channel.id ? "bg-white/10 text-white" : "text-slate-400 hover:bg-white/5"
              }`}
            >
              # {channel.name}
            </button>
          ))}
        </Card>

        <Card className="flex h-[36rem] flex-col">
          <header className="border-b border-white/10 px-4 py-3">
            <p className="font-medium text-slate-200"># {active?.name ?? "…"}</p>
            <p className="text-xs text-slate-500">{active?.purpose}</p>
          </header>

          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.data?.length === 0 && (
              <p className="py-10 text-center text-sm text-slate-600">
                No messages yet. Say hello, or ask someone for a status update.
              </p>
            )}
            {messages.data?.map((message) => {
              const author = message.author_id ? peopleById.get(message.author_id) : undefined;
              const isHuman = !message.author_id;
              return (
                <div key={message.id} className="flex gap-3">
                  <Avatar emoji={author?.avatar ?? "🧑"} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-slate-500">
                      <span className={isHuman ? "text-blue-300" : "text-slate-300"}>
                        {message.author_label}
                      </span>{" "}
                      · {timeAgo(message.created_at)}
                    </p>
                    <p className="text-sm whitespace-pre-wrap text-slate-200">{message.body}</p>
                  </div>
                </div>
              );
            })}
            {pending && <p className="text-xs text-amber-400">⚡ {pending}</p>}
            <div ref={endRef} />
          </div>

          <div className="border-t border-white/10 p-3">
            {error && <ErrorNote>{error}</ErrorNote>}
            <div className="flex gap-2">
              <Input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && send()}
                placeholder={`Message #${active?.name ?? ""} — mention @someone to get an answer`}
              />
              <Button onClick={send}>Send</Button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {employees.data?.slice(0, 8).map((employee) => (
                <button
                  key={employee.id}
                  onClick={() => setDraft((current) => `${current}@${employee.name.split(" ")[0]} `)}
                  className="rounded-full border border-white/10 px-2 py-0.5 text-xs text-slate-400 hover:border-white/25 hover:text-slate-200"
                >
                  {employee.avatar} {employee.name.split(" ")[0]}
                </button>
              ))}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
