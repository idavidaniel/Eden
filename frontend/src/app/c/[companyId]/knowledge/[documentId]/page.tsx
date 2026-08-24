"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import { ArrowLeft, Pencil } from "lucide-react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { keys } from "@/lib/hooks";
import {
  Badge,
  Button,
  ErrorNote,
  PageHeader,
  Panel,
  Skeleton,
  Textarea,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function DocumentPage({
  params,
}: {
  params: Promise<{ companyId: string; documentId: string }>;
}) {
  const { companyId, documentId } = use(params);
  const client = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<string | null>(null);

  const document = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => api.wiki.get(documentId),
  });

  const save = useMutation({
    mutationFn: () => api.wiki.update(documentId, { body: editing ?? "" }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["document", documentId] });
      client.invalidateQueries({ queryKey: keys.documents(companyId) });
      setEditing(null);
      toast.show("ok", "Saved.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  if (document.error) return <ErrorNote error={document.error} retry={() => document.refetch()} />;
  if (!document.data) return <Skeleton className="h-96" />;

  return (
    <div className="space-y-5">
      <Link
        href={`/c/${companyId}/knowledge`}
        className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-ink"
      >
        <ArrowLeft size={13} />
        Knowledge
      </Link>

      <PageHeader
        eyebrow={<Badge>{document.data.space}</Badge>}
        title={document.data.title}
        hint={`Updated ${timeAgo(document.data.updated_at)}`}
        action={
          editing === null ? (
            <Button
              size="sm"
              icon={<Pencil size={13} />}
              onClick={() => setEditing(document.data!.body ?? "")}
            >
              Edit
            </Button>
          ) : (
            <>
              <Button size="sm" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button size="sm" variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
                Save
              </Button>
            </>
          )
        }
      />

      <Panel className="p-6">
        {editing === null ? (
          <div className="doc">
            <ReactMarkdown>{document.data.body ?? ""}</ReactMarkdown>
          </div>
        ) : (
          <Textarea
            value={editing}
            onChange={(event) => setEditing(event.target.value)}
            className="min-h-[28rem] font-mono text-xs"
          />
        )}
      </Panel>
    </div>
  );
}
