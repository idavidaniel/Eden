"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { Document } from "@/lib/types";
import { Button, Card, EmptyState, ErrorNote, Field, Input, Modal, Spinner, Textarea } from "./ui";

export default function WikiIndex({ companyId }: { companyId: string }) {
  const router = useRouter();
  const [composing, setComposing] = useState(false);
  const [space, setSpace] = useState<string | null>(null);
  const wiki = useResource<{ spaces: string[]; documents: Document[] }>(
    () => api.wiki.list(companyId),
    [companyId],
    { intervalMs: 10000 },
  );

  const documents = (wiki.data?.documents ?? []).filter((doc) => !space || doc.space === space);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Wiki</h1>
          <p className="text-sm text-slate-400">
            Specs, decisions and handover notes — written by the team as they work.
          </p>
        </div>
        <Button onClick={() => setComposing(true)}>+ New page</Button>
      </header>

      {wiki.loading && <Spinner />}

      {wiki.data && wiki.data.spaces.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setSpace(null)}
            className={`rounded-full border px-3 py-1 text-xs ${
              space === null ? "border-blue-500/50 bg-blue-500/10 text-blue-200" : "border-white/10 text-slate-400"
            }`}
          >
            All spaces
          </button>
          {wiki.data.spaces.map((name) => (
            <button
              key={name}
              onClick={() => setSpace(name)}
              className={`rounded-full border px-3 py-1 text-xs ${
                space === name ? "border-blue-500/50 bg-blue-500/10 text-blue-200" : "border-white/10 text-slate-400"
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      {wiki.data?.documents.length === 0 && (
        <EmptyState
          icon="📚"
          title="The wiki is empty"
          hint="Ask the team to document something, or write the first page yourself."
          action={<Button onClick={() => setComposing(true)}>Write a page</Button>}
        />
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {documents.map((document) => (
          <Link key={document.id} href={`/companies/${companyId}/wiki/${document.id}`}>
            <Card className="h-full p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-100">{document.title}</p>
                  <p className="text-xs text-slate-500">
                    {document.space} · v{document.version}
                  </p>
                </div>
                <span className="shrink-0 text-xs text-slate-600">{timeAgo(document.updated_at)}</span>
              </div>
            </Card>
          </Link>
        ))}
      </div>

      <NewPageDialog
        open={composing}
        companyId={companyId}
        onClose={() => setComposing(false)}
        onCreated={(document) => {
          setComposing(false);
          router.push(`/companies/${companyId}/wiki/${document.id}`);
        }}
      />
    </div>
  );
}

function NewPageDialog({
  open,
  companyId,
  onClose,
  onCreated,
}: {
  open: boolean;
  companyId: string;
  onClose: () => void;
  onCreated: (document: Document) => void;
}) {
  const [title, setTitle] = useState("");
  const [space, setSpace] = useState("General");
  const [body, setBody] = useState("");
  const [error, setError] = useState("");

  const submit = async () => {
    if (!title.trim()) return setError("Give the page a title.");
    try {
      onCreated(await api.wiki.create(companyId, { title, body, space }));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="New wiki page" wide>
      <div className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-[2fr_1fr]">
          <Field label="Title">
            <Input value={title} onChange={(event) => setTitle(event.target.value)} />
          </Field>
          <Field label="Space">
            <Input value={space} onChange={(event) => setSpace(event.target.value)} />
          </Field>
        </div>
        <Field label="Body" hint="Markdown.">
          <Textarea rows={10} value={body} onChange={(event) => setBody(event.target.value)} />
        </Field>
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit}>Publish</Button>
        </div>
      </div>
    </Modal>
  );
}
