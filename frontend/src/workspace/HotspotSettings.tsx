// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import type { Client, HotspotStatus } from "./types";
import { Action, Form } from "./ui";
import { PreferenceCard as Card } from "./PreferenceCard";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Field } from "@/components/ui/field";

/** Uses a Wi-Fi network the computer already saved; passwords stay with the operating system. */
export function HotspotSettings({ hotspot, client }: { hotspot?: HotspotStatus; client: Client }) {
  const [profile, setProfile] = useState(hotspot?.profile || "");
  const [auto, setAuto] = useState(hotspot?.auto === true);
  const id = useId();
  if (!hotspot) return null;
  const choices = hotspot.profiles.includes(profile) || !profile ? hotspot.profiles : [profile, ...hotspot.profiles];
  return <Card title="Phone hotspot" subtitle="Get this computer online through your phone.">
    {!hotspot.supported ? <p className="muted">Hotspot connection needs Windows or NetworkManager.</p> : <>
      <p role="status" className="muted">{hotspot.active && hotspot.active === hotspot.profile ? "Connected to your phone's hotspot." : hotspot.profile ? "Not connected to your phone's hotspot." : "Join your phone's hotspot once in this computer's Wi-Fi settings, then choose it here."}</p>
      <Form submit={() => client.call("settings.save", { link: { hotspot: { profile, auto } } })}>
        <Field label="Phone hotspot network" htmlFor={id}>
          <Select value={profile || undefined} onValueChange={setProfile} disabled={!choices.length}>
            <SelectTrigger id={id}><SelectValue placeholder={choices.length ? "Choose a saved Wi-Fi network" : "No saved Wi-Fi networks"} /></SelectTrigger>
            <SelectContent>{choices.map(name => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <label className="check"><input type="checkbox" checked={auto} disabled={!profile} onChange={event => setAuto(event.target.checked)} />Reconnect automatically when this computer has no network</label>
        <Button type="submit" variant="secondary" disabled={!profile} className="justify-self-start">Save hotspot</Button>
      </Form>
      {hotspot.profile && <Action run={() => client.call("hotspot.connect")}>Connect to {hotspot.profile}</Action>}
      {hotspot.error && <p className="inline-error">{hotspot.error}</p>}
      <p>Turn on the hotspot using your phone's quick settings.</p>
    </>}
  </Card>;
}
