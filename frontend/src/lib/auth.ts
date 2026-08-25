"use client";

import { api, ApiError, BASE } from "./api";

/**
 * Signing in from the browser.
 *
 * Tokens are set as HTTP-only cookies by the backend and travel through the
 * same-origin proxy, so nothing here ever reads or writes them. That is the
 * whole point: a script injected into this page cannot steal a session it
 * cannot see. The cost is that every call has to send credentials, which is
 * what `credentials: "include"` in the API client is for.
 */

export interface Account {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_owner: boolean;
  created_at: string | null;
  last_login_at: string | null;
  tenant: { id: string | null; name: string | null; slug: string | null };
  two_factor: TwoFactorStatus;
  companies?: number;
  active_sessions?: number;
}

export interface TwoFactorStatus {
  enabled: boolean;
  enabled_at: string | null;
  backup_codes_left: number;
  setup_started: boolean;
}

export interface SignedIn {
  status: "signed_in";
  requires_2fa: false;
  user: Account;
}

export interface NeedsSecondFactor {
  status: "2fa_required";
  requires_2fa: true;
  temporary_token: string;
  expires_in: number;
  note: string;
}

export type LoginResult = SignedIn | NeedsSecondFactor;

export const auth = {
  signUp: (body: {
    email: string;
    password: string;
    full_name?: string;
    organisation?: string;
  }) => post<SignedIn>("/auth/signup", body),

  logIn: (email: string, password: string) =>
    post<LoginResult>("/auth/login", { email, password }),

  secondFactor: (temporaryToken: string, code: string) =>
    post<SignedIn>("/auth/login/2fa", { temporary_token: temporaryToken, code }),

  logOut: () => post<{ status: string }>("/auth/logout"),
  logOutEverywhere: () => post<{ sessions_ended: number }>("/auth/logout-everywhere"),
  refresh: () => post<{ status: string }>("/auth/refresh"),

  me: () => api.me(),
  updateMe: (body: { full_name?: string }) => api.updateMe(body),
  changePassword: (current: string, next: string) =>
    post<{ other_sessions_ended: number }>("/users/me/password", {
      current_password: current,
      new_password: next,
    }),
  sessions: () => api.sessions(),

  startTwoFactor: () =>
    post<{ secret: string; uri: string; issuer: string; note: string }>("/auth/2fa/setup"),
  confirmTwoFactor: (code: string) =>
    post<{ backup_codes: string[]; note: string }>("/auth/2fa/verify-setup", { code }),
  disableTwoFactor: (password: string, code: string) =>
    post<{ status: string }>("/auth/2fa/disable", { password, code }),
  newBackupCodes: (code: string) =>
    post<{ backup_codes: string[]; note: string }>("/auth/2fa/backup-codes", { code }),
};

async function post<T>(path: string, body?: unknown): Promise<T> {
  // No refresh-and-retry here on purpose: these *are* the session endpoints,
  // and a 401 from one of them is the answer rather than a stale token.
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const parsed = await response.json();
      detail = typeof parsed.detail === "string" ? parsed.detail : detail;
    } catch {
      /* keep the status-based message */
    }
    throw new ApiError(detail, response.status);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
