"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";
import { auth, type Account } from "./auth";

/**
 * Who is signed in, for the whole app.
 *
 * Backed by a query rather than a copy in state, so there is one source of
 * truth and no chance of the header saying one thing while a page says another.
 * A 401 is not retried — it is an answer, not a failure — and it clears the
 * session rather than leaving stale data on screen.
 */

interface SessionValue {
  account: Account | null;
  loading: boolean;
  signOut: () => void;
  signingOut: boolean;
  refresh: () => void;
}

const SessionContext = createContext<SessionValue>({
  account: null,
  loading: true,
  signOut: () => {},
  signingOut: false,
  refresh: () => {},
});

export const useSession = () => useContext(SessionContext);

/** The signed-in account, or throw. For pages that cannot render without one. */
export function useAccount(): Account {
  const { account } = useSession();
  if (!account) {
    throw new Error("useAccount used outside a signed-in page");
  }
  return account;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const router = useRouter();

  const me = useQuery({
    queryKey: ["me"],
    queryFn: auth.me,
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    staleTime: 60_000,
  });

  const signOut = useMutation({
    mutationFn: auth.logOut,
    // Even if the call fails, stop showing signed-in state: the person asked
    // to leave, and leaving them looking signed in is the worse outcome.
    onSettled: () => {
      client.clear();
      router.replace("/login");
    },
  });

  const value = useMemo<SessionValue>(
    () => ({
      account: me.data ?? null,
      loading: me.isLoading,
      signOut: () => signOut.mutate(),
      signingOut: signOut.isPending,
      refresh: () => client.invalidateQueries({ queryKey: ["me"] }),
    }),
    [me.data, me.isLoading, signOut, client],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** Send someone to sign in, remembering where they were going. */
export function useSignInRedirect() {
  const router = useRouter();
  return useCallback(
    (from?: string) => {
      const next = from ? `?next=${encodeURIComponent(from)}` : "";
      router.replace(`/login${next}`);
    },
    [router],
  );
}
