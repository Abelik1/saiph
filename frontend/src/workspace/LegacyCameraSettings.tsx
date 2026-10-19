// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import type { ReactNode } from "react";
import type { CameraConfig, CameraStatus, Client, Settings } from "./types";
import { Action, Form } from "./ui";
import { PreferenceCard as Card } from "./PreferenceCard";
import { WirelessDebugging } from "./WirelessDebugging";
import { LegacyPhoneCamera } from "./LegacyPhoneCamera";
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

export function LegacyCameraSettings({ settings, camera, client, platform }: {
  settings: Settings; camera?: CameraStatus; client: Client; platform?: string;
}) {
  const [config, setConfig] = useState<CameraConfig>(() => settings.link?.camera || {});
  const enabledId = useId();
  const text = (key: keyof CameraConfig) => (value: string) => setConfig(current => ({ ...current, [key]: value }));
  return <Card title="Phone camera" subtitle="View your phone's camera on this computer.">
    <p role="status">{camera?.running ? "Your phone camera is running." : camera?.can_preview ? "Ready to open your phone camera." : "Complete phone camera setup below."}</p>
    <p>On Phone, choose Webcam → Open camera preview.</p>
    <Form successMessage="Camera preferences saved." submit={() => client.call("settings.save", { link: { camera: config } })}>
      <div className="flex items-center justify-between gap-4">
        <Label htmlFor={enabledId}>Allow phone camera</Label>
        <Switch id={enabledId} checked={config.enabled !== false} onCheckedChange={enabled => setConfig(current => ({ ...current, enabled }))} />
      </div>
      <Disclosure summary="Camera tool paths">
        <Path label="scrcpy executable" value={config.scrcpy_executable || ""} placeholder="Find installed or Saiph portable scrcpy" onChange={text("scrcpy_executable")} />
      </Disclosure>
      <Disclosure summary="Meeting-app configuration">
        {platform !== "windows" && <Path label="Linux loopback device" value={config.v4l2_sink || ""} placeholder="/dev/video10" onChange={text("v4l2_sink")} />}
        {platform !== "linux" && <>
          <Path label="OBS profile" value={config.obs_profile ?? "Orion Phone"} onChange={text("obs_profile")} />
          <Path label="OBS scene collection" value={config.obs_collection ?? "Orion Phone"} onChange={text("obs_collection")} />
          <Path label="OBS scene" value={config.obs_scene ?? "Orion Phone"} onChange={text("obs_scene")} />
          <Path label="OBS scene file" value={config.obs_scene_file || ""} placeholder="Use the standard OBS folder" onChange={text("obs_scene_file")} />
          <Path label="OBS executable" value={config.obs_executable || ""} placeholder="Find the installed OBS Studio" onChange={text("obs_executable")} />
        </>}
      </Disclosure>
      <Button type="submit" variant="secondary" className="justify-self-start">Save camera preferences</Button>
    </Form>
    <Disclosure summary="Phone camera setup">
      <p>Camera video travels directly over USB or Wi‑Fi. It works with Saiph Cloud and without a server or Tailscale. Android 12 or later is required.</p>
      <ol className="m-0 grid list-none gap-5 p-0 [counter-reset:step]">
        <Step title="Allow a phone connection">
          <p className="m-0">In phone Settings → About phone, tap Build number seven times. Some phones put it under Software information. In Developer options, turn on USB debugging.</p>
          <p className="m-0">Connect the cable, unlock your phone and tap Allow on its debugging prompt.</p>
        </Step>
        <Step title="Install the camera tool">
          <p className="m-0">Install scrcpy 2.2 or later. It includes adb. If Saiph cannot find it, enter its executable path above.</p>
          <Action variant="tonal" size="sm" run={() => client.call("setup.open", { link: "scrcpy" })}>Download scrcpy</Action>
        </Step>
        <Step title="Open your camera">
          <p className="m-0">On Phone, choose Webcam, find your phone and open the camera preview. Camera capture starts when you choose; audio is separate.</p>
        </Step>
      </ol>
      <Disclosure summary="Pair or connect over Wi‑Fi"><WirelessDebugging client={client} /></Disclosure>
      <Action variant="tonal" size="sm" run={() => client.call("camera.help")}>Open camera setup guide</Action>
    </Disclosure>
    <Disclosure summary="Use in a meeting app (optional)">
      <p>{platform === "linux" ? "Linux uses a virtual webcam to make your phone camera available to meeting apps." : "For Windows meeting apps, this beta uses OBS Virtual Camera to share your phone camera."}</p>
      {platform !== "linux" && <>
        <p>OBS is only needed for the meeting-app webcam. You can open the phone camera directly using scrcpy.</p>
        <ol className="m-0 grid list-none gap-5 p-0 [counter-reset:step]">
          <Step title="Install OBS Studio"><Action variant="tonal" size="sm" run={() => client.call("setup.open", { link: "obs" })}>Download OBS Studio</Action></Step>
          <Step title="Create the camera scene">
            <p className="m-0">Open camera preview on Phone. In OBS, create a profile, scene collection and scene, each named Orion Phone.</p>
            <p className="m-0">Add a Window Capture source for “[scrcpy.exe]: Orion Phone Camera”. Set Window Match Priority to “Window title must match” and leave Capture Audio off.</p>
          </Step>
          <Step title="Keep audio separate">
            <p className="m-0">In OBS Settings → Audio, disable Desktop Audio and Mic/Auxiliary Audio. Exit OBS and close the camera preview.</p>
          </Step>
          <Step title="Use the webcam">
            <p className="m-0">On Phone, choose Use phone as webcam. In your meeting app, choose OBS Virtual Camera.</p>
          </Step>
        </ol>
      </>}
      {platform !== "windows" && <>
        <p>Install v4l2loopback-dkms. Create a loopback device and enter its path in Meeting-app configuration above. Choose Saiph Phone in your meeting app.</p>
        <p>For example: sudo modprobe v4l2loopback video_nr=10 card_label="Saiph Phone" exclusive_caps=1. With Secure Boot, your system may require a key. Follow the module's instructions to keep it after a restart.</p>
        <Action variant="tonal" size="sm" run={() => client.call("setup.open", { link: "v4l2loopback" })}>v4l2loopback instructions</Action>
      </>}
    </Disclosure>
    <Disclosure summary="Start a legacy USB camera session">
      <LegacyPhoneCamera camera={camera} config={config} client={client} />
    </Disclosure>
  </Card>;
}
