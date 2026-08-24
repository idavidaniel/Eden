"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { BOARD_COLUMNS, STATUS_LABELS, STATUS_TONES, initials } from "@/lib/format";
import { keys } from "@/lib/hooks";
import type { Employee, WorkItem, WorkStatus } from "@/lib/types";
import { Badge, Empty, Mono, cx } from "@/components/ui";
import { useToast } from "@/components/ui/toast";

/**
 * The board is writable about *status* and read-only about *verdicts*: you can
 * move a card, but nothing here marks work done — only a passing check does
 * that, which is the whole argument the product makes.
 */
export function Board({
  projectId,
  items,
  people,
  selectedId,
  onSelect,
}: {
  projectId: string;
  items: WorkItem[];
  people: Employee[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const byId = new Map(people.map((person) => [person.id, person]));
  const blocked = items.filter((item) => item.status === "blocked");

  const move = useMutation({
    mutationFn: ({ id, status }: { id: string; status: WorkStatus }) =>
      api.workItems.update(id, { status }),
    onSuccess: (_result, variables) => {
      client.invalidateQueries({ queryKey: keys.workItems(projectId) });
      client.invalidateQueries({ queryKey: keys.workItem(variables.id) });
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <div className="space-y-4">
      {blocked.length ? (
        <div className="rounded-lg border border-line bg-fail-wash px-4 py-3">
          <p className="flex items-center gap-1.5 text-sm font-medium text-fail">
            <AlertTriangle size={14} />
            {blocked.length} blocked
          </p>
          <ul className="mt-1.5 space-y-1">
            {blocked.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onSelect(item.id)}
                  className="text-left text-sm text-ink hover:underline"
                >
                  <Mono className="text-faint">{item.key}</Mono>{" "}
                  {item.blocked_reason || item.title}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="scroll-x">
        <div className="grid min-w-[64rem] grid-cols-5 gap-3">
          {BOARD_COLUMNS.map((status) => {
            const column = items.filter((item) => item.status === status);
            return (
              <section
                key={status}
                className="min-w-0 rounded-lg"
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  const id = event.dataTransfer.getData("text/plain");
                  if (id) move.mutate({ id, status });
                }}
              >
                <h3 className="mb-2 flex items-center gap-2 px-0.5 text-[0.7rem] font-semibold tracking-wider text-faint uppercase">
                  {STATUS_LABELS[status]}
                  <span className="tnum font-normal">{column.length}</span>
                </h3>
                <ul className="space-y-2">
                  {column.map((item) => (
                    <li key={item.id}>
                      <Card
                        item={item}
                        person={item.assignee_id ? byId.get(item.assignee_id) : undefined}
                        selected={item.id === selectedId}
                        onSelect={() => onSelect(item.id)}
                      />
                    </li>
                  ))}
                  {column.length === 0 ? (
                    <li className="rounded-md border border-dashed border-line px-3 py-6 text-center text-xs text-faint">
                      Nothing here
                    </li>
                  ) : null}
                </ul>
              </section>
            );
          })}
        </div>
      </div>

      {items.length === 0 ? (
        <Empty title="Nothing planned yet">
          Start the project and the team writes the plan, or add an item yourself.
        </Empty>
      ) : null}
    </div>
  );
}

function Card({
  item,
  person,
  selected,
  onSelect,
}: {
  item: WorkItem;
  person?: Employee;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      draggable
      onDragStart={(event) => event.dataTransfer.setData("text/plain", item.id)}
      className={cx(
        "cursor-pointer rounded-md border bg-surface p-2.5 transition-colors",
        selected ? "border-accent ring-1 ring-accent" : "border-line hover:border-line-strong",
      )}
    >
      <div className="flex items-start gap-2">
        <Mono className="shrink-0 text-faint">{item.key}</Mono>
        <span className="flex-1" />
        {item.rework_count > 0 ? (
          <Badge tone="pending" className="shrink-0">
            <RotateCcw size={10} />
            {item.rework_count}
          </Badge>
        ) : null}
      </div>

      <p className="mt-1 line-clamp-3 text-sm text-ink">{item.title}</p>

      <div className="mt-2 flex items-center gap-1.5">
        <Badge tone={STATUS_TONES[item.status] ?? "neutral"}>{item.kind}</Badge>
        {item.approval_required ? <Badge tone="pending">needs you</Badge> : null}
        <span className="flex-1" />
        {person ? (
          <span
            title={`${person.name} — ${person.title}`}
            className="grid size-5 shrink-0 place-items-center rounded-full bg-accent-wash text-[0.6rem] font-semibold text-accent"
          >
            {initials(person.name)}
          </span>
        ) : (
          <span className="text-[0.65rem] text-faint">unassigned</span>
        )}
      </div>
    </div>
  );
}
