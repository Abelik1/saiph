// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client } from "./types";
import { Action, Card, Form } from "./ui";

type Config = { cloud?: { path?: string; enabled?: boolean; recordings?: boolean }; link?: { focus?: boolean; dnd_sync?: boolean; auto_copy_codes?: boolean; battery_alerts?: boolean; pause_media_on_calls?: boolean; new_photo_notices?: boolean; ring_computer?: boolean; clipboard?:boolean; timezone?: string; wake_hour?: number; wake_minute?: number } };
type Backup = { configured: boolean; targets: Record<string, { ok?: boolean; completed_at?: number; error?: string }>; error?: string };

export function ContinuitySettings({ settings, backup, client, workspace = true }: { settings: Config; backup?: Backup; client: Client; workspace?: boolean }) {
  const [cloud, setCloud] = useState(settings.cloud || {});
  const [focus, setFocus] = useState(settings.link?.focus !== false);
  const [clipboard, setClipboard] = useState(settings.link?.clipboard !== false);
  const [dnd, setDnd] = useState(settings.link?.dnd_sync !== false);
  const [codes, setCodes] = useState(settings.link?.auto_copy_codes === true);
  const [battery, setBattery] = useState(settings.link?.battery_alerts !== false);
  const [calls, setCalls] = useState(settings.link?.pause_media_on_calls !== false);
  const [photos, setPhotos] = useState(settings.link?.new_photo_notices !== false);
  const [ring, setRing] = useState(settings.link?.ring_computer !== false);
  const [timezone, setTimezone] = useState(settings.link?.timezone || "Europe/London");
  const [wakeHour, setWakeHour] = useState(settings.link?.wake_hour ?? 7);
  return <Card title="Cloud and continuity" subtitle="These preferences belong to this computer.">
    <Form submit={() => client.call("settings.save", { cloud: workspace ? cloud : {path:cloud.path,enabled:cloud.enabled}, link: { ...(workspace ? settings.link : {}), focus, dnd_sync: dnd, auto_copy_codes: codes, battery_alerts: battery, pause_media_on_calls: calls, new_photo_notices: photos, ring_computer: ring, clipboard, timezone, wake_hour: wakeHour, wake_minute: settings.link?.wake_minute ?? 0 } })}>
      <label>Cloud folder<input value={cloud.path || ""} placeholder="Cloud in your home folder" onChange={e => setCloud({ ...cloud, path: e.target.value })} /></label>
      <label className="check"><input type="checkbox" checked={cloud.enabled !== false} onChange={e => setCloud({ ...cloud, enabled: e.target.checked })} />Use Cloud folders</label>
      {workspace && <label className="check"><input type="checkbox" checked={cloud.recordings !== false} onChange={e => setCloud({ ...cloud, recordings: e.target.checked })} />Transcribe finished Cloud recordings automatically</label>}
      <label className="check"><input type="checkbox" checked={focus} onChange={e => setFocus(e.target.checked)} />Follow the shared sleep plan for quiet notifications</label>
      <label className="check"><input type="checkbox" checked={dnd} onChange={e => setDnd(e.target.checked)} />Sync Do Not Disturb with my devices</label>
      <label className="check"><input type="checkbox" checked={codes} onChange={e => setCodes(e.target.checked)} />Copy verification codes from my phone automatically</label>
      <label className="check"><input type="checkbox" checked={battery} onChange={e => setBattery(e.target.checked)} />Tell me when my phone's battery is low</label>
      <label className="check"><input type="checkbox" checked={calls} onChange={e => setCalls(e.target.checked)} />Pause music and videos here during phone calls</label>
      <label className="check"><input type="checkbox" checked={photos} onChange={e => setPhotos(e.target.checked)} />Offer new screenshots and photos from my phone</label>
      <label className="check"><input type="checkbox" checked={ring} onChange={e => setRing(e.target.checked)} />Let my phone ring this computer to find it</label>
      <label className="check"><input type="checkbox" checked={clipboard} onChange={e => setClipboard(e.target.checked)} />Share clipboard across my devices</label>
      <div className="form-grid"><label>Focus timezone<input value={timezone} onChange={e => setTimezone(e.target.value)} /></label><label>Quiet hours end<input aria-label="Quiet hours end" type="number" min={0} max={23} value={wakeHour} onChange={e => setWakeHour(Number(e.target.value))} /></label></div>
      <button>Save preferences</button>
    </Form>
    <p className="muted">Windows quiets Saiph notifications during Focus. Set Windows automatic Do Not Disturb once to include other apps. Turning Windows or GNOME Do Not Disturb on or off is shared with your phone; Saiph does not change Windows Do Not Disturb itself.</p>
    {workspace && <><div className="actions"><Action run={() => client.call("continuity.platform", { action: "find" })}>Find my phone</Action><Action run={() => client.call("continuity.platform", { action: "lock" })}>Windows Dynamic Lock settings</Action></div>
    <div className="settings-row"><span>Encrypted backups</span><span>{backup?.configured ? "Configured" : "One-time private setup required"}</span></div>
    {backup?.error && <p className="muted">{backup.error}</p>}
    {Object.entries(backup?.targets || {}).map(([name, result]) => <div className="settings-row" key={name}><span>{name === "pi" ? "Pi backup" : "Offsite backup"}</span><span>{result.ok && result.completed_at ? new Date(result.completed_at * 1000).toLocaleString() : "Waiting for a successful backup"}</span></div>)}
    </>}
  </Card>;
}
