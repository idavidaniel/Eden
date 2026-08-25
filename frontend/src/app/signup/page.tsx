"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserRoundPlus } from "lucide-react";
import { auth } from "@/lib/auth";
import { AuthError, AuthShell } from "@/components/auth/shell";
import { Button, Field, Input, cx } from "@/components/ui";

const MIN_PASSWORD = 10;

export default function SignUp() {
  const router = useRouter();
  const client = useQueryClient();

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;

  const create = useMutation({
    mutationFn: () =>
      auth.signUp({
        email: email.trim(),
        password,
        full_name: fullName.trim(),
        organisation: organisation.trim(),
      }),
    onSuccess: (result) => {
      client.setQueryData(["me"], result.user);
      router.replace("/");
    },
    onError: (failure: Error) => setError(failure.message),
  });

  return (
    <AuthShell
      title="Create an account"
      hint="You get an organisation of your own. Everything you found lives inside it."
      footer={
        <>
          Already have one?{" "}
          <Link href="/login" className="text-accent hover:underline">
            Sign in
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
          create.mutate();
        }}
      >
        <Field label="Your name">
          <Input
            autoComplete="name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            placeholder="Ada Kern"
            autoFocus
          />
        </Field>
        <Field label="Email">
          <Input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>
        <Field
          label="Organisation"
          hint="Optional. Leave it blank and one is named after you."
        >
          <Input
            value={organisation}
            onChange={(event) => setOrganisation(event.target.value)}
            placeholder="Marsh & Idris"
          />
        </Field>
        <Field
          label="Password"
          hint={
            <span className={cx(tooShort && "text-fail")}>
              At least {MIN_PASSWORD} characters. A short phrase you can remember beats a
              short password you cannot.
            </span>
          }
        >
          <Input
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>
        <Button
          type="submit"
          variant="primary"
          icon={<UserRoundPlus size={14} />}
          busy={create.isPending}
          className="w-full"
          disabled={!email.trim() || password.length < MIN_PASSWORD}
        >
          Create account
        </Button>
      </form>
    </AuthShell>
  );
}
