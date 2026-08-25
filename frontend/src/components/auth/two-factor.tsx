"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { Download, ShieldCheck, ShieldOff } from "lucide-react";
import { auth, type TwoFactorStatus } from "@/lib/auth";
import {
  Badge,
  Button,
  Dialog,
  Field,
  Input,
  Panel,
  PanelHeader,
  Reveal,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

/**
 * Turning the second factor on and off.
 *
 * Setup is three screens on purpose: scan, prove it works, save the backup
 * codes. Skipping the middle one is how people lock themselves out — the QR
 * scanned fine, the clock was wrong, and nobody found out until the next login.
 */
export function TwoFactorPanel({
  status,
  onChanged,
}: {
  status: TwoFactorStatus;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [stage, setStage] = useState<"idle" | "scan" | "codes">("idle");
  const [secret, setSecret] = useState<{ secret: string; uri: string } | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [disabling, setDisabling] = useState(false);

  const start = useMutation({
    mutationFn: auth.startTwoFactor,
    onSuccess: (result) => {
      setSecret(result);
      setCode("");
      setStage("scan");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const confirm = useMutation({
    mutationFn: () => auth.confirmTwoFactor(code.trim()),
    onSuccess: (result) => {
      setCodes(result.backup_codes);
      setStage("codes");
      onChanged();
      toast.show("ok", "Two-factor is on.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Panel>
      <PanelHeader
        icon={<ShieldCheck size={14} />}
        title="Two-factor authentication"
        hint={
          status.enabled
            ? "A code from your phone is needed as well as your password."
            : "A password can be guessed or reused. A code from your phone cannot."
        }
        action={
          status.enabled ? (
            <Badge tone="pass">On</Badge>
          ) : (
            <Badge tone="pending">Off</Badge>
          )
        }
      />

      <div className="space-y-3 p-4">
        {status.enabled ? (
          <>
            <p className="text-sm text-muted">
              {status.backup_codes_left} backup code
              {status.backup_codes_left === 1 ? "" : "s"} left.
              {status.backup_codes_left <= 2 ? (
                <span className="text-pending"> Worth generating a new set.</span>
              ) : null}
            </p>
            <div className="flex flex-wrap gap-2">
              <NewCodesButton onIssued={setCodesAndShow} />
              <Button
                variant="danger"
                size="sm"
                icon={<ShieldOff size={13} />}
                onClick={() => setDisabling(true)}
              >
                Turn off
              </Button>
            </div>
          </>
        ) : (
          <Button
            variant="primary"
            size="sm"
            busy={start.isPending}
            onClick={() => start.mutate()}
          >
            Set it up
          </Button>
        )}
      </div>

      {/* --- scan and confirm --- */}
      <Dialog
        open={stage === "scan"}
        onClose={() => setStage("idle")}
        title="Scan this, then prove it works"
        hint="Nothing changes until a code from your app is accepted."
        footer={
          <>
            <Button onClick={() => setStage("idle")}>Cancel</Button>
            <Button
              variant="primary"
              busy={confirm.isPending}
              disabled={code.trim().length < 6}
              onClick={() => confirm.mutate()}
            >
              Turn it on
            </Button>
          </>
        }
      >
        {secret ? (
          <div className="space-y-4">
            <div className="flex justify-center rounded-md border border-line bg-white p-4">
              {/* White ground on purpose: a dark-on-dark QR does not scan. */}
              <QRCodeSVG value={secret.uri} size={168} level="M" />
            </div>
            <details>
              <summary className="cursor-pointer text-xs text-muted hover:text-ink">
                Cannot scan it?
              </summary>
              <div className="mt-2">
                <Reveal label="Enter this by hand" value={secret.secret} />
              </div>
            </details>
            <Field label="Code from your app">
              <Input
                autoComplete="one-time-code"
                inputMode="numeric"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="123456"
                className="text-center font-mono text-lg tracking-[0.3em]"
                autoFocus
              />
            </Field>
          </div>
        ) : null}
      </Dialog>

      {/* --- backup codes, shown once --- */}
      <Dialog
        open={stage === "codes"}
        onClose={() => {
          setStage("idle");
          setCodes([]);
        }}
        title="Save these now"
        hint="Each works once. They are hashed here, so they cannot be shown again."
        footer={
          <Button
            variant="primary"
            onClick={() => {
              setStage("idle");
              setCodes([]);
            }}
          >
            I have saved them
          </Button>
        }
      >
        <BackupCodes codes={codes} />
      </Dialog>

      <DisableDialog
        open={disabling}
        onClose={() => setDisabling(false)}
        onDone={onChanged}
      />
    </Panel>
  );

  function setCodesAndShow(issued: string[]) {
    setCodes(issued);
    setStage("codes");
    onChanged();
  }
}

function BackupCodes({ codes }: { codes: string[] }) {
  const asText = codes.join("\n");
  return (
    <div className="space-y-3">
      <ul className="grid grid-cols-2 gap-1.5 rounded-md border border-line bg-sunken p-3">
        {codes.map((code) => (
          <li key={code} className="font-mono text-sm tracking-wide text-ink">
            {code}
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button
          size="sm"
          icon={<Download size={13} />}
          onClick={() => {
            // Built in the page rather than fetched: these bytes must never
            // make a second trip to a server.
            const blob = new Blob(
              [`Eden backup codes\n\nEach of these works once.\n\n${asText}\n`],
              { type: "text/plain" },
            );
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = "eden-backup-codes.txt";
            link.click();
            URL.revokeObjectURL(url);
          }}
        >
          Download
        </Button>
        <Button size="sm" onClick={() => navigator.clipboard.writeText(asText)}>
          Copy
        </Button>
      </div>
    </div>
  );
}

function NewCodesButton({ onIssued }: { onIssued: (codes: string[]) => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");

  const issue = useMutation({
    mutationFn: () => auth.newBackupCodes(code.trim()),
    onSuccess: (result) => {
      setOpen(false);
      setCode("");
      onIssued(result.backup_codes);
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        New backup codes
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Replace your backup codes"
        hint="The ones you have now stop working the moment these are issued."
        footer={
          <>
            <Button onClick={() => setOpen(false)}>Cancel</Button>
            <Button
              variant="primary"
              busy={issue.isPending}
              disabled={code.trim().length < 6}
              onClick={() => issue.mutate()}
            >
              Issue new codes
            </Button>
          </>
        }
      >
        <Field label="Code from your app">
          <Input
            autoComplete="one-time-code"
            inputMode="numeric"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            className="text-center font-mono text-lg tracking-[0.3em]"
            autoFocus
          />
        </Field>
      </Dialog>
    </>
  );
}

function DisableDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");

  const disable = useMutation({
    mutationFn: () => auth.disableTwoFactor(password, code.trim()),
    onSuccess: () => {
      setPassword("");
      setCode("");
      onClose();
      onDone();
      toast.show("info", "Two-factor is off. Your password is now the only thing in the way.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Turn off two-factor?"
      hint="Both your password and a current code — being signed in is not enough."
      footer={
        <>
          <Button onClick={onClose}>Keep it on</Button>
          <Button
            variant="danger"
            busy={disable.isPending}
            disabled={!password || code.trim().length < 6}
            onClick={() => disable.mutate()}
          >
            Turn it off
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Your password">
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>
        <Field label="Code from your app or a backup code">
          <Input
            autoComplete="one-time-code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            className="text-center font-mono tracking-[0.2em]"
          />
        </Field>
      </div>
    </Dialog>
  );
}
