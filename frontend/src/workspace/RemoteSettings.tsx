// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client, RemoteStatus, State } from "./types";
import { Card, Form } from "./ui";

const warnings: Record<string, string> = {
  system: "Lets the phone lock this computer.",
  keyboard: "Lets the phone type into whichever app is in front. Turn this on only for phones you fully trust.",
  touchpad: "Lets the phone move the pointer and click. Turn this on only for phones you fully trust.",
};

/** Off by default. The owner chooses the phones and the fixed controls a phone may use. */
export function RemoteSettings({ remote, state, client }: { remote?: RemoteStatus; state: State; client: Client }) {
  const [enabled, setEnabled] = useState(remote?.enabled === true);
  const [devices, setDevices] = useState<string[]>(remote?.devices || []);
  const [adapters, setAdapters] = useState<Record<string, boolean>>(() => Object.fromEntries(Object.entries(remote?.adapters || {}).map(([id, value]) => [id, value.enabled])));
  if (!remote) return null;
  const phones = (state.phone?.devices || []).filter(device => device.id !== state.settings?.hub?.device_id);
  const toggle = (id: string, on: boolean) => setDevices(current => on ? [...current.filter(value => value !== id), id] : current.filter(value => value !== id));
  return <Card title="Phone remote" subtitle="Control apps on this computer from your phone with fixed buttons, not screen sharing.">
    <Form submit={() => client.call("settings.save", { link: { remote: { enabled, devices, adapters } } })}>
      <label className="check"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />Allow phone remote control</label>
      <fieldset disabled={!enabled}><legend>Phones that may control this computer</legend>
        {phones.length ? phones.map(device => <label className="check" key={device.id}><input type="checkbox" checked={devices.includes(device.id)} onChange={event => toggle(device.id, event.target.checked)} />{device.name}</label>)
          : <p className="muted">Pair a phone first.</p>}
      </fieldset>
      <fieldset disabled={!enabled}><legend>Apps offered to the phone</legend>
        {Object.entries(remote.adapters).map(([id, adapter]) => <label className="check" key={id}><input type="checkbox" checked={adapters[id] === true} onChange={event => setAdapters(current => ({ ...current, [id]: event.target.checked }))} />
          {adapter.name}{!adapter.available && <small className="muted"> · unavailable on this computer</small>}{warnings[id] && <small className="muted"> · {warnings[id]}</small>}</label>)}
      </fieldset>
      <button>Save remote preferences</button>
    </Form>
    <p className="muted">To lock this computer from your phone (home screen or the Lock computer quick setting), allow the phone and turn on This computer.</p>
    {remote.wayland && <p className="muted">Wayland does not let apps send keys, so presentation, web video and typing controls are unavailable. Media controls still work.</p>}
    {remote.last && <p className="muted" role="status">Last control: {remote.adapters[remote.last.app]?.name || remote.last.app} · {remote.last.control} at {new Date(remote.last.at * 1000).toLocaleTimeString()}</p>}
  </Card>;
}
