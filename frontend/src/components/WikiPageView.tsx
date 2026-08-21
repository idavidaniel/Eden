"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { Document } from "@/lib/types";
import { Button, Card, ErrorNote, Spinner, Textarea } from "./ui";

export default function WikiPageView({
  companyId,
  documentId,
}: {
  companyId: string;
  documentId: string;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const document = useResource<Document>(() => api.wiki.get(documentId), [documentId]);
  const [draftFor, setDraftFor] = useState<string | null>(null);

  // Reseed whenever a new version loads, so edits start from what is published.
  const versionKey = document.data ? `${document.data.id}@${document.data.version}` : null;
  if (versionKey && draftFor !== versionKey) {
    setDraftFor(versionKey);
    setDraft(document.data?.body ?? "");
  }

  const save = async () => {
    setSaving(true);
    try {
      await api.wiki.update(documentId, { body: draft });
      setEditing(false);
      document.reload();
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!confirm("Delete this page?")) return;
    await api.wiki.remove(documentId);
    router.push(`/companies/${companyId}/wiki`);
  };

  if (document.loading) return <Spinner />;
  if (document.error) return <ErrorNote>{document.error}</ErrorNote>;
  if (!document.data) return null;

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <Link href={`/companies/${companyId}/wiki`} className="text-xs text-slate-500 hover:text-slate-300">
        ← Wiki
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold text-slate-100">{document.data.title}</h1>
          <p className="mt-1 text-xs text-slate-500">
            {document.data.space} · v{document.data.version} · updated {timeAgo(document.data.updated_at)}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="subtle" onClick={() => setEditing((current) => !current)}>
            {editing ? "Preview" : "Edit"}
          </Button>
          {editing && (
            <Button size="sm" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save version"}
            </Button>
          )}
          <Button size="sm" variant="danger" onClick={remove}>
            Delete
          </Button>
        </div>
      </header>

      <Card className="p-6">
        {editing ? (
          <Textarea rows={22} value={draft} onChange={(event) => setDraft(event.target.value)} />
        ) : (
          <div className="prose-eden max-w-none text-slate-300">
            <ReactMarkdown>{document.data.body || "_This page is empty._"}</ReactMarkdown>
          </div>
        )}
      </Card>

      {document.data.history && document.data.history.length > 1 && (
        <Card className="p-4">
          <h2 className="mb-2 text-xs tracking-wide text-slate-500 uppercase">History</h2>
          <ul className="space-y-1 text-sm">
            {document.data.history.map((entry) => (
              <li key={entry.version} className="flex justify-between text-slate-400">
                <span>
                  v{entry.version} · {entry.author_label}
                </span>
                <span className="text-xs text-slate-600">{timeAgo(entry.created_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
