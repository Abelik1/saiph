// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { CameraConfig, CameraStatus, Client, DebugPhone } from "./types";
import { Action } from "./ui";
import { SettingsShortcut } from "./Navigation";
import { WirelessDebugging } from "./WirelessDebugging";

const connection = (phone: DebugPhone) =>
  phone.connection === "wifi" ? "Wi‑Fi" : "USB cable";

/**
 * `deviceId` is a phone paired through a self-hosted Hub. Without one (Saiph
 * Hosted, or no Hub) the camera uses a phone that has allowed this computer
 * over USB or wireless debugging; the video never leaves the cable or Wi‑Fi.
 */
export function PhoneCamera({
  camera,
  config,
  deviceId,
  client,
}: {
  camera?: CameraStatus;
  config?: CameraConfig;
  deviceId?: string;
  client: Client;
}) {
  const [facing, setFacing] = useState<NonNullable<CameraConfig["facing"]>>(
    config?.facing || "front",
  );
  const [quality, setQuality] = useState<NonNullable<CameraConfig["quality"]>>(
    config?.quality || "720p",
  );
  const [rotation, setRotation] = useState<
    NonNullable<CameraConfig["rotation"]>
  >(config?.rotation || "0");
  const [phones, setPhones] = useState<DebugPhone[] | null>(null);
  const [adbFound, setAdbFound] = useState(true);
  const [serial, setSerial] = useState("");
  const ready = (phones || []).filter((phone) => phone.state === "ready");
  const chosen = ready.find((phone) => phone.serial === serial) || ready[0];
  const target = deviceId
    ? { device_id: deviceId }
    : chosen
      ? { serial: chosen.serial }
      : undefined;
  const find = async () => {
    const found = await client.call<{ adb: boolean; devices: DebugPhone[] }>(
      "camera.devices",
    );
    setAdbFound(found.adb);
    setPhones(found.devices);
  };
  const start = async (preview = false) => {
    await client.call("settings.save", {
      link: { camera: { facing, quality, rotation } },
    });
    await client.call(
      "camera.start",
      preview ? { ...target, preview: true } : target,
    );
  };
  const waiting = (phones || []).filter((phone) => phone.state !== "ready");
  return (
    <div className="phone-camera">
      {!camera?.running && (
        <details>
          <summary>Camera options</summary>
          <label>
            Phone camera
            <select
              value={facing}
              onChange={(event) =>
                setFacing(event.target.value as typeof facing)
              }
            >
              <option value="front">Front camera</option>
              <option value="back">Rear camera</option>
            </select>
          </label>
          <label>
            Video quality
            <select
              value={quality}
              onChange={(event) =>
                setQuality(event.target.value as typeof quality)
              }
            >
              <option value="720p">720p · 30 fps</option>
              <option value="1080p">1080p · 30 fps</option>
            </select>
          </label>
          <label>
            Picture rotation
            <select
              value={rotation}
              onChange={(event) =>
                setRotation(event.target.value as typeof rotation)
              }
            >
              {(["0", "90", "180", "270"] as const).map((value) => (
                <option key={value} value={value}>
                  {value}°
                </option>
              ))}
            </select>
          </label>
        </details>
      )}
      {!deviceId && !camera?.running && (
        <div className="camera-phone-picker">
          <p className="muted">
            Connect your phone with a USB cable, or over Wi‑Fi with wireless
            debugging, then find it here.
          </p>
          <Action className="text-button" run={find}>
            {phones ? "Find again" : "Find my phone"}
          </Action>
          {phones && ready.length > 1 && (
            <label>
              Phone for the camera
              <select
                value={chosen?.serial}
                onChange={(event) => setSerial(event.target.value)}
              >
                {ready.map((phone) => (
                  <option key={phone.serial} value={phone.serial}>
                    {phone.model} · {connection(phone)}
                  </option>
                ))}
              </select>
            </label>
          )}
          {phones && ready.length === 1 && chosen && (
            <p className="muted">
              Using {chosen.model} · {connection(chosen)}
            </p>
          )}
          {phones && !ready.length && !waiting.length && (
            <p className="muted" role="status">
              {adbFound
                ? "No phone found. Check the cable and that USB debugging is on, or connect over Wi‑Fi below."
                : "adb was not found. Install scrcpy, which includes adb; Settings → Devices explains how."}
            </p>
          )}
          {waiting.map((phone) => (
            <p className="muted" role="status" key={phone.serial}>
              {phone.state === "unauthorized"
                ? `Unlock ${phone.model} and tap Allow on the debugging prompt, then choose Find again.`
                : phone.state === "no_permission"
                  ? `This computer cannot open ${phone.model} over USB yet. On Linux, install your distribution's android-udev rules and reconnect the cable.`
                  : `${phone.model} is offline for debugging. Unlock it and reconnect.`}
            </p>
          ))}
          <details>
            <summary>Connect over Wi‑Fi</summary>
            <WirelessDebugging client={client} onConnected={find} />
          </details>
        </div>
      )}
      {camera?.running ? (
        <Action className="text-button" run={() => client.call("camera.stop")}>
          {camera.mode === "preview" ? "Close camera preview" : "Stop phone camera"}
        </Action>
      ) : (
        <>
          <Action
            className="text-button"
            disabled={!target || !camera?.available}
            run={() => start()}
          >
            Use phone as webcam
          </Action>
          {!camera?.available && camera?.can_preview && (
            <Action
              className="text-button"
              disabled={!target}
              run={() => start(true)}
            >
              Open camera preview
            </Action>
          )}
        </>
      )}
      <p className="muted" role="status">
        {camera?.running
          ? camera.mode === "preview"
            ? "The preview window is open. Use it to set up OBS, then close it."
            : `${camera.facing === "back" ? "Rear" : "Front"} camera · ${camera.quality || "720p"}. Check the picture in your meeting app.`
          : !target
            ? phones === null
              ? "Find your phone to start the camera."
              : "Connect your phone to start the camera."
            : camera?.available
              ? "Your camera starts only when you choose to use it."
              : "Set up the camera once in Settings."}
      </p>
      {!camera?.available && (
        <SettingsShortcut target="Devices">
          Set up phone camera
        </SettingsShortcut>
      )}
    </div>
  );
}
