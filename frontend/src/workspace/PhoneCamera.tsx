// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import { Settings2, Video } from "lucide-react";
import type { CameraConfig, CameraStatus, Client, DebugPhone } from "./types";
import { Action } from "./ui";
import { SettingsShortcut } from "./Navigation";
import { WirelessDebugging } from "./WirelessDebugging";
import { Disclosure } from "@/components/ui/disclosure";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Field } from "@/components/ui/field";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

function Choice<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (value: T) => void }) {
  const id = useId();
  return <Field label={label} htmlFor={id}>
    <Select value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectTrigger id={id} size="sm"><SelectValue /></SelectTrigger>
      <SelectContent>{options.map(([option, text]) => <SelectItem key={option} value={option}>{text}</SelectItem>)}</SelectContent>
    </Select>
  </Field>;
}

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
    <div className="grid gap-3 p-4">
      <Item size="flush">
        <ItemMedia><Video /></ItemMedia>
        <ItemContent>
          <ItemTitle className="flex items-center gap-2">Phone camera {camera?.running && <Badge tone="good">Live</Badge>}</ItemTitle>
          <ItemDescription role="status">
            {camera?.running
              ? camera.mode === "preview"
                ? "Your phone camera is open in its own window."
                : `${camera.facing === "back" ? "Rear" : "Front"} camera · ${camera.quality || "720p"}. Check the picture in your meeting app.`
              : !target
                ? phones === null
                  ? "Find your phone to start the camera."
                  : "Connect your phone to start the camera."
                : camera?.available
                  ? "Your camera starts only when you choose to use it."
                  : camera?.can_preview ? "Open your camera directly. Meeting-app sharing needs optional setup." : "Set up the camera once in Settings."}
          </ItemDescription>
        </ItemContent>
      </Item>
      {!deviceId && !camera?.running && (
        // Without a Hub-paired phone, use one that allowed this computer over USB or Wi-Fi debugging.
        <div className="grid gap-2.5 pl-12 text-[12.5px] leading-relaxed text-muted-foreground">
          <p className="m-0">Connect your phone with a USB cable, or over Wi‑Fi with wireless debugging, then find it here.</p>
          <div><Action variant="tonal" size="sm" run={find}>{phones ? "Find again" : "Find my phone"}</Action></div>
          {phones && ready.length > 1 && chosen && (
            <Choice label="Phone for the camera" value={chosen.serial} onChange={setSerial}
              options={ready.map((phone) => [phone.serial, `${phone.model} · ${connection(phone)}`] as [string, string])} />
          )}
          {phones && ready.length === 1 && chosen && <p className="m-0">Using {chosen.model} · {connection(chosen)}</p>}
          {phones && !ready.length && !waiting.length && (
            <p className="m-0" role="status">
              {adbFound
                ? "No phone found. Check the cable and that USB debugging is on, or connect over Wi‑Fi below."
                : "adb was not found. Install scrcpy, which includes adb; Settings → Devices explains how."}
            </p>
          )}
          {waiting.map((phone) => (
            <p className="m-0" role="status" key={phone.serial}>
              {phone.state === "unauthorized"
                ? `Unlock ${phone.model} and tap Allow on the debugging prompt, then choose Find again.`
                : phone.state === "no_permission"
                  ? `This computer cannot open ${phone.model} over USB yet. On Linux, install your distribution's android-udev rules and reconnect the cable.`
                  : `${phone.model} is offline for debugging. Unlock it and reconnect.`}
            </p>
          ))}
          <Disclosure summary="Connect over Wi‑Fi">
            <WirelessDebugging client={client} onConnected={find} />
          </Disclosure>
        </div>
      )}
      <ItemActions className="flex-wrap pl-12">
        {camera?.running ? (
          <Action variant="destructive" size="sm" run={() => client.call("camera.stop")}>
            {camera.mode === "preview" ? "Close camera preview" : "Stop phone camera"}
          </Action>
        ) : (
          <>
            {camera?.can_preview && (
              <Action variant="tonal" size="sm" disabled={!target} run={() => start(true)}>
                Open camera preview
              </Action>
            )}
            <Action variant="secondary" size="sm" disabled={!target || !camera?.available} run={() => start()}>
              Use phone as webcam
            </Action>
          </>
        )}
        {!camera?.running && (
          // The options belong to this button, so they open beside it. They are saved when the camera starts.
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Camera options" title="Camera options"><Settings2 /></Button>
            </PopoverTrigger>
            <PopoverContent>
              <b className="text-[13px] font-semibold">Camera options</b>
              <Choice label="Phone camera" value={facing} onChange={setFacing} options={[["front", "Front camera"], ["back", "Rear camera"]]} />
              <Choice label="Video quality" value={quality} onChange={setQuality} options={[["720p", "720p · 30 fps"], ["1080p", "1080p · 30 fps"]]} />
              <Choice label="Picture rotation" value={rotation} onChange={setRotation} options={(["0", "90", "180", "270"] as const).map((value) => [value, value + "°"])} />
              <small className="text-[12px] text-muted-foreground">Used the next time you start the webcam.</small>
            </PopoverContent>
          </Popover>
        )}
        {!camera?.available && (
          <SettingsShortcut target="Devices">
            Set up phone camera
          </SettingsShortcut>
        )}
      </ItemActions>
    </div>
  );
}
