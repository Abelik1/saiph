// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client, HotspotStatus } from "./types";
import { Action, Card, Form } from "./ui";

/** Uses a Wi-Fi network the computer already saved; passwords stay with the operating system. */
export function HotspotSettings({ hotspot, client }: { hotspot?: HotspotStatus; client: Client }) {
  const [profile, setProfile] = useState(hotspot?.profile || "");
  const [auto, setAuto] = useState(hotspot?.auto === true);
  if (!hotspot) return null;
  const choices = hotspot.profiles.includes(profile) || !profile ? hotspot.profiles : [profile, ...hotspot.profiles];
  return <Card title="Phone hotspot" subtitle="Get this computer online through your phone.">
    {!hotspot.supported ? <p className="muted">Hotspot connection needs Windows or NetworkManager.</p> : <>
      <p role="status" className="muted">{hotspot.active && hotspot.active === hotspot.profile ? "Connected to your phone's hotspot." : hotspot.profile ? "Not connected to your phone's hotspot." : "Join your phone's hotspot once in this computer's Wi-Fi settings, then choose it here."}</p>
      <Form submit={() => client.call("settings.save", { link: { hotspot: { profile, auto } } })}>
        <label>Phone hotspot network<select value={profile} onChange={event => setProfile(event.target.value)}><option value="">Choose a saved Wi-Fi network</option>{choices.map(name => <option key={name} value={name}>{name}</option>)}</select></label>
        <label className="check"><input type="checkbox" checked={auto} disabled={!profile} onChange={event => setAuto(event.target.checked)} />Reconnect automatically when this computer has no network</label>
        <button disabled={!profile}>Save hotspot</button>
      </Form>
      {hotspot.profile && <Action run={() => client.call("hotspot.connect")}>Connect to {hotspot.profile}</Action>}
      {hotspot.error && <p className="inline-error">{hotspot.error}</p>}
      <p className="muted">Android doesn't let apps switch the hotspot on. Use Hotspot settings in the Saiph phone app, or your phone's quick settings.</p>
    </>}
  </Card>;
}
