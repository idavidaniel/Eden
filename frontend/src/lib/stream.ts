"use client";

import { BASE } from "./api";
import type { ActivityEvent } from "./types";

/**
 * One connection per company, shared by everything on the page.
 *
 * The old interface opened an EventSource per component that wanted live
 * updates, which meant a page showing the board, the feed and the header held
 * three connections to the same stream and paid for three copies of every
 * event. Browsers also cap concurrent connections per origin, so enough panels
 * would quietly stop updating.
 *
 * Subscribers register here instead. The first one opens the connection, the
 * last one to leave closes it, and everyone in between shares the same frames.
 */

type Listener = (event: ActivityEvent) => void;

interface Channel {
  source: EventSource;
  listeners: Set<Listener>;
  cursor: number;
  closing: ReturnType<typeof setTimeout> | null;
}

const channels = new Map<string, Channel>();

// A component unmounting and remounting (a route change, React strict mode)
// should not tear the connection down and build it again.
const LINGER_MS = 4000;

function open(companyId: string, cursor: number): Channel {
  const channel: Channel = {
    source: new EventSource(`${BASE}/companies/${companyId}/stream?cursor=${cursor}`),
    listeners: new Set(),
    cursor,
    closing: null,
  };

  channel.source.onmessage = (frame) => {
    let event: ActivityEvent;
    try {
      event = JSON.parse(frame.data) as ActivityEvent;
    } catch {
      return; // keep-alives and malformed frames
    }
    if (typeof event.seq !== "number" || event.seq <= channel.cursor) return;
    channel.cursor = event.seq;
    for (const listener of channel.listeners) listener(event);
  };

  return channel;
}

export function subscribe(companyId: string, cursor: number, listener: Listener): () => void {
  let channel = channels.get(companyId);
  if (!channel) {
    channel = open(companyId, cursor);
    channels.set(companyId, channel);
  }
  if (channel.closing) {
    clearTimeout(channel.closing);
    channel.closing = null;
  }
  channel.listeners.add(listener);

  return () => {
    const live = channels.get(companyId);
    if (!live) return;
    live.listeners.delete(listener);
    if (live.listeners.size > 0) return;
    live.closing = setTimeout(() => {
      if (live.listeners.size === 0) {
        live.source.close();
        channels.delete(companyId);
      }
    }, LINGER_MS);
  };
}

/** Where the shared stream has got to, for a fetch that wants to resume from it. */
export function cursorFor(companyId: string): number {
  return channels.get(companyId)?.cursor ?? 0;
}
