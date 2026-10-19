// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useState } from "react";
import { ShieldAlert } from "lucide-react";
import type { Client, HostedState } from "./types";
import { Action } from "./ui";
import { isWizardOpen, useAnyWizardOpen } from "./pairingWizard";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type Pending = { code: string; device_id: string; fingerprint: string; expires_at: number; location?: string | null };
type Approvals = { requests: Pending[]; waiting: number; flood: boolean };

/**
 * The main computer's pop-up when a new phone or computer asks to join this
 * account. Nothing is approved automatically: the owner compares the new device's
 * security code, names it and confirms with Windows Hello. Deny hides this request
 * until it expires; Block refuses the device on this computer for good.
 */
export function DeviceApprovalPrompt({ hosted, client }: { hosted?: HostedState; client: Client }) {
  const id = useId();
  const wizard = useAnyWizardOpen();
  const [view, setView] = useState<Approvals | null>(null);
  const [later, setLater] = useState<string[]>([]);
  const [label, setLabel] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const active = Boolean(hosted?.enabled && hosted.role === "root" && hosted.status === "active") && !wizard;
  useEffect(() => {
    if (!active) { setView(null); return; }
    let alive = true;
    const look = () => isWizardOpen() ? undefined : client.call<Approvals>("hosted.approvals").then(value => {
      if (alive && !isWizardOpen() && value && Array.isArray(value.requests)) setView(value);
    }).catch(() => undefined);
    void look();
    const timer = window.setInterval(look, 15000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [active, client]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const pending = view?.requests.find(item => typeof item.fingerprint === "string" && !later.includes(item.device_id) && item.expires_at > now);
  const shown = pending?.device_id;
  useEffect(() => { setLabel(""); setConfirmed(false); }, [shown]);
  if (!active || !pending) return null;
  const done = () => setView(value => value && { ...value, requests: value.requests.filter(item => item.device_id !== pending.device_id) });
  const where = pending.location ? `near ${pending.location} (approximate)` : "at an unknown location";
  const others = (view?.waiting ?? 1) - 1;
  return <Dialog open onOpenChange={open => { if (!open) setLater(value => [...value, pending.device_id]); }}>
    <DialogContent className="w-[min(560px,calc(100vw-32px))]">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2"><ShieldAlert className="size-5" />Approve a new device?</DialogTitle>
        <DialogDescription>A phone or computer signed in to your Saiph account and asked to join.</DialogDescription>
      </DialogHeader>
      <div className="grid gap-3 text-sm">
        <p role="alert" className="m-0 rounded-[10px] bg-muted px-3 py-2.5">
          This is an unknown device {where}. Are you sure you want to approve this device? It will receive your clipboard,
          notifications and files.
        </p>
        {!pending.location && <small className="text-muted-foreground">Saiph Cloud does not report a request's location yet. When it does, it is approximate and advisory only.</small>}
        {view?.flood && <p className="m-0 font-medium">Several devices asked to join in the last few minutes. If you didn't start them, deny or block them.</p>}
        <p className="m-0 text-muted-foreground">New device's security code. Compare every group with the new device's screen:</p>
        <code className="break-words text-[13px]" aria-label="New device's security code">{pending.fingerprint}</code>
        {hosted?.fingerprint && <>
          <p className="m-0 text-muted-foreground">This computer's security code, which the new device showed before it asked:</p>
          <code className="break-words text-[13px]" aria-label="This computer's security code">{hosted.fingerprint}</code>
        </>}
        <label className="grid gap-1" htmlFor={id + "-name"}>Name this device
          <input id={id + "-name"} className="rounded-[8px] border border-border bg-field px-3 py-2" value={label} maxLength={40}
            onChange={event => setLabel(event.target.value)} />
        </label>
        <label className="flex items-start gap-2 text-[13px]">
          <input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
          Every group matches the new device, and I started this
        </label>
        <small className="text-muted-foreground" role="timer">
          This request expires in {Math.max(0, Math.ceil((pending.expires_at - now) / 60))} min{others > 0 ? ` · ${others} more waiting` : ""}.
        </small>
        <div className="flex flex-wrap gap-2">
          <Action variant="default" disabled={!confirmed || !label.trim()} run={async () => {
            await client.call("hosted.approve", { code: pending.code, label: label.trim(), confirmed: true }); done();
          }}>Approve</Action>
          <Action variant="secondary" run={async () => { await client.call("hosted.request.deny", { device_id: pending.device_id }); done(); }}>Deny</Action>
          <Action variant="destructive" run={async () => { await client.call("hosted.request.block", { device_id: pending.device_id }); done(); }}>Block this device</Action>
        </div>
      </div>
    </DialogContent>
  </Dialog>;
}
