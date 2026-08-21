"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { subscribeToActivity } from "./api";
import type { ActivityEvent } from "./types";

/**
 * Fetch on mount (and whenever `deps` change), optionally polling.
 * Data from the previous key stays visible while the next load is in flight.
 */
export function useResource<T>(
  loader: () => Promise<T>,
  deps: unknown[] = [],
  options: { intervalMs?: number } = {},
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string>("");
  const [loaded, setLoaded] = useState(false);
  const loaderRef = useRef(loader);

  // Written in an effect, not during render: the latest closure is what the
  // interval and manual reloads should call.
  useEffect(() => {
    loaderRef.current = loader;
  });

  const reload = useCallback(async () => {
    try {
      setData(await loaderRef.current());
      setError("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    reload();
    if (!options.intervalMs) return;
    const timer = setInterval(reload, options.intervalMs);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading: !loaded, reload, setData };
}

/**
 * Live activity for a company: `seed` is the history already fetched, and the
 * stream appends everything newer. Derived rather than copied into state, so
 * the two never drift apart.
 */
export function useActivity(companyId: string, seed: ActivityEvent[] = []) {
  const [streamed, setStreamed] = useState<ActivityEvent[]>([]);
  const seedCursor = seed.at(-1)?.seq ?? 0;
  const cursorRef = useRef(seedCursor);

  useEffect(() => {
    cursorRef.current = seedCursor;
  });

  useEffect(() => {
    if (!companyId) return;
    return subscribeToActivity(companyId, cursorRef.current, (event) =>
      setStreamed((current) =>
        current.some((item) => item.seq === event.seq) ? current : [...current.slice(-400), event],
      ),
    );
  }, [companyId]);

  return [...seed, ...streamed.filter((event) => event.seq > seedCursor)];
}
