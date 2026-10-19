// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, MicrophoneStatus, Settings } from "./types";
import { Action } from "./ui";
import { PreferenceCard as Card } from "./PreferenceCard";
import { SettingsShortcut } from "./Navigation";
import { Mic, MicOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";
import { Disclosure } from "@/components/ui/disclosure";

export function PhoneMicrophone({
  microphone,
  deviceId,
  deviceName,
  client,
}: {
  microphone?: MicrophoneStatus;
  deviceId?: string;
  deviceName?: string;
  client: Client;
}) {
  const running = microphone?.running;
  return (
    <div className="grid gap-3 p-4">
      <Item size="flush">
        <ItemMedia>{running && microphone?.muted ? <MicOff /> : <Mic />}</ItemMedia>
        <ItemContent>
          <ItemTitle className="flex items-center gap-2">Microphone {running && <Badge tone={microphone?.muted ? "warn" : "good"}>{microphone?.muted ? "Muted" : "Live"}</Badge>}</ItemTitle>
          <ItemDescription role="status">
            {running
              ? `${deviceName || "Phone"} microphone · ${microphone?.muted ? "Muted — capture stopped" : "Capturing audio"}`
              : !deviceId
                ? "Reconnect your phone to start the microphone."
                : microphone?.message || "Set up the microphone once in Settings."}
          </ItemDescription>
        </ItemContent>
      </Item>
      <ItemActions className="flex-wrap pl-12">
        {running ? (
          <>
            <Action variant="tonal" size="sm" run={() => client.call("microphone.mute", { muted: !microphone?.muted })}>
              {microphone?.muted ? "Unmute phone microphone" : "Mute phone microphone"}
            </Action>
            <Action variant="destructive" size="sm" run={() => client.call("microphone.stop")}>
              Stop phone microphone
            </Action>
          </>
        ) : (
          <>
            <Action variant="tonal" size="sm" disabled={!deviceId || !microphone?.available}
              run={() => client.call("microphone.start", { device_id: deviceId })}>
              Use phone as microphone
            </Action>
            {!microphone?.available && (
              <SettingsShortcut target="Devices">
                Set up phone microphone
              </SettingsShortcut>
            )}
          </>
        )}
      </ItemActions>
    </div>
  );
}

export function MicrophoneSettings({
  settings,
  microphone,
  client,
  platform,
}: {
  settings: Settings;
  microphone?: MicrophoneStatus;
  client: Client;
  platform?: string;
}) {
  const enabled = settings.link?.microphone?.enabled === true;
  return (
    <Card
      title="Phone microphone"
      subtitle="Optional audio input for your meeting app."
    >
      <p role="status"><Badge tone={enabled ? "good" : "quiet"}>{enabled ? "Enabled" : "Off"}</Badge></p>
      <p>Start and stop capture from Phone. Mute stops microphone capture.</p>
      {microphone?.message && <p>{microphone.message}</p>}
      <Action
        variant="tonal"
        run={() =>
          client.call("settings.save", {
            link: { microphone: { enabled: !enabled } },
          })
        }
      >
        {enabled ? "Turn off phone microphone" : "Enable phone microphone"}
      </Action>
      <Disclosure summary="Microphone setup">
        <p>Use scrcpy 3.3.4 with SDL2.</p>
        {platform !== "windows" && (
          <p>
            On Linux, install pactl and use your session’s PulseAudio or
            PipeWire-Pulse server; Saiph creates its temporary input when
            capture starts. Choose Saiph Phone Microphone in your meeting app.
          </p>
        )}
        {platform !== "linux" && (
          <p>
            On Windows, install standard VB-CABLE from its publisher once and
            leave its endpoint names unchanged. Choose CABLE Output (VB-Audio
            Virtual Cable) in the meeting app. VB-CABLE is donationware with its
            own licence; it is not bundled with Saiph.
          </p>
        )}
        <Action
          variant="tonal"
          run={() => client.call("microphone.help")}
        >
          Open microphone setup guide
        </Action>
        <p>Use headphones to prevent feedback. Microphone sharing is experimental; check sound in your meeting app before use.</p>
      </Disclosure>
    </Card>
  );
}
