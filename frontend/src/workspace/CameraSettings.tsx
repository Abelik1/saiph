// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import type { ReactNode } from "react";
import type { CameraConfig, CameraStatus, Client, Settings } from "./types";
import { Action, Card, Form } from "./ui";
import { WirelessDebugging } from "./WirelessDebugging";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Field, Label } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

/** One numbered step of the setup guide; the number is drawn from a CSS counter. */
function Step({ title, children }: { title: string; children: ReactNode }) {
  return (
    <li className="relative grid gap-1.5 pl-10 [counter-increment:step] before:absolute before:top-0 before:left-0 before:flex before:size-7 before:items-center before:justify-center before:rounded-full before:bg-secondary before:text-[12px] before:font-semibold before:text-secondary-foreground before:content-[counter(step)]">
      <b className="text-[13.5px] font-semibold text-foreground">{title}</b>
      <div className="grid justify-items-start gap-2 leading-relaxed">{children}</div>
    </li>
  );
}

function Path({ label, value, placeholder, onChange }: { label: string; value: string; placeholder?: string; onChange: (value: string) => void }) {
  const id = useId();
  return (
    <Field label={label} htmlFor={id}>
      <Input id={id} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </Field>
  );
}

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
  const enabledId = useId();
  const text = (key: keyof CameraConfig) => (value: string) =>
    setConfig((current) => ({ ...current, [key]: value }));
  return (
    <Card
      title="Phone camera"
      subtitle="One-time setup for this computer. Capture always starts deliberately."
    >
      <p className="m-0 mb-4 text-[13px] text-muted-foreground" role="status">
        {camera?.message || "Camera readiness appears here automatically."}
      </p>
      <Disclosure summary="One-time camera setup" className="mb-4">
        <p className="m-0">
          The video goes straight from your phone to this computer over a USB
          cable or your Wi‑Fi. It works with Saiph Hosted and without a server
          or Tailscale. The phone needs Android 12 or later.
        </p>
        <ol className="m-0 grid list-none gap-4 p-0 [counter-reset:step]">
          <Step title="Turn on Developer options on the phone.">
            <p className="m-0">
              Open Settings → About phone and tap Build number seven times (some
              phones put it under Software information). Then open Developer
              options and turn on USB debugging, or Wireless debugging to use
              Wi‑Fi instead of a cable.
            </p>
          </Step>
          <Step title="Install scrcpy 2.2 or later on this computer.">
            <p className="m-0">
              It includes adb.{" "}
              {platform !== "linux" &&
                "On Windows, unzip it and enter the path to scrcpy.exe under Tool and configuration paths below unless it is already on your PATH. "}
              {platform !== "windows" &&
                "On Linux, use the official release or a distribution package of version 2.2 or later; older packages cannot use the phone camera. "}
            </p>
            <Action variant="tonal" size="sm" run={() => client.call("setup.open", { link: "scrcpy" })}>
              Download scrcpy
            </Action>
          </Step>
          <Step title="Allow this computer.">
            <p className="m-0">
              Connect the USB cable, unlock the phone and tap Allow (tick Always
              allow from this computer). Or pair over Wi‑Fi below; you only pair
              once.
            </p>
          </Step>
          {platform !== "linux" && (
            <Step title="Set up OBS Studio once (Windows).">
              <p className="m-0">
                Install OBS Studio. On the Phone page find your phone and choose
                Open camera preview so the Orion Phone Camera window appears. In
                OBS create a Profile, a Scene Collection and a scene, each named
                Orion Phone. Add a Window Capture source, choose “[scrcpy.exe]:
                Orion Phone Camera” and set Window Match Priority to “Window
                title must match”. Leave Capture Audio off, and in Settings →
                Audio set Desktop Audio and Mic/Auxiliary Audio to Disabled.
                Quit OBS (File → Exit) and close the preview. Saiph then starts
                OBS’s Virtual Camera for you.
              </p>
              <Action variant="tonal" size="sm" run={() => client.call("setup.open", { link: "obs" })}>
                Download OBS Studio
              </Action>
            </Step>
          )}
          {platform !== "windows" && (
            <Step title="Create a virtual webcam once (Linux).">
              <p className="m-0">
                Install v4l2loopback (on Debian or Ubuntu: sudo apt install
                v4l2loopback-dkms), then run sudo modprobe v4l2loopback
                video_nr=10 card_label="Saiph Phone" exclusive_caps=1 and enter
                /dev/video10 below. With Secure Boot your system may ask you to
                enrol a key. To keep it after a restart, add the module and its
                options to /etc/modules-load.d and /etc/modprobe.d.
              </p>
              <Action variant="tonal" size="sm" run={() => client.call("setup.open", { link: "v4l2loopback" })}>
                v4l2loopback instructions
              </Action>
            </Step>
          )}
          <Step title="Use it.">
            <p className="m-0">
              On the Phone page choose Use phone as webcam, then pick{" "}
              {platform === "linux" ? "Saiph Phone" : platform === "windows" ? "OBS Virtual Camera" : "OBS Virtual Camera (Windows) or Saiph Phone (Linux)"}{" "}
              as the camera in your meeting app. The phone shows a green camera
              dot while it is in use. Microphone audio is not sent.
            </p>
          </Step>
        </ol>
        <Disclosure summary="Pair or connect over Wi‑Fi" className="mt-1">
          <WirelessDebugging client={client} />
        </Disclosure>
        <Action variant="link" className="justify-self-start text-[13px]" run={() => client.call("camera.help")}>
          Open the upstream camera setup guide
        </Action>
      </Disclosure>
      <Form
        className="grid gap-4"
        successMessage="Camera preferences saved."
        submit={() =>
          client.call("settings.save", { link: { camera: config } })
        }
      >
        <div className="grid gap-4">
          <div className="flex items-center justify-between gap-4">
            <Label htmlFor={enabledId} className="text-[13px] text-foreground">
              Use my phone as a webcam (it starts only when I choose)
            </Label>
            <Switch
              id={enabledId}
              checked={config.enabled !== false}
              onCheckedChange={(enabled) => setConfig((current) => ({ ...current, enabled }))}
            />
          </div>
          {platform !== "windows" && (
            <Path label="Linux loopback device" value={config.v4l2_sink || ""} placeholder="/dev/video10" onChange={text("v4l2_sink")} />
          )}
          {platform !== "linux" && (
            <>
              <Path label="OBS profile" value={config.obs_profile ?? "Orion Phone"} onChange={text("obs_profile")} />
              <Path label="OBS scene collection" value={config.obs_collection ?? "Orion Phone"} onChange={text("obs_collection")} />
              <Path label="OBS scene" value={config.obs_scene ?? "Orion Phone"} onChange={text("obs_scene")} />
            </>
          )}
          <Disclosure summary="Tool and configuration paths">
            {platform !== "linux" && (
              <>
                <Path label="OBS scene file" value={config.obs_scene_file || ""} placeholder="Use the standard OBS folder" onChange={text("obs_scene_file")} />
                <Path label="OBS executable" value={config.obs_executable || ""} placeholder="Find the installed OBS Studio" onChange={text("obs_executable")} />
              </>
            )}
            <Path label="scrcpy executable" value={config.scrcpy_executable || ""} placeholder="Find installed or Saiph portable scrcpy" onChange={text("scrcpy_executable")} />
          </Disclosure>
          <Button type="submit" variant="default" className="justify-self-start">Save camera preferences</Button>
        </div>
      </Form>
      <p className="m-0 mt-4 text-[12.5px] text-muted-foreground">
        Readiness confirms the local tools and configuration. Verify video in
        your meeting app after starting the camera.
      </p>
    </Card>
  );
}
