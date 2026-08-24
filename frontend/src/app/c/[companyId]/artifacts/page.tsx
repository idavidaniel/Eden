"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Boxes } from "lucide-react";
import { api } from "@/lib/api";
import { bytes, timeAgo, titleCase } from "@/lib/format";
import { keys } from "@/lib/hooks";
import {
  Badge,
  Empty,
  ErrorNote,
  LinkCell,
  Mono,
  PageHeader,
  Panel,
  Row,
  Skeleton,
  Table,
  Td,
  Th,
  cx,
} from "@/components/ui";
import { HashChip } from "@/components/ui/provenance";

export default function Artifacts({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const [kind, setKind] = useState<string>("");

  const artifacts = useQuery({
    queryKey: [...keys.artifacts(companyId), kind],
    queryFn: () => api.companies.artifacts(companyId, kind || undefined),
  });

  const kinds = Object.entries(artifacts.data?.by_kind ?? {}).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  return (
    <div className="space-y-5">
      <PageHeader
        title="Deliverables"
        hint="Everything this company has produced, each pinned to the bytes it was checked as."
      />

      {kinds.length > 1 ? (
        <div className="scroll-x flex gap-1">
          <FilterChip label="Everything" active={!kind} onClick={() => setKind("")} />
          {kinds.map(([name, total]) => (
            <FilterChip
              key={name}
              label={`${titleCase(name)} ${total}`}
              active={kind === name}
              onClick={() => setKind(name)}
            />
          ))}
        </div>
      ) : null}

      {artifacts.error ? (
        <ErrorNote error={artifacts.error} retry={() => artifacts.refetch()} />
      ) : artifacts.isLoading ? (
        <Skeleton className="h-64" />
      ) : artifacts.data?.artifacts.length ? (
        <Panel>
          <Table>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Kind</Th>
                <Th align="right">Version</Th>
                <Th align="right">Size</Th>
                <Th>Content hash</Th>
                <Th align="right">Updated</Th>
              </tr>
            </thead>
            <tbody>
              {artifacts.data.artifacts.map((artifact) => (
                <Row key={artifact.id}>
                  <Td>
                    <LinkCell href={`/c/${companyId}/artifacts/${artifact.id}`}>
                      <Mono className="block truncate">{artifact.name}</Mono>
                      {artifact.title && artifact.title !== artifact.name ? (
                        <span className="block truncate text-xs text-faint">{artifact.title}</span>
                      ) : null}
                    </LinkCell>
                  </Td>
                  <Td>
                    <Badge>{artifact.kind}</Badge>
                  </Td>
                  <Td align="right" className="tnum text-muted">
                    {artifact.version}
                  </Td>
                  <Td align="right" className="tnum text-muted">
                    {bytes(artifact.size_bytes)}
                  </Td>
                  <Td>
                    <HashChip hash={artifact.content_hash} />
                  </Td>
                  <Td align="right" className="text-muted">
                    {timeAgo(artifact.updated_at)}
                  </Td>
                </Row>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : (
        <Panel>
          <Empty icon={<Boxes size={22} />} title="Nothing produced yet">
            A deliverable appears here the moment an agent saves one, with the hash that check
            results are tied to.
          </Empty>
        </Panel>
      )}

      <p className="text-xs text-faint">
        Deliverables are content-addressed. If a file changes after it was checked, the hash stops
        matching and{" "}
        <Link href={`/c/${companyId}/ops`} className="text-accent hover:underline">
          re-verification
        </Link>{" "}
        says so.
      </p>
    </div>
  );
}

function FilterChip({
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
