// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import { Settings2, Video } from "lucide-react";
import type { CameraConfig, CameraStatus, Client } from "./types";
import { Action } from "./ui";
import { SettingsShortcut } from "./Navigation";
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
  const start = async () => {
    await client.call("settings.save", {
      link: { camera: { facing, quality, rotation } },
    });
    await client.call("camera.start", { device_id: deviceId });
  };
  return (
    <div className="grid gap-3 p-4">
      <Item size="flush">
        <ItemMedia><Video /></ItemMedia>
        <ItemContent>
          <ItemTitle className="flex items-center gap-2">Webcam {camera?.running && <Badge tone="good">Live</Badge>}</ItemTitle>
          <ItemDescription role="status">
            {camera?.running
              ? `${camera.facing === "back" ? "Rear" : "Front"} camera · ${camera.quality || "720p"}. Check the picture in your meeting app.`
              : !deviceId
                ? "Reconnect your phone to start the camera."
                : camera?.available
                  ? "Your camera starts only when you choose to use it."
                  : "Set up the camera once in Settings."}
          </ItemDescription>
        </ItemContent>
      </Item>
      <ItemActions className="flex-wrap pl-12">
        {camera?.running ? (
          <Action variant="destructive" size="sm" run={() => client.call("camera.stop")}>
            Stop phone camera
          </Action>
        ) : (
          <Action variant="tonal" size="sm" disabled={!deviceId || !camera?.available} run={start}>
            Use phone as webcam
          </Action>
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
