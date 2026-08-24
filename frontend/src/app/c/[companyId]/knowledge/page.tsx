"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Plus, ScrollText } from "lucide-react";
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
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
  Textarea,
  cx,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function Knowledge({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const [space, setSpace] = useState("");
  const [writing, setWriting] = useState(false);

  const wiki = useQuery({
    queryKey: keys.documents(companyId),
    queryFn: () => api.wiki.list(companyId),
  });
  const employees = useQuery({
    queryKey: keys.employees(companyId),
    queryFn: () => api.employees.list(companyId),
  });

  const documents = useMemo(
    () =>
      (wiki.data?.documents ?? []).filter((document) => !space || document.space === space),
    [wiki.data, space],
  );

  return (
    <div className="space-y-5">
      <PageHeader
        title="Knowledge"
        hint="What the company wrote down for itself, and what each agent privately remembers."
        action={
          <Button variant="primary" icon={<Plus size={14} />} onClick={() => setWriting(true)}>
            New document
          </Button>
        }
      />

      {wiki.error ? (
        <ErrorNote error={wiki.error} retry={() => wiki.refetch()} />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
          <div className="min-w-0 space-y-3">
            {(wiki.data?.spaces.length ?? 0) > 1 ? (
              <div className="scroll-x flex gap-1">
                <SpaceChip label="Everything" active={!space} onClick={() => setSpace("")} />
                {wiki.data!.spaces.map((name) => (
                  <SpaceChip
                    key={name}
                    label={name}
                    active={space === name}
                    onClick={() => setSpace(name)}
                  />
                ))}
              </div>
            ) : null}

            {wiki.isLoading ? (
              <Skeleton className="h-48" />
            ) : documents.length ? (
              <Panel>
                <ul className="divide-y divide-line">
                  {documents.map((document) => (
                    <li key={document.id}>
                      <Link
                        href={`/c/${companyId}/knowledge/${document.id}`}
                        className="block px-4 py-3 transition-colors hover:bg-sunken"
                      >
                        <div className="flex items-center gap-2">
                          <h2 className="text-sm font-medium text-ink">{document.title}</h2>
                          <Badge>{document.space}</Badge>
                          <span className="flex-1" />
                          <span className="text-xs text-faint">{timeAgo(document.updated_at)}</span>
                        </div>
                        {document.excerpt ? (
                          <p className="mt-1 line-clamp-2 text-sm text-muted">{document.excerpt}</p>
                        ) : null}
                      </Link>
                    </li>
                  ))}
                </ul>
              </Panel>
            ) : (
              <Panel>
                <Empty icon={<ScrollText size={22} />} title="Nothing written down yet">
                  Agents publish here as they learn things worth keeping for everyone.
                </Empty>
              </Panel>
            )}
          </div>

          <Panel className="self-start">
            <PanelHeader
              icon={<Brain size={14} />}
              title="Private memory"
              hint="Each agent keeps its own. Open one to read or correct it."
            />
            <ul className="divide-y divide-line">
              {(employees.data ?? []).map((person) => (
                <li key={person.id}>
                  <Link
                    href={`/c/${companyId}/agents/${person.id}`}
                    className="flex items-center gap-2 px-4 py-2 transition-colors hover:bg-sunken"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-ink">{person.name}</span>
                      <span className="block truncate text-xs text-faint">{person.title}</span>
                    </span>
                    <span className="text-xs text-accent">memory →</span>
                  </Link>
                </li>
              ))}
            </ul>
            <p className="border-t border-line px-4 py-3 text-xs text-muted">
              An agent may only distil a procedure from work whose checks passed. Facts you teach
              it are facts; earned know-how has to be earned.
            </p>
          </Panel>
        </div>
      )}

      <WriteDialog companyId={companyId} open={writing} onClose={() => setWriting(false)} />
    </div>
  );
}

function SpaceChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "rounded-md border px-2.5 py-1 text-xs whitespace-nowrap transition-colors",
        active
          ? "border-accent bg-accent-wash text-accent"
          : "border-line text-muted hover:bg-sunken hover:text-ink",
      )}
    >
      {label}
    </button>
  );
}

function WriteDialog({
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
  const [title, setTitle] = useState("");
  const [space, setSpace] = useState("General");
  const [body, setBody] = useState("");

  const create = useMutation({
    mutationFn: () => api.wiki.create(companyId, { title, space, body }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.documents(companyId) });
      toast.show("ok", "Published. Everyone can retrieve it.");
      setTitle("");
      setBody("");
      onClose();
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New document"
      hint="Markdown. Agents can search and cite this."
      wide
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            busy={create.isPending}
            disabled={!title.trim()}
            onClick={() => create.mutate()}
          >
            Publish
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-[1fr_10rem]">
          <Field label="Title">
            <Input value={title} onChange={(event) => setTitle(event.target.value)} autoFocus />
          </Field>
          <Field label="Space">
            <Input value={space} onChange={(event) => setSpace(event.target.value)} />
          </Field>
        </div>
        <Field label="Body">
          <Textarea
            value={body}
            onChange={(event) => setBody(event.target.value)}
            className="min-h-64 font-mono text-xs"
          />
        </Field>
      </div>
    </Dialog>
  );
}
