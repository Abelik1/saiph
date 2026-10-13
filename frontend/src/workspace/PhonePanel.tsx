// SPDX-License-Identifier: AGPL-3.0-or-later
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import type { Client } from "./types";
import type { PhoneFeatureState } from "./PhoneTabs";
import { Action } from "./ui";

type PhoneDevice = { id: string; name: string; online: boolean; capabilities: string[] };
const modes = [["ring", "Ring"], ["vibrate", "Vibrate"], ["silent", "Silent"]] as const;

/** The phone's media and ringer, controlled from this computer. */
export function PhonePanel({ features, phone, client }: { features?: PhoneFeatureState; phone?: PhoneDevice; client: Client }) {
  if (!phone) return null;
  const sessions = features?.media?.find((row) => row.device_id === phone.id)?.sessions || [];
  const session = sessions.find((row) => row.playing) || sessions[0];
  const ringer = features?.ringers?.find((row) => row.device_id === phone.id)?.mode;
  const media = phone.online && phone.capabilities.includes("media");
  const control = (action: string) => client.call("phone.media", { device_id: phone.id, source: session!.source, action });
  return <>
    {phone.capabilities.includes("ringer") && <div className="phone-ringer" role="group" aria-label="Phone sound">
      {modes.map(([mode, label]) => <Action key={mode} className={"text-button" + (ringer === mode ? " selected" : "")} disabled={!phone.online || ringer === mode}
        run={() => client.call("phone.ringer", { device_id: phone.id, mode })}>{label}</Action>)}
    </div>}
    {session && <section className="phone-now-playing" aria-label="Now playing on your phone">
      <small>{session.app || "Now playing"}</small>
      <b>{session.title || "Unknown title"}</b>{session.artist && <span>{session.artist}</span>}
      <div className="actions">
        <Action className="icon-button" ariaLabel="Previous track" disabled={!media || !session.can_previous} run={() => control("previous")}><SkipBack size={16} /></Action>
        {session.playing
          ? <Action className="icon-button" ariaLabel="Pause" disabled={!media || !session.can_pause} run={() => control("pause")}><Pause size={16} /></Action>
          : <Action className="icon-button" ariaLabel="Play" disabled={!media || !session.can_play} run={() => control("play")}><Play size={16} /></Action>}
        <Action className="icon-button" ariaLabel="Next track" disabled={!media || !session.can_next} run={() => control("next")}><SkipForward size={16} /></Action>
      </div>
    </section>}
  </>;
}
