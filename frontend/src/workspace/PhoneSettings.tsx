// SPDX-License-Identifier: AGPL-3.0-or-later
import { ClipboardCopy, FolderOpen, Wifi } from "lucide-react";
import type { Client, State } from "./types";
import { Action } from "./ui";
import { PreferenceCard as Card } from "./PreferenceCard";
import { phonePreferences, type PhoneFeature } from "./phonePreferences";
import { ActionRow, SwitchRow as Row } from "./SettingRow";
import { Button } from "@/components/ui/button";

type Device = NonNullable<State["phone"]>["devices"][number];

const features: [PhoneFeature, string, string][] = [
  ["notifications", "Notifications", "See and reply to your phone's notifications on this computer."],
  ["messages", "Messages", "Read and send texts from this computer."],
  ["photos", "Photos", "See your phone's recent photos on this computer."],
  ["apps", "Apps", "Open your phone's apps on this computer."],
  ["calls", "Calls", "Answer, decline and make calls from this computer. Audio stays on your phone."],
];

/** The phone these settings act on: the online one first, as on the Phone page. */
export function settingsPhone(state: State): Device | undefined {
  const phones = state.phone?.devices.filter((d) => d.capabilities.includes("battery") || d.hosted) || [];
  return phones.find((d) => d.online) || phones[0];
}

/** Phone Link's Settings → Features and Additional settings, for this computer. */
export function PhoneSettings({ state, client, openTab }: { state: State; client: Client; openTab?: (tab: string) => void }) {
  const preferences = phonePreferences(state.settings);
  const phone = settingsPhone(state);
  const save = (phone_options: object) => client.call("settings.save", { link: { phone: phone_options } });
  const callsAvailable = Boolean(state.phone?.devices.some((d) => d.capabilities.includes("calls")));
  const has = (name: string) => Boolean(phone?.capabilities.includes(name));
  const cloudReason = !phone ? "Connect a phone first." : !phone.hosted ? "Available with a Saiph Cloud phone." : "";
  const offline = phone && !phone.online ? (phone.status?.paused
    ? "Your phone is paused on mobile data. Change this in Saiph on your phone: Status and quick controls."
    : `${phone.name} is offline. Change this in Saiph on your phone, or try again when it reconnects.`) : "";
  const mobileReason = cloudReason || offline || (!has("mobile_data") ? "Update Saiph on your phone, then turn on Status and quick controls there." : "");
  // Hotspot and wallpaper are shared quick actions (Hub and Saiph Cloud); Sync over mobile data is a Saiph Cloud setting.
  const hotspotReason = !phone ? "Connect a phone first." : offline || (!has("hotspot") ? "Update Saiph on your phone, then turn on Status and quick controls there." : "");
  const wallpaperReason = !preferences.wallpaper || !phone?.online || has("wallpaper") ? ""
    : !phone.hosted && !phone.status ? "Update Saiph on your phone to show its wallpaper here."
    : "Your phone doesn't let Saiph read its wallpaper. On Android 13 and later this needs All files access for Saiph (Android Settings → Apps → Saiph → Permissions).";
  const windows = state.platform === "windows";
  return <div className="columns">
    <Card title="Features" subtitle="Choose what this computer shows and syncs from your phone.">
      <div>
        {features.map(([name, title, detail]) => {
          const unavailable = name === "calls" && !callsAvailable;
          return <Row key={name} title={title} detail={detail} checked={preferences.features[name] && !unavailable} disabled={unavailable}
            reason={unavailable ? "Your phone doesn't share calls yet. In Saiph on your phone, turn on Texts and calls." : undefined}
            change={(value) => save({ features: { [name]: value } })} />;
        })}
      </div>
    </Card>
    <div className="grid gap-5">
      <Card title="Your phone" subtitle={phone ? `Settings for ${phone.name}.` : "Connect a phone to use these settings."}>
        <div>
          <Row title="Sync over mobile data" detail="Let Saiph Cloud sync while your phone uses mobile data. Off: it pauses until your phone is on Wi-Fi."
            checked={phone?.status?.mobile_data ?? true} disabled={Boolean(mobileReason)} reason={mobileReason}
            change={(allowed) => client.call("phone.mobile_data", { device_id: phone!.id, allowed })} />
          <Row title="Use phone wallpaper" detail="Show your phone's wallpaper in the header and behind the Phone page. Copies a small picture of it to this computer."
            checked={preferences.wallpaper} reason={wallpaperReason}
            change={async (value) => {
              await save({ wallpaper: value });
              if (value && phone?.online && has("wallpaper")) await client.call("phone.wallpaper", { device_id: phone.id });
            }} />
          <Row title="Audio player" detail="Show what's playing on your phone, with play, pause and skip." checked={preferences.audio_player}
            change={(value) => save({ audio_player: value })} />
          <ActionRow title="Transferred files" detail="Files your phone sends are saved in your Downloads folder.">
            <Action variant="secondary" size="sm" run={() => client.call("phone.files.folder")}><FolderOpen />Open folder</Action>
          </ActionRow>
          <ActionRow title="Instant hotspot" reason={hotspotReason}
            detail="Android doesn't let apps turn the hotspot on. Saiph asks your phone to show a notification that opens its hotspot settings.">
            <Action variant="secondary" size="sm" disabled={Boolean(hotspotReason)} run={() => client.call("phone.hotspot", { device_id: phone!.id })}><Wifi />Open on phone</Action>
          </ActionRow>
          <ActionRow title="Copy and paste between devices" detail="Share copied text and pictures with your phone.">
            <Button variant="secondary" size="sm" onClick={() => openTab?.("Connections")}><ClipboardCopy />Clipboard settings</Button>
          </ActionRow>
        </div>
      </Card>
      <Card title="Taskbar and tray" subtitle="How Saiph shows new phone activity on this computer.">
        <div>
          <Row title="Unread badge" detail="Show the number of phone notifications on Saiph's taskbar button." checked={windows && preferences.badges}
            disabled={!windows} reason={windows ? undefined : "Taskbar badges are available on Windows."} change={(value) => save({ badges: value })} />
          <Row title="Recent content" detail="Show your newest phone notifications in the tray icon's Phone menu." checked={preferences.recent}
            change={(value) => save({ recent: value })} />
        </div>
      </Card>
    </div>
  </div>;
}

/**
 * Settings → Advanced: scrcpy windows over authorised USB or wireless debugging, an explicit opt-in.
 * Off (the default), Saiph never offers scrcpy or adb; the phone screen uses the local network.
 */
export function UsbDebuggingSettings({ state, client }: { state: State; client: Client }) {
  const preferences = phonePreferences(state.settings);
  return <Card title="USB debugging (advanced)" subtitle="Separate phone app windows through scrcpy, for people who already use Android debugging.">
    <div>
      <Row title="Use USB debugging for phone apps" checked={preferences.usb_debugging}
        detail="Adds Use USB debugging (scrcpy) to Phone → Apps. Needs scrcpy on this computer and debugging allowed on the phone. Not needed for the phone screen, which works over your Wi-Fi."
        change={(value) => client.call("settings.save", { link: { phone: { usb_debugging: value } } })} />
    </div>
  </Card>;
}
