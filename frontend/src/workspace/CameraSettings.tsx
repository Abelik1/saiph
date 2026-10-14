// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { CameraConfig, CameraStatus, Client, Settings } from "./types";
import { Action, Card, Form } from "./ui";
import { WirelessDebugging } from "./WirelessDebugging";

export function CameraSettings({
  settings,
  camera,
  client,
  platform,
}: {
  settings: Settings;
  camera?: CameraStatus;
  client: Client;
  platform?: string;
}) {
  const [config, setConfig] = useState<CameraConfig>(
    () => settings.link?.camera || {},
  );
  const text = (key: keyof CameraConfig, value: string) =>
    setConfig((current) => ({ ...current, [key]: value }));
  return (
    <Card
      title="Phone camera"
      subtitle="One-time setup for this computer. Capture always starts deliberately."
    >
      <p className="muted">
        {camera?.message || "Camera readiness appears here automatically."}
      </p>
      <details className="device-setup-guide">
        <summary>One-time camera setup</summary>
        <p>
          The video goes straight from your phone to this computer over a USB
          cable or your Wi‑Fi. It works with Saiph Hosted and without a server
          or Tailscale. The phone needs Android 12 or later.
        </p>
        <ol>
          <li>
            <b>Turn on Developer options on the phone.</b> Open Settings → About
            phone and tap Build number seven times (some phones put it under
            Software information). Then open Developer options and turn on USB
            debugging, or Wireless debugging to use Wi‑Fi instead of a cable.
          </li>
          <li>
            <b>Install scrcpy 2.2 or later on this computer.</b> It includes
            adb.{" "}
            {platform !== "linux" &&
              "On Windows, unzip it and enter the path to scrcpy.exe under Tool and configuration paths below unless it is already on your PATH. "}
            {platform !== "windows" &&
              "On Linux, use the official release or a distribution package of version 2.2 or later; older packages cannot use the phone camera. "}
            <Action
              className="text-button"
              run={() => client.call("setup.open", { link: "scrcpy" })}
            >
              Download scrcpy
            </Action>
          </li>
          <li>
            <b>Allow this computer.</b> Connect the USB cable, unlock the phone
            and tap Allow (tick Always allow from this computer). Or pair over
            Wi‑Fi below; you only pair once.
          </li>
          {platform !== "linux" && (
            <li>
              <b>Set up OBS Studio once (Windows).</b> Install OBS Studio. On
              the Phone page find your phone and choose Open camera preview so
              the Orion Phone Camera window appears. In OBS create a Profile, a
              Scene Collection and a scene, each named Orion Phone. Add a Window
              Capture source, choose “[scrcpy.exe]: Orion Phone Camera” and set
              Window Match Priority to “Window title must match”. Leave Capture
              Audio off, and in Settings → Audio set Desktop Audio and
              Mic/Auxiliary Audio to Disabled. Quit OBS (File → Exit) and close
              the preview. Saiph then starts OBS’s Virtual Camera for you.{" "}
              <Action
                className="text-button"
                run={() => client.call("setup.open", { link: "obs" })}
              >
                Download OBS Studio
              </Action>
            </li>
          )}
          {platform !== "windows" && (
            <li>
              <b>Create a virtual webcam once (Linux).</b> Install
              v4l2loopback (on Debian or Ubuntu: sudo apt install
              v4l2loopback-dkms), then run sudo modprobe v4l2loopback
              video_nr=10 card_label="Saiph Phone" exclusive_caps=1 and enter
              /dev/video10 below. With Secure Boot your system may ask you to
              enrol a key. To keep it after a restart, add the module and its
              options to /etc/modules-load.d and /etc/modprobe.d.{" "}
              <Action
                className="text-button"
                run={() => client.call("setup.open", { link: "v4l2loopback" })}
              >
                v4l2loopback instructions
              </Action>
            </li>
          )}
          <li>
            <b>Use it.</b> On the Phone page choose Use phone as webcam, then
            pick {platform === "linux" ? "Saiph Phone" : platform === "windows" ? "OBS Virtual Camera" : "OBS Virtual Camera (Windows) or Saiph Phone (Linux)"}{" "}
            as the camera in your meeting app. The phone shows a green camera
            dot while it is in use. Microphone audio is not sent.
          </li>
        </ol>
        <details>
          <summary>Pair or connect over Wi‑Fi</summary>
          <WirelessDebugging client={client} />
        </details>
        <Action className="text-button" run={() => client.call("camera.help")}>
          Open the upstream camera setup guide
        </Action>
      </details>
      <Form
        successMessage="Camera preferences saved."
        submit={() =>
          client.call("settings.save", { link: { camera: config } })
        }
      >
        <label className="check">
          <input
            type="checkbox"
            checked={config.enabled !== false}
            onChange={(event) =>
              setConfig((current) => ({
                ...current,
                enabled: event.target.checked,
              }))
            }
          />
          Use my phone as a webcam (it starts only when I choose)
        </label>
        {platform !== "windows" && (
          <label>
            Linux loopback device
            <input
              value={config.v4l2_sink || ""}
              placeholder="/dev/video10"
              onChange={(event) => text("v4l2_sink", event.target.value)}
            />
          </label>
        )}
        {platform !== "linux" && (
          <>
            <label>
              OBS profile
              <input
                value={config.obs_profile ?? "Orion Phone"}
                onChange={(event) => text("obs_profile", event.target.value)}
              />
            </label>
            <label>
              OBS scene collection
              <input
                value={config.obs_collection ?? "Orion Phone"}
                onChange={(event) => text("obs_collection", event.target.value)}
              />
            </label>
            <label>
              OBS scene
              <input
                value={config.obs_scene ?? "Orion Phone"}
                onChange={(event) => text("obs_scene", event.target.value)}
              />
            </label>
          </>
        )}
        <details>
          <summary>Tool and configuration paths</summary>
          {platform !== "linux" && (
            <>
              <label>
                OBS scene file
                <input
                  value={config.obs_scene_file || ""}
                  placeholder="Use the standard OBS folder"
                  onChange={(event) =>
                    text("obs_scene_file", event.target.value)
                  }
                />
              </label>
              <label>
                OBS executable
                <input
                  value={config.obs_executable || ""}
                  placeholder="Find the installed OBS Studio"
                  onChange={(event) =>
                    text("obs_executable", event.target.value)
                  }
                />
              </label>
            </>
          )}
          <label>
            scrcpy executable
            <input
              value={config.scrcpy_executable || ""}
              placeholder="Find installed or Saiph portable scrcpy"
              onChange={(event) =>
                text("scrcpy_executable", event.target.value)
              }
            />
          </label>
        </details>
        <button>Save camera preferences</button>
      </Form>
      <p className="muted">
        Readiness confirms the local tools and configuration. Verify video in
        your meeting app after starting the camera.
      </p>
    </Card>
  );
}
