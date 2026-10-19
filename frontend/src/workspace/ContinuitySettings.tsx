// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import { FolderOpen } from "lucide-react";
import type { Client } from "./types";
import { Action, Form } from "./ui";
import { PreferenceCard as Card } from "./PreferenceCard";
import { SwitchRow } from "./SettingRow";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

type Config = {
  cloud?: { path?: string; enabled?: boolean; recordings?: boolean };
  link?: {
    focus?: boolean;
    dnd_sync?: boolean;
    auto_copy_codes?: boolean;
    battery_alerts?: boolean;
    pause_media_on_calls?: boolean;
    new_photo_notices?: boolean;
    ring_computer?: boolean;
    clipboard?: boolean;
    timezone?: string;
    wake_hour?: number;
    wake_minute?: number;
  };
};
type Backup = {
  configured: boolean;
  targets: Record<
    string,
    { ok?: boolean; completed_at?: number; error?: string }
  >;
  error?: string;
};
type Flag = "focus" | "dnd_sync" | "auto_copy_codes" | "battery_alerts" | "pause_media_on_calls" | "new_photo_notices" | "ring_computer" | "clipboard";

/** Switches between your phone and this computer, in the order people look for them. On unless noted. */
const phoneRows: [Flag, string, string][] = [
  ["clipboard", "Share clipboard", "Copy on one device and paste on your others."],
  ["auto_copy_codes", "Copy verification codes", "When a sign-in code arrives on your phone, copy it here automatically."],
  ["new_photo_notices", "New photos and screenshots", "Offer new screenshots and photos from your phone on this computer."],
  ["battery_alerts", "Low battery alerts", "Tell me when my phone's battery is low."],
  ["pause_media_on_calls", "Pause media during calls", "Pause music and videos on this computer while your phone is on a call."],
  ["ring_computer", "Find this computer", "Let your phone ring this computer to find it."],
];
const quietRows: [Flag, string, string][] = [
  ["dnd_sync", "Sync Do Not Disturb", "Turning Do Not Disturb on or off on one device changes it on your others."],
  ["focus", "Follow the shared sleep plan", "Quiet Saiph's notifications here during your quiet hours."],
];
const defaults: Record<Flag, boolean> = { focus: true, dnd_sync: true, auto_copy_codes: false, battery_alerts: true, pause_media_on_calls: true, new_photo_notices: true, ring_computer: true, clipboard: true };

const timezones = Intl.supportedValuesOf("timeZone");

/** Settings → Connections: what your phone and this computer share, laid out like Settings → Phone.
 * Every switch saves on its own; the quiet-hours times and the Cloud folder path save with their button. */
export function ContinuitySettings({
  settings,
  backup,
  client,
  workspace = true,
  platform,
}: {
  settings: Config;
  backup?: Backup;
  client: Client;
  workspace?: boolean;
  platform?: string;
}) {
  const link = settings.link || {};
  const cloud = settings.cloud || {};
  const on = (flag: Flag) => link[flag] ?? defaults[flag];
  // Workspace's settings store replaces the whole object, so it is sent in full there.
  const saveLink = (change: Config["link"]) => client.call("settings.save", { link: workspace ? { ...link, ...change } : change });
  const saveCloud = (change: Config["cloud"]) => client.call("settings.save", { cloud: workspace ? { ...cloud, ...change } : change });
  const [path, setPath] = useState(cloud.path || "");
  const [timezone, setTimezone] = useState(link.timezone || "Europe/London");
  const [wakeTime, setWakeTime] = useState(
    () => `${String(link.wake_hour ?? 7).padStart(2, "0")}:${String(link.wake_minute ?? 0).padStart(2, "0")}`,
  );
  const ids = useId();
  const switches = (rows: [Flag, string, string][]) => rows.map(([flag, title, detail]) =>
    <SwitchRow key={flag} title={title} detail={detail} checked={on(flag)} change={(value) => saveLink({ [flag]: value })} />);
  return (
    <>
      <Card title="Phone and this computer" subtitle="What your phone and this computer share with each other.">
        <div>{switches(phoneRows)}</div>
      </Card>
      <Card title="Quiet hours" subtitle="Keep notifications quiet on all your devices at the same time.">
        <div>{switches(quietRows)}</div>
        <Form
          className="grid gap-4"
          successMessage="Quiet hours saved."
          submit={async () => {
            try {
              new Intl.DateTimeFormat(undefined, { timeZone: timezone });
            } catch {
              throw new Error("Choose a valid timezone from the suggestions.");
            }
            if (!/^\d{2}:\d{2}$/.test(wakeTime)) throw new Error("Choose a time for quiet hours to end.");
            const [wake_hour, wake_minute] = wakeTime.split(":").map(Number);
            await saveLink({ timezone, wake_hour, wake_minute });
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Focus timezone" htmlFor={ids + "-timezone"}>
              <Input id={ids + "-timezone"} list={ids + "-zones"} required disabled={!on("focus")} value={timezone}
                placeholder="Search a city or timezone" onChange={(e) => setTimezone(e.target.value)} />
              <datalist id={ids + "-zones"}>
                {Array.from(new Set([link.timezone || "Europe/London", ...timezones])).map((zone) => <option key={zone} value={zone} />)}
              </datalist>
            </Field>
            <Field label="Quiet hours end" htmlFor={ids + "-wake"}>
              <Input id={ids + "-wake"} type="time" required disabled={!on("focus")} value={wakeTime} onChange={(e) => setWakeTime(e.target.value)} />
            </Field>
          </div>
          <Button type="submit" variant="secondary" size="sm" className="justify-self-start" disabled={!on("focus")}>Save quiet hours</Button>
        </Form>
        <p>
          {platform === "linux" ? "Focus quiets Saiph. GNOME Do Not Disturb changes are shared with your phone."
            : "Focus quiets Saiph. Configure Windows Do Not Disturb to quiet other apps; Saiph shares changes without switching it for you."}
        </p>
      </Card>
      <Card title="Cloud folders" subtitle="Files in your Cloud folder sync with your other devices.">
        <div>
          <SwitchRow title="Use Cloud folders" detail="Keep a Cloud folder on this computer." checked={cloud.enabled !== false}
            change={(enabled) => saveCloud({ enabled })} />
          {workspace && <SwitchRow title="Transcribe recordings" detail="Transcribe finished Cloud recordings automatically." checked={cloud.recordings !== false}
            change={(recordings) => saveCloud({ recordings })} />}
        </div>
        <Form className="grid gap-3" successMessage="Cloud folder saved." submit={() => saveCloud({ path })}>
          <Field label="Cloud folder" htmlFor={ids + "-folder"}>
            <div className="flex gap-2">
              <Input id={ids + "-folder"} value={path} maxLength={4096} placeholder="Cloud in your home folder" onChange={(e) => setPath(e.target.value)} />
              <Action
                variant="secondary"
                ariaLabel="Browse Cloud folder"
                run={async () => {
                  const chosen = await client.call<{ path?: string }>("dialog.directory", { title: "Choose your Cloud folder" });
                  if (chosen.path) setPath(chosen.path);
                }}
              >
                <FolderOpen />Browse…
              </Action>
            </div>
          </Field>
          <Button type="submit" variant="secondary" size="sm" className="justify-self-start">Save folder</Button>
        </Form>
      </Card>
      {workspace && (
        <Card title="This computer">
          <div className="actions">
            <Action run={() => client.call("continuity.platform", { action: "find" })}>Find my phone</Action>
            {platform !== "linux" && (
              <Action run={() => client.call("continuity.platform", { action: "lock" })}>Windows Dynamic Lock settings</Action>
            )}
          </div>
          <div className="settings-row">
            <span>Encrypted backups</span>
            <span>{backup?.configured ? "Configured" : "One-time private setup required"}</span>
          </div>
          {backup?.error && <p className="muted">{backup.error}</p>}
          {Object.entries(backup?.targets || {}).map(([name, result]) => (
            <div className="settings-row" key={name}>
              <span>{name === "pi" ? "Pi backup" : "Offsite backup"}</span>
              <span>
                {result.ok && result.completed_at
                  ? new Date(result.completed_at * 1000).toLocaleString()
                  : "Waiting for a successful backup"}
              </span>
            </div>
          ))}
        </Card>
      )}
    </>
  );
}
