// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { BluetoothLockStatus, Client } from "./types";
import { Action, Card, Form } from "./ui";

/** Linux: lock when the Bluetooth-paired phone leaves. Windows has Dynamic Lock built in. */
export function BluetoothLockSettings({ status, client }: { status?: BluetoothLockStatus; client: Client }) {
  const [enabled, setEnabled] = useState(status?.enabled === true);
  const [device, setDevice] = useState(status?.device || "");
  const [seconds, setSeconds] = useState(status?.seconds ?? 30);
  if (!status) return null;
  if (status.windows) return <Card title="Lock when my phone leaves" subtitle="Windows does this itself with Dynamic Lock.">
    <p className="muted">Pair your phone with this computer over Bluetooth, then turn on Dynamic Lock in Windows sign-in options.</p>
    <Action run={() => client.call("continuity.platform", { action: "lock" })}>Open sign-in options</Action>
  </Card>;
  if (!status.supported) return null;
  return <Card title="Lock when my phone leaves" subtitle="Locks this session when your Bluetooth-paired phone is gone. It never unlocks.">
    <Form submit={() => client.call("settings.save", { link: { bt_lock: { enabled, device, seconds } } })}>
      <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />Lock this computer when my phone leaves</label>
      <label>Phone<select value={device} disabled={!enabled} onChange={(e) => setDevice(e.target.value)}><option value="">Choose a paired Bluetooth phone</option>{status.devices.map((d) => <option key={d.address} value={d.address}>{d.name}</option>)}</select></label>
      <label>Lock after (seconds)<input aria-label="Lock after seconds" type="number" min={10} max={600} value={seconds} disabled={!enabled} onChange={(e) => setSeconds(Number(e.target.value))} /></label>
      <button disabled={enabled && !device}>Save automatic lock</button>
    </Form>
    {!status.devices.length && <p className="muted">Pair your phone with this computer in Bluetooth settings first.</p>}
    {status.error && <p className="inline-error">{status.error}</p>}
  </Card>;
}
