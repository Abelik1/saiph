// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, MicrophoneStatus, Settings } from "./types";
import { Action, Card } from "./ui";
import { SettingsShortcut } from "./Navigation";

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
  return (
    <div className="phone-microphone">
      {microphone?.running ? (
        <>
          <p role="status">
            {deviceName || "Phone"} microphone ·{" "}
            {microphone.muted ? "Muted — capture stopped" : "Capturing audio"}
          </p>
          <Action
            className="text-button"
            run={() =>
              client.call("microphone.mute", { muted: !microphone.muted })
            }
          >
            {microphone.muted
              ? "Unmute phone microphone"
              : "Mute phone microphone"}
          </Action>
          <Action
            className="text-button"
            run={() => client.call("microphone.stop")}
          >
            Stop phone microphone
          </Action>
        </>
      ) : (
        <>
          <Action
            className="text-button"
            disabled={!deviceId || !microphone?.available}
            run={() => client.call("microphone.start", { device_id: deviceId })}
          >
            Use phone as microphone
          </Action>
          <p className="muted" role="status">
            {!deviceId
              ? "Reconnect your phone to start the microphone."
              : microphone?.message ||
                "Set up the microphone once in Settings."}
          </p>
          {!microphone?.available && (
            <SettingsShortcut target="Devices">
              Set up phone microphone
            </SettingsShortcut>
          )}
        </>
      )}
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
      <p>
        Capture starts only when you choose it on Phone. Mute stops phone
        capture. Stop removes Saiph’s temporary audio route. Camera sharing is
        separate.
      </p>
      <p className="muted">{microphone?.message}</p>
      <p>Phone microphone sharing: {enabled ? "Enabled" : "Off"}</p>
      <Action
        run={() =>
          client.call("settings.save", {
            link: { microphone: { enabled: !enabled } },
          })
        }
      >
        {enabled ? "Turn off phone microphone" : "Enable phone microphone"}
      </Action>
      <details className="device-setup-guide">
        <summary>One-time microphone setup</summary>
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
          className="text-button"
          run={() => client.call("microphone.help")}
        >
          Open microphone setup guide
        </Action>
      </details>
      <p className="muted">
        Use headphones to prevent feedback. Readiness does not prove audible
        meeting delivery. Microphone capture remains experimental until verified
        with your phone.
      </p>
    </Card>
  );
}
