// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import { BellRing, Music2, Pause, Play, SkipBack, SkipForward, Vibrate, VolumeX } from "lucide-react";
import type { Client } from "./types";
import type { PhoneFeatureState } from "./PhoneTabs";
import { Action } from "./ui";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Eyebrow } from "@/components/ui/item";

type PhoneDevice = { id: string; name: string; online: boolean; capabilities: string[] };
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

/** The phone's media and ringer, controlled from this computer. */
export function PhonePanel({ features, phone, client }: { features?: PhoneFeatureState; phone?: PhoneDevice; client: Client }) {
  if (!phone) return null;
  const sessions = features?.media?.find((row) => row.device_id === phone.id)?.sessions || [];
  const session = sessions.find((row) => row.playing) || sessions[0];
  const ringer = features?.ringers?.find((row) => row.device_id === phone.id)?.mode;
  const media = phone.online && phone.capabilities.includes("media");
  const control = (action: string) => client.call("phone.media", { device_id: phone.id, source: session!.source, action });
  if (!phone.capabilities.includes("ringer") && !session) return null;
  return <>
    {phone.capabilities.includes("ringer") && <Ringer phone={phone} mode={ringer} client={client} />}
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
  </>;
}
