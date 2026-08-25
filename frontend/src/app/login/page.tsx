"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogIn } from "lucide-react";
import { auth } from "@/lib/auth";
import { AuthError, AuthShell } from "@/components/auth/shell";
import { Button, Field, Input } from "@/components/ui";

export default function Login() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const client = useQueryClient();
  const next = search.get("next") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const signIn = useMutation({
    mutationFn: () => auth.logIn(email.trim(), password),
    onSuccess: (result) => {
      if (result.requires_2fa) {
        // The temporary token is useless on its own and expires in minutes, so
        // handing it to the next page in the URL is acceptable. It is not a
        // session, and cannot be presented as one.
        const to = new URLSearchParams({ token: result.temporary_token, next });
        router.push(`/2fa?${to}`);
        return;
      }
      client.setQueryData(["me"], result.user);
      router.replace(next);
    },
    onError: (failure: Error) => setError(failure.message),
  });

  return (
    <AuthShell
      title="Sign in"
      hint="To your organisation and everything it runs."
      footer={
        <>
          No account yet?{" "}
          <Link href="/signup" className="text-accent hover:underline">
            Create one
          </Link>
        </>
      }
    >
      <AuthError message={error} />
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          signIn.mutate();
        }}
      >
        <Field label="Email">
          <Input
            type="email"
            autoComplete="email"
            required
            autoFocus
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>
        <Button
          type="submit"
          variant="primary"
          icon={<LogIn size={14} />}
          busy={signIn.isPending}
          className="w-full"
          disabled={!email.trim() || !password}
        >
          Sign in
        </Button>
      </form>
    </AuthShell>
  );
}
