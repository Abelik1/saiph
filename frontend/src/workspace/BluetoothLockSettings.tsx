// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import type { BluetoothLockStatus, Client } from "./types";
import { Action, Form } from "./ui";
import { PreferenceCard as Card } from "./PreferenceCard";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Field } from "@/components/ui/field";

/** Linux: lock when the Bluetooth-paired phone leaves. Windows has Dynamic Lock built in. */
export function BluetoothLockSettings({ status, client }: { status?: BluetoothLockStatus; client: Client }) {
  const [enabled, setEnabled] = useState(status?.enabled === true);
  const [device, setDevice] = useState(status?.device || "");
  const [seconds, setSeconds] = useState(status?.seconds ?? 30);
  const id = useId();
  if (!status) return null;
  if (status.windows) return <Card title="Lock when my phone leaves" subtitle="Windows does this itself with Dynamic Lock.">
    <p className="muted">Pair your phone with this computer over Bluetooth, then turn on Dynamic Lock in Windows sign-in options.</p>
    <Action run={() => client.call("continuity.platform", { action: "lock" })}>Open sign-in options</Action>
  </Card>;
  if (!status.supported) return null;
  return <Card title="Lock when my phone leaves" subtitle="Locks this session when your Bluetooth-paired phone is gone. It never unlocks.">
    <Form submit={() => client.call("settings.save", { link: { bt_lock: { enabled, device, seconds } } })}>
      <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />Lock this computer when my phone leaves</label>
      <Field label="Phone" htmlFor={id}>
        <Select value={device || undefined} onValueChange={setDevice} disabled={!enabled || !status.devices.length}>
          <SelectTrigger id={id}><SelectValue placeholder="Choose a paired Bluetooth phone" /></SelectTrigger>
          <SelectContent>{status.devices.map((d) => <SelectItem key={d.address} value={d.address}>{d.name}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      <label>Lock after (seconds)<input aria-label="Lock after seconds" type="number" min={10} max={600} value={seconds} disabled={!enabled} onChange={(e) => setSeconds(Number(e.target.value))} /></label>
      <Button type="submit" variant="secondary" disabled={enabled && !device} className="justify-self-start">Save automatic lock</Button>
    </Form>
    {!status.devices.length && <p className="muted">Pair your phone with this computer in Bluetooth settings first.</p>}
    {status.error && <p className="inline-error">{status.error}</p>}
  </Card>;
}
