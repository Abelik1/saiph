// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, type ReactNode } from "react";
import { Switch } from "@/components/ui/switch";

/** One labelled switch row with a description and, when it cannot be changed, the reason why.
 * It saves as soon as it is switched, like Settings → Phone. */
export function SwitchRow({ title, detail, checked, disabled, reason, change }: { title: string; detail: string; checked: boolean; disabled?: boolean; reason?: string; change: (value: boolean) => Promise<unknown> }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function toggle(value: boolean) {
    setPending(true); setError("");
    try { await change(value); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setPending(false); }
  }
  return <div className="list-row">
    <div className="grow">
      <b>{title}</b>
      <small>{detail}</small>
      {reason && <small className="text-attention-foreground">{reason}</small>}
      {error && <small className="inline-error" role="alert">{error}</small>}
    </div>
    <Switch checked={checked} disabled={disabled || pending} aria-label={title} onCheckedChange={(value) => void toggle(value)} />
  </div>;
}

/** A setting row whose control is a button or a small form rather than a switch. */
export function ActionRow({ title, detail, reason, children }: { title: string; detail: string; reason?: string; children: ReactNode }) {
  return <div className="list-row">
    <div className="grow">
      <b>{title}</b>
      <small>{detail}</small>
      {reason && <small className="text-attention-foreground">{reason}</small>}
    </div>
    {children}
  </div>;
}
