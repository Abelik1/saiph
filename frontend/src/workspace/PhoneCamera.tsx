// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import { Video } from "lucide-react";
import type { CameraConfig, CameraStatus, Client } from "./types";
import { Action } from "./ui";
import { QrImage, validQr, type PairingQrCode } from "./PairingQr";
import { Badge } from "@/components/ui/badge";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";

type CameraCode = PairingQrCode & { session: string };

export function PhoneCamera({ camera, config, client }: {
  camera?: CameraStatus; config?: CameraConfig; deviceId?: string; client: Client;
}) {
  const [code, setCode] = useState<CameraCode | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(120);
  const invitation = useRef<string | null>(null);
  const observedSession = useRef(false);
  const live = camera?.local_state === "live";
  const legacyLive = Boolean(camera?.running && !live);
  const waiting = camera?.local_state === "waiting" || camera?.local_state === "connecting";
  useEffect(() => () => {
    if (invitation.current) void client.call("camera.cancel_invite", { session: invitation.current }).catch(() => {});
  }, [client]);
  useEffect(() => {
    if (live || waiting) observedSession.current = true;
    if (live || (!waiting && observedSession.current)) {
      invitation.current = null; setCode(null);
      if (!live) observedSession.current = false;
    }
  }, [live, waiting]);
  useEffect(() => {
    if (!code) return;
    const tick = () => setRemaining(Math.max(0, Math.ceil((Date.parse(code.expires_at) - Date.now()) / 1000)));
    tick(); const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [code]);
  useEffect(() => {
    if (!live) { setImage(null); return; }
    let cancelled = false;
    let timer: number;
    const poll = async () => {
      try {
        const frame = await client.call<{ image: string | null }>("camera.frame");
        if (!cancelled) setImage(typeof frame.image === "string" && frame.image.length <= 150000
          && frame.image.startsWith("data:image/jpeg;base64,") ? frame.image : null);
      } catch { if (!cancelled) setImage(null); }
      if (!cancelled) timer = window.setTimeout(poll, 250);
    };
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [client, live]);
  async function start(preview: boolean) {
    observedSession.current = false;
    if (config?.enabled === false) await client.call("settings.save", { link: { camera: { enabled: true } } });
    const next = await client.call<CameraCode>("camera.session", { preview });
    if (!validQr(next) || !/^[a-f0-9]{32}$/.test(next.session)) throw new Error("The camera code could not be displayed.");
    invitation.current = next.session;
    setRemaining(120); setCode(next);
  }
  async function stop() {
    await client.call("camera.stop"); invitation.current = null; observedSession.current = false; setCode(null); setImage(null);
  }
  return <div className="grid gap-4 p-4" aria-label="Phone camera">
    <Item className="p-0">
      <ItemMedia><Video /></ItemMedia>
      <ItemContent>
        <ItemTitle>Phone camera {(live || legacyLive) && <Badge tone="good">Live</Badge>}</ItemTitle>
        <ItemDescription>{legacyLive ? "Your phone camera is running." : live ? camera?.local_preview ? "Camera preview · audio is off." : "Choose Saiph Camera in your meeting app."
          : "Use your phone as a webcam. Keep both devices on the same Wi-Fi."}</ItemDescription>
      </ItemContent>
    </Item>
    {code && !live && <div className="grid justify-items-center gap-3">
      {remaining > 0 ? <>
        <QrImage modules={code.modules} label="Camera session QR code" width={240} />
        <p className="m-0 text-center text-sm">On your phone: Saiph → Use phone as webcam → Scan computer's camera code.</p>
        <small className="text-muted-foreground" role="timer">Works once · expires in {remaining}s. Keep this code private.</small>
      </> : <p role="status">Camera code expired. Close it and start a new session.</p>}
    </div>}
    {live && image && <img src={image} alt="Live phone camera preview" className="aspect-video w-full rounded-lg bg-field object-contain" />}
    {!code && !live && camera?.local_message && <p role="status" className="m-0 text-sm text-muted-foreground">{camera.local_message}</p>}
    <ItemActions className="flex-wrap justify-start">
      {live || legacyLive || code || waiting ? <Action variant="destructive" run={stop}>{live || legacyLive ? "Stop camera" : "Close camera code"}</Action> : <>
        <Action disabled={!camera?.integrated_available} run={() => start(false)}>Use phone as webcam</Action>
        <Action variant="tonal" run={() => start(true)}>Preview camera</Action>
      </>}
    </ItemActions>
    {!camera?.integrated_available && !code && !live && <small className="text-muted-foreground">The integrated webcam needs the Windows Saiph build. Preview works without it.</small>}
  </div>;
}
