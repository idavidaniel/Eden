"use client";

import { use, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Hash, Send, Users } from "lucide-react";
import { api } from "@/lib/api";
import { timeAgo, when } from "@/lib/format";
import { keys } from "@/lib/hooks";
import {
  Badge,
  Button,
  Dialog,
  Empty,
  Field,
  Input,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Skeleton,
  Tabs,
  Textarea,
  cx,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function Rooms({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const [tab, setTab] = useState("channels");

  return (
    <div className="space-y-5">
      <PageHeader
        title="Rooms"
        hint="Where the company talks to itself — and where a meeting has to end in something written down."
      />
      <Tabs
        tabs={[
          { key: "channels", label: "Channels" },
          { key: "meetings", label: "Meetings" },
        ]}
        active={tab}
        onSelect={setTab}
      />
      {tab === "channels" ? <Channels companyId={companyId} /> : <Meetings companyId={companyId} />}
    </div>
  );
}

function Channels({ companyId }: { companyId: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const [active, setActive] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  const channels = useQuery({
    queryKey: keys.channels(companyId),
    queryFn: () => api.chat.channels(companyId),
  });
  const current = active ?? channels.data?.[0]?.id ?? null;

  const messages = useQuery({
    queryKey: ["messages", current],
    queryFn: () => api.chat.messages(current!),
    enabled: Boolean(current),
    refetchInterval: 6000,
  });

  const send = useMutation({
    mutationFn: () => api.chat.send(current!, draft),
    onSuccess: () => {
      setDraft("");
      client.invalidateQueries({ queryKey: ["messages", current] });
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data]);

  if (channels.isLoading) return <Skeleton className="h-96" />;
  if (!channels.data?.length) {
    return (
      <Panel>
        <Empty icon={<Hash size={22} />} title="No channels" />
      </Panel>
    );
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[14rem_1fr]">
      <Panel className="self-start">
        <ul className="p-1">
          {channels.data.map((channel) => (
            <li key={channel.id}>
              <button
                type="button"
                onClick={() => setActive(channel.id)}
                className={cx(
                  "flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left text-sm transition-colors",
                  channel.id === current
                    ? "bg-accent-wash font-medium text-accent"
                    : "text-muted hover:bg-sunken hover:text-ink",
                )}
              >
                <Hash size={13} className="shrink-0" />
                <span className="truncate">{channel.name}</span>
                {channel.unread ? (
                  <span className="tnum ml-auto rounded-full bg-pending-wash px-1.5 text-[0.7rem] text-pending">
                    {channel.unread}
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel className="min-w-0">
        <PanelHeader
          icon={<Hash size={14} />}
          title={channels.data.find((entry) => entry.id === current)?.name ?? ""}
          hint={channels.data.find((entry) => entry.id === current)?.purpose}
        />
        <div className="max-h-[28rem] min-h-[16rem] overflow-y-auto px-4 py-3">
          {messages.data?.length ? (
            <ol className="space-y-3">
              {messages.data.map((message) => (
                <li key={message.id}>
                  <div className="flex items-baseline gap-2">
                    <span className="text-xs font-semibold text-ink">{message.author_label}</span>
                    <span className="text-xs text-faint">{timeAgo(message.created_at)}</span>
                  </div>
                  <p className="mt-0.5 text-sm whitespace-pre-wrap text-muted">{message.body}</p>
                </li>
              ))}
            </ol>
          ) : (
            <Empty title="Nothing said here yet" />
          )}
          <div ref={bottom} />
        </div>
        <div className="flex gap-2 border-t border-line p-3">
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && draft.trim()) send.mutate();
            }}
            placeholder="Say something — whoever is mentioned will answer."
          />
          <Button
            variant="primary"
            icon={<Send size={13} />}
            disabled={!draft.trim()}
            busy={send.isPending}
            onClick={() => send.mutate()}
          >
            Send
          </Button>
        </div>
      </Panel>
    </div>
  );
}

function Meetings({ companyId }: { companyId: string }) {
  const [holding, setHolding] = useState(false);
  const meetings = useQuery({
    queryKey: keys.meetings(companyId),
    queryFn: () => api.companies.meetings(companyId),
  });

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader
          icon={<CalendarDays size={14} />}
          title="Meetings"
          hint="A meeting that produces nothing did not happen. Each one ends in a structured outcome."
          action={
            <Button size="sm" variant="primary" onClick={() => setHolding(true)}>
              Hold one
            </Button>
          }
        />
        {meetings.data?.length ? (
          <ul className="divide-y divide-line">
            {meetings.data.map((meeting) => (
              <li key={meeting.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={meeting.status === "held" ? "pass" : "pending"}>
                    {meeting.status}
                  </Badge>
                  <Mono className="text-faint">{meeting.kind}</Mono>
                  <span className="text-sm font-medium text-ink">{meeting.title}</span>
                  <span className="flex-1" />
                  <span className="flex items-center gap-1 text-xs text-faint">
                    <Users size={11} />
                    {meeting.attendee_ids.length}
                  </span>
                  <span className="text-xs text-faint">{when(meeting.held_at)}</span>
                </div>
                {meeting.agenda ? (
                  <p className="mt-1 text-sm text-muted">{meeting.agenda}</p>
                ) : null}
                {Object.keys(meeting.outcome ?? {}).length ? (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-accent">
                      What came out of it
                    </summary>
                    <pre className="scroll-x mt-1.5 rounded border border-line bg-sunken p-2 font-mono text-xs whitespace-pre-wrap text-ink">
                      {JSON.stringify(meeting.outcome, null, 2)}
                    </pre>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <Empty icon={<CalendarDays size={22} />} title="No meetings yet">
            A standup, a review or a retro. Every one has to end with decisions and action items,
            written down and turned into work.
          </Empty>
        )}
      </Panel>

      <HoldDialog companyId={companyId} open={holding} onClose={() => setHolding(false)} />
    </div>
  );
}

function HoldDialog({
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
  const [kind, setKind] = useState("standup");
  const [title, setTitle] = useState("");
  const [agenda, setAgenda] = useState("");
  const [projectId, setProjectId] = useState("");

  const projects = useQuery({
    queryKey: keys.projects(companyId),
    queryFn: () => api.projects.list(companyId),
    enabled: open,
  });

  const hold = useMutation({
    mutationFn: () =>
      api.companies.hold(companyId, {
        kind,
        title: title || undefined,
        agenda,
        project_id: projectId || undefined,
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.meetings(companyId) });
      toast.show("ok", "Queued. It will appear here once it has been held.");
      setTitle("");
      setAgenda("");
      onClose();
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Hold a meeting"
      hint="Everyone invited speaks, then the chair is forced to write down what was decided."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={hold.isPending} onClick={() => hold.mutate()}>
            Hold it
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Kind">
          <Select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="standup">Standup — what is blocked</option>
            <option value="review">Review — is this good enough</option>
            <option value="retro">Retro — what went wrong and why</option>
            <option value="planning">Planning — what to do next</option>
          </Select>
        </Field>
        <Field label="About which project" hint="Optional. Narrows who attends and what they see.">
          <Select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
            <option value="">The whole company</option>
            {(projects.data ?? []).map((project) => (
              <option key={project.id} value={project.id}>
                {project.key} — {project.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Title" hint="Leave blank for a sensible one.">
          <Input value={title} onChange={(event) => setTitle(event.target.value)} />
        </Field>
        <Field label="Agenda" hint="What has to be settled by the end.">
          <Textarea value={agenda} onChange={(event) => setAgenda(event.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}
