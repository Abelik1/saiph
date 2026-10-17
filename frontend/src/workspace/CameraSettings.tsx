// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import type { CameraStatus, Client, Settings } from "./types";
import { PreferenceCard } from "./PreferenceCard";
import { LegacyCameraSettings } from "./LegacyCameraSettings";
import { Form } from "./ui";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Label } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";

export function CameraSettings({ settings, camera, client, platform }: {
  settings: Settings; camera?: CameraStatus; client: Client; platform?: string;
}) {
  const id = useId();
  const [enabled, setEnabled] = useState(settings.link?.camera?.enabled !== false);
  const [legacyOpen, setLegacyOpen] = useState(false);
  return <PreferenceCard title="Phone camera" subtitle="A webcam built into Saiph.">
    <p>On your computer: Phone → Webcam. On your phone: Use phone as webcam.</p>
    <p className="text-muted-foreground">Keep both devices on the same Wi-Fi. Camera sessions are encrypted, audio is off, and leaving the phone's camera screen stops sharing.</p>
    <Form successMessage="Camera preferences saved." submit={() => client.call("settings.save", { link: { camera: { enabled } } })}>
      <div className="flex items-center justify-between gap-4"><Label htmlFor={id}>Allow phone camera</Label>
        <Switch id={id} checked={enabled} onCheckedChange={setEnabled} /></div>
      <Button type="submit" variant="secondary" className="justify-self-start">Save camera preferences</Button>
    </Form>
    <Disclosure summary="Legacy USB camera tools (advanced)" onToggle={event => setLegacyOpen(event.currentTarget.open)}>
      {legacyOpen && <LegacyCameraSettings settings={settings} camera={camera} client={client} platform={platform} />}
    </Disclosure>
  </PreferenceCard>;
}
