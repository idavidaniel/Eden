"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, ShieldCheck } from "lucide-react";
import { auth } from "@/lib/auth";
import { AuthError, AuthShell } from "@/components/auth/shell";
import { Button, Field, Input } from "@/components/ui";

export default function TwoFactor() {
  return (
    <Suspense fallback={null}>
      <SecondFactorForm />
    </Suspense>
  );
}

function SecondFactorForm() {
  const router = useRouter();
  const search = useSearchParams();
  const client = useQueryClient();

  const token = search.get("token") ?? "";
  const next = search.get("next") || "/";
  const [code, setCode] = useState("");
  const [usingBackup, setUsingBackup] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const verify = useMutation({
    mutationFn: () => auth.secondFactor(token, code.trim()),
    onSuccess: (result) => {
      client.setQueryData(["me"], result.user);
      router.replace(next);
    },
    onError: (failure: Error) => setError(failure.message),
  });

  if (!token) {
    return (
      <AuthShell title="Start again" hint="This page needs to be reached from sign-in.">
        <Button variant="primary" className="w-full" onClick={() => router.replace("/login")}>
          Back to sign in
        </Button>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="One more step"
      hint={
        usingBackup
          ? "Enter one of the backup codes you saved. Each works once."
          : "Enter the six-digit code from your authenticator app."
      }
      footer={
        <button
          type="button"
          className="text-accent hover:underline"
          onClick={() => {
            setUsingBackup((value) => !value);
            setCode("");
            setError(null);
          }}
        >
          {usingBackup ? "Use my authenticator app instead" : "I do not have my phone"}
        </button>
      }
    >
      <AuthError message={error} />
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          verify.mutate();
        }}
      >
        <Field label={usingBackup ? "Backup code" : "Authentication code"}>
          <Input
            // `one-time-code` lets a phone offer the code from the keyboard.
            autoComplete="one-time-code"
            inputMode={usingBackup ? "text" : "numeric"}
            required
            autoFocus
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder={usingBackup ? "A1B2C-D3E4F" : "123456"}
            className="text-center font-mono text-lg tracking-[0.3em]"
          />
        </Field>
        <Button
          type="submit"
          variant="primary"
          icon={usingBackup ? <KeyRound size={14} /> : <ShieldCheck size={14} />}
          busy={verify.isPending}
          className="w-full"
          disabled={!code.trim()}
        >
          Verify
        </Button>
      </form>
    </AuthShell>
  );
}
