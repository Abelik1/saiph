// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import { BellOff, BellRing, MapPin, Music2, Pause, Play, SkipBack, SkipForward, Vibrate, VolumeX } from "lucide-react";
import type { Client, PhoneStatus } from "./types";
import type { PhoneFeatureState } from "./PhoneTabs";
import { Action } from "./ui";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Eyebrow } from "@/components/ui/item";

type PhoneDevice = { id: string; name: string; online: boolean; capabilities: string[]; hosted?: boolean; status?: PhoneStatus | null; ringing?: boolean };
const modes = [["ring", "Ring", BellRing], ["vibrate", "Vibrate", Vibrate], ["silent", "Silent", VolumeX]] as const;

function Ringer({ phone, mode, client }: { phone: PhoneDevice; mode?: string; client: Client }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function choose(next: string) {
    if (!next || next === mode) return;
    setPending(true); setError("");
    try { await client.call("phone.ringer", { device_id: phone.id, mode: next }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setPending(false); }
  }
  return <div className="grid gap-2">
    <Eyebrow>Sound</Eyebrow>
    <ToggleGroup type="single" value={mode || ""} onValueChange={(next) => void choose(next)} aria-label="Phone sound" disabled={!phone.online || pending} className="w-full">
      {modes.map(([value, label, Icon]) => <ToggleGroupItem key={value} value={value} className="flex-1"><Icon aria-hidden="true" />{label}</ToggleGroupItem>)}
    </ToggleGroup>
    {error && <span className="inline-error" role="alert">{error}</span>}
  </div>;
}

/** One Phone Link-style quick action: an icon tile with a short label underneath. */
function Tile({ label, title, pressed, disabled, run, children }: { label: string; title: string; pressed?: boolean; disabled: boolean; run: () => Promise<unknown>; children: React.ReactNode }) {
  return <div className="grid justify-items-center gap-1 text-center">
    <Action variant={pressed ? "default" : "tonal"} size="icon" className="size-11 rounded-full [&_svg]:size-[18px]" title={title} ariaLabel={label}
      role={pressed === undefined ? undefined : "switch"} ariaChecked={pressed} disabled={disabled} run={run}>{children}</Action>
    <small className="text-[11.5px] leading-tight text-muted-foreground">{label}</small>
  </div>;
}

/** Why a quick action is greyed out, in the words of the step that fixes it. */
export function quickHint(phone: PhoneDevice): string {
  if (!phone.online) return phone.status?.paused ? "Paused on mobile data. Quick actions return when your phone is on Wi-Fi."
    : "Reconnect your phone to use quick actions.";
  // Hub and Saiph Cloud phones send the same status; its quick actions are merged into the capabilities.
  if (!phone.status) return "";
  const missing = [!phone.capabilities.includes("dnd") && "Do Not Disturb access (for sound and Do Not Disturb)", !phone.capabilities.includes("media") && "notification access (for music)"].filter(Boolean);
  return missing.length ? `To use every quick action, allow ${missing.join(" and ")} in Saiph on your phone.` : "";
}

/** The phone's quick actions, sound mode and media, controlled from this computer. */
export function PhonePanel({ features, phone, client, audio = true }: { features?: PhoneFeatureState; phone?: PhoneDevice; client: Client; audio?: boolean }) {
  if (!phone) return null;
  const sessions = features?.media?.find((row) => row.device_id === phone.id)?.sessions || [];
  const session = audio ? sessions.find((row) => row.playing) || sessions[0] : undefined;
  const ringer = features?.ringers?.find((row) => row.device_id === phone.id)?.mode;
  const has = (capability: string) => phone.capabilities.includes(capability);
  const media = phone.online && has("media");
  const control = (action: string) => client.call("phone.media", { device_id: phone.id, source: session!.source, action });
  const dnd = has("dnd") && typeof phone.status?.dnd === "boolean" ? phone.status.dnd : undefined;
  const hint = quickHint(phone);
  if (!has("ringer") && !session && !has("ring") && dnd === undefined) return null;
  return <>
    {(has("ring") || dnd !== undefined) && <div className="flex flex-wrap gap-4" role="group" aria-label="Quick actions">
      {dnd !== undefined && <Tile label="Do Not Disturb" title={(dnd ? "Turn off" : "Turn on") + " Do Not Disturb on " + phone.name} pressed={dnd}
        disabled={!phone.online} run={() => client.call("phone.dnd", { device_id: phone.id, active: !dnd })}><BellOff /></Tile>}
      {/* While it rings (only newer phones say so), the same tile stops it, as Stop on the phone does. */}
      {has("ring") && (phone.ringing
        ? <Tile label="Stop ringing" title={"Stop ringing " + phone.name} pressed
            disabled={!phone.online} run={() => client.call("phone.ring.stop", { device_id: phone.id })}><BellOff /></Tile>
        : <Tile label="Find phone" title={"Ring " + phone.name + " loudly, even on silent, so you can find it"}
            disabled={!phone.online} run={() => client.call("phone.ring", { device_id: phone.id })}><MapPin /></Tile>)}
    </div>}
    {has("ringer") && <Ringer phone={phone} mode={ringer} client={client} />}
    {session && <section className="flex items-center gap-3 rounded-[12px] border border-border bg-field/50 p-3" aria-label="Now playing on your phone">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-[10px] text-primary-foreground [background-image:var(--primary-gradient)] [&_svg]:size-[18px]"><Music2 aria-hidden="true" /></span>
      <div className="grid min-w-0 flex-1 leading-tight">
        <small className="truncate text-[11px] text-muted-foreground">{session.app || "Now playing"}</small>
        <b className="truncate text-[13px] font-medium">{session.title || "Unknown title"}</b>
        {session.artist && <span className="truncate text-[12px] text-muted-foreground">{session.artist}</span>}
      </div>
      <div className="flex shrink-0 items-center">
        <Action variant="ghost" size="icon-sm" ariaLabel="Previous track" disabled={!media || !session.can_previous} run={() => control("previous")}><SkipBack /></Action>
        {session.playing
          ? <Action variant="ghost" size="icon-sm" ariaLabel="Pause" disabled={!media || !session.can_pause} run={() => control("pause")}><Pause /></Action>
          : <Action variant="ghost" size="icon-sm" ariaLabel="Play" disabled={!media || !session.can_play} run={() => control("play")}><Play /></Action>}
        <Action variant="ghost" size="icon-sm" ariaLabel="Next track" disabled={!media || !session.can_next} run={() => control("next")}><SkipForward /></Action>
      </div>
    </section>}
    {hint && <p className="m-0 text-[12px] leading-relaxed text-muted-foreground" role="status">{hint}</p>}
  </>;
}
