// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import { Check, Circle, Volume2 } from "lucide-react";
import type { CallAudioStatus, Client } from "./types";
import { Action } from "./ui";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

/** The setup order: everything before a step must be fine for it to be reached (call_audio.py readiness). */
const order: CallAudioStatus["readiness"][] = ["checking", "unsupported", "no-adapter", "bluetooth-off", "needs-setup", "choose-phone", "not-paired", "no-calls-profile", "phone-away", "ready"];
const reached = (status: CallAudioStatus, step: CallAudioStatus["readiness"]) => order.indexOf(status.readiness) > order.indexOf(step);

/** Calls answered here use this computer's microphone and speakers. */
export function callAudioOn(status?: CallAudioStatus) {
  return Boolean(status?.supported && status.enabled && status.readiness === "ready");
}

function badge(status: CallAudioStatus): { tone: "good" | "warn" | "bad" | "quiet" | "default"; text: string } {
  if (status.readiness === "ready") return status.enabled ? { tone: "good", text: "On" } : { tone: "default", text: "Ready" };
  if (status.readiness === "checking") return { tone: "quiet", text: "Checking" };
  if (status.readiness === "unsupported" || status.readiness === "no-adapter") return { tone: "bad", text: "Unavailable" };
  if (status.readiness === "bluetooth-off") return { tone: "warn", text: "Bluetooth off" };
  if (status.readiness === "phone-away") return { tone: "warn", text: "Phone not connected" };
  return { tone: "warn", text: "Needs setup" };
}

function Step({ done, children }: { done: boolean; children: React.ReactNode }) {
  return <li className={cn("flex items-center gap-2 text-[13px]", done ? "text-foreground" : "text-muted-foreground")}>
    {done ? <Check aria-hidden="true" className="size-4 text-status-on" /> : <Circle aria-hidden="true" className="size-3.5" />}
    <span>{children}<span className="sr-only">{done ? " (done)" : " (to do)"}</span></span>
  </li>;
}

/** Phone → Calls: set up talking through this computer. Linux only; Bluetooth Hands-Free only. */
export function CallAudioSetup({ status, client }: { status?: CallAudioStatus; client: Client }) {
  const [device, setDevice] = useState(status?.device || "");
  const id = useId();
  if (!status) return null;
  if (!status.supported) return status.windows
    ? <p className="m-0 mt-6 max-w-[60ch] text-[12.5px] leading-relaxed text-muted-foreground">Talking through this computer needs Bluetooth Hands-Free access that Windows keeps for Phone Link today, so call audio stays on your phone. Phone Link's Calls can be used alongside Saiph.</p>
    : null;
  const chosen = device || status.device;
  const save = (enabled: boolean, next = chosen) => client.call("settings.save", { link: { call_audio: { enabled, device: next } } });
  const { tone, text } = badge(status);
  const devices = status.devices || [];
  return <section aria-label="Talk through this computer" className="mt-6 grid gap-3 rounded-[14px] border border-border bg-card/60 px-5 py-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="grid min-w-0 gap-1">
        <h3 className="m-0 flex items-center gap-2 text-[14px] font-semibold"><Volume2 aria-hidden="true" className="size-4" />Talk through this computer <Badge tone={tone}>{text}</Badge></h3>
        <p className="m-0 max-w-[60ch] text-[12.5px] leading-relaxed text-muted-foreground">Uses Bluetooth, like a car kit. Call audio goes straight between your phone and this computer, never through Saiph Cloud or your server.</p>
      </div>
      <Switch aria-label="Use this computer for call audio" checked={status.enabled} disabled={!chosen && !status.enabled}
        onCheckedChange={(on) => void save(on).catch(() => {})} />
    </div>
    <p role="status" className="m-0 text-[13px]">{status.message}</p>
    <ol className="m-0 grid list-none gap-1.5 p-0" aria-label="Setup steps">
      <Step done={reached(status, "bluetooth-off")}>Bluetooth and PipeWire on this computer</Step>
      <Step done={reached(status, "needs-setup")}>This computer can act as a hands-free device</Step>
      <Step done={status.readiness === "ready"}>Your phone is connected with Phone calls on</Step>
    </ol>
    {status.setup.action && <div className="grid gap-2 rounded-[10px] bg-field/60 px-3.5 py-3 text-[12.5px] leading-relaxed">
      <p className="m-0">{status.setup.action === "write"
        ? <>Saiph can turn on the hands-free role for your account only. It adds one file, <code>{status.setup.file}</code>, and restarts WirePlumber, which interrupts sound for a moment. Nothing system-wide changes.</>
        : <>The hands-free role is turned on but Bluetooth has not picked it up. Restarting WirePlumber interrupts sound for a moment.</>}</p>
      <Action variant="secondary" size="sm" className="justify-self-start" run={() => client.call("call_audio.setup", {})}>
        {status.setup.action === "write" ? "Turn on hands-free" : "Restart WirePlumber"}</Action>
    </div>}
    {reached(status, "needs-setup") && <div className="grid gap-1.5">
      <label htmlFor={id} className="text-[12.5px] font-medium">Phone</label>
      <Select value={chosen || undefined} onValueChange={(value) => { setDevice(value); void save(status.enabled, value).catch(() => {}); }} disabled={!devices.length}>
        <SelectTrigger id={id} className="w-72 max-w-full"><SelectValue placeholder="Choose a paired Bluetooth phone" /></SelectTrigger>
        <SelectContent>{devices.map((row) => <SelectItem key={row.address} value={row.address}>{row.name}{row.gateway ? "" : " (no phone calls)"}</SelectItem>)}</SelectContent>
      </Select>
      {!devices.length && <small className="text-[12px] text-muted-foreground">Pair your phone with this computer in Bluetooth settings first, then keep Phone calls on for it on your phone.</small>}
    </div>}
    {!status.enabled && status.phone_connected && <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">While your phone is connected to this computer for calls, it may send call audio here. To stop that, turn off Phone calls for this computer in your phone's Bluetooth settings.</p>}
    {status.error && <p className="inline-error m-0">{status.error}</p>}
    <div className="flex flex-wrap items-center gap-2">
      <Action variant="ghost" size="sm" run={() => client.call("call_audio.refresh", {})} disabled={status.checking}>Check again</Action>
      {status.setup.applied && <Action variant="ghost" size="sm" run={() => client.call("call_audio.remove_setup", {})}>Remove Saiph's hands-free file</Action>}
    </div>
    <details className="text-[12px] text-muted-foreground">
      <summary className="cursor-pointer select-none">Details</summary>
      <p className="m-0 mt-1.5">PipeWire {status.versions.pipewire || "not found"} · WirePlumber {status.versions.wireplumber || "not found"} · BlueZ {status.versions.bluez || "not found"} · call control: {status.call_control === "hfp" ? "Bluetooth and Saiph" : "Saiph on your phone"}</p>
      {status.issues.length > 0 && <ul className="m-0 mt-1 pl-4">{status.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
    </details>
  </section>;
}

/** Where the current call's audio is, with a way to bring it here. */
export function CallAudioSession({ status, live, client }: { status?: CallAudioStatus; live: boolean; client: Client }) {
  if (!callAudioOn(status) || !status) return null;
  const { state, message, codec } = status.session;
  if (state === "idle" || state === "ringing") return null;
  if (state === "here") return <small role="status" className="basis-full text-[12.5px] text-status-on">Talking through this computer{codec ? ` · ${codec}` : ""}. Switch back from your phone's call screen.</small>;
  return <div role="status" className="flex basis-full flex-wrap items-center gap-2 text-[12.5px] text-muted-foreground">
    <span className={state === "failed" ? "inline-error" : undefined}>{message}</span>
    {live && state !== "connecting" && status.call_control === "hfp" && <Action variant="tonal" size="sm" run={() => client.call("call_audio.move_here", {})}>Move audio here</Action>}
  </div>;
}
