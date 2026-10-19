// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import { Video } from "lucide-react";
import type { CameraConfig, CameraStatus, Client } from "./types";
import { followFrames, showRate } from "./frameFeed";
import { Action } from "./ui";
import { QrImage, validQr, type PairingQrCode } from "./PairingQr";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";

type CameraCode = PairingQrCode & { session: string };
type Frame = { image: string | null; sequence: number; fps?: number; rotation?: number; shown?: number;
  source_width?: number; source_height?: number; output_width?: number; output_height?: number };
// The phone's own JPEG, as base64, for shells that still answer camera.frame.
const MAX_IMAGE = 2_100_000;

/** Draws one decoded frame upright; the canvas keeps the picture's own size and CSS fits it. */
function drawFrame(canvas: HTMLCanvasElement, image: HTMLImageElement, rotation: number) {
  const turned = rotation === 90 || rotation === 270;
  const width = turned ? image.naturalHeight : image.naturalWidth, height = turned ? image.naturalWidth : image.naturalHeight;
  if (!width || !height) return;
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(1, 0, 0, 1, width / 2, height / 2);
  context.rotate((rotation * Math.PI) / 180);
  context.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);
}

/** An approved Saiph Cloud phone that is online: it receives the code as a sealed request instead of a scan. */
export type CloudPhone = { id: string; name: string };

export function PhoneCamera({ camera, config, client, cloudPhone }: {
  camera?: CameraStatus; config?: CameraConfig; deviceId?: string; client: Client; cloudPhone?: CloudPhone;
}) {
  const [code, setCode] = useState<CameraCode | null>(null);
  const [offer, setOffer] = useState<{ sent?: string; error?: string } | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(120);
  const [resolution, setResolution] = useState("1080p");
  const [fps, setFps] = useState(20);
  const [quality, setQuality] = useState("high");
  const [measurement, setMeasurement] = useState<Frame | null>(null);
  const [pushed, setPushed] = useState(false);
  const preview = useRef<HTMLCanvasElement>(null);
  const invitation = useRef<string | null>(null);
  const observedSession = useRef(false);
  const live = camera?.local_state === "live";
  const legacyLive = Boolean(camera?.running && !live);
  const waiting = camera?.local_state === "waiting" || camera?.local_state === "connecting";
  const activeFps = camera?.local_fps || 15;
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
    if (!live) { setImage(null); setMeasurement(null); setPushed(false); return; }
    // Pushed frames go straight to the canvas; the status line updates once a second.
    const rate = showRate();
    let reported = 0;
    const follow = followFrames(client, "camera", (info, picture) => {
      const canvas = preview.current;
      if (!canvas) return;
      drawFrame(canvas, picture, info.rotation || 0);
      const shown = rate(), now = performance.now();
      if (now - reported >= 1000) { reported = now; setMeasurement({ ...info, image: null, shown }); }
    }, () => Boolean(preview.current && preview.current.offsetParent !== null));
    if (follow) { setPushed(true); return follow; }
    let cancelled = false;
    let timer: number;
    const poll = async () => {
      const started = performance.now();
      try {
        const frame = await client.call<Frame>("camera.frame");
        if (!cancelled) {
          setImage(typeof frame.image === "string" && frame.image.length <= MAX_IMAGE
            && frame.image.startsWith("data:image/jpeg;base64,") ? frame.image : null);
          setMeasurement(frame);
        }
      } catch { if (!cancelled) setImage(null); }
      // Native response time belongs to the selected frame period. Adding another
      // full period after a slow read needlessly lowers the preview cadence.
      // Start only after completion, so slow reads never overlap or queue up.
      if (!cancelled) timer = window.setTimeout(poll, Math.max(0, 1000 / activeFps - (performance.now() - started)));
    };
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [client, live, activeFps]);
  async function start(preview: boolean) {
    observedSession.current = false;
    if (config?.enabled === false) await client.call("settings.save", { link: { camera: { enabled: true } } });
    const next = await client.call<CameraCode>("camera.session", { preview, resolution, fps, quality });
    if (!validQr(next) || !/^[a-f0-9]{32}$/.test(next.session)) throw new Error("The camera code could not be displayed.");
    invitation.current = next.session;
    setRemaining(120); setCode(next); setOffer(null);
    if (cloudPhone) await send(next.session, cloudPhone);
  }
  async function send(session: string, phone: CloudPhone) {
    try {
      const result = await client.call<{ sent?: boolean; name?: string }>("camera.offer", { session, device_id: phone.id });
      setOffer(result?.sent ? { sent: typeof result.name === "string" && result.name ? result.name : phone.name }
        : { error: "The request was not sent. Scan the code instead." });
    } catch (error) {
      setOffer({ error: error instanceof Error && error.message ? error.message : "The request was not sent. Scan the code instead." });
    }
  }
  async function stop() {
    await client.call("camera.stop"); invitation.current = null; observedSession.current = false; setCode(null); setImage(null); setOffer(null);
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
    {!live && !legacyLive && !code && !waiting && <div className="grid gap-3">
      <fieldset className="grid gap-1"><legend className="text-sm">Resolution</legend><div className="flex flex-wrap gap-2">
        {["720p", "1080p"].map(value => <Button key={value} size="sm" variant={resolution === value ? "tonal" : "ghost"} aria-pressed={resolution === value} onClick={() => setResolution(value)}>{value}</Button>)}
      </div></fieldset>
      <fieldset className="grid gap-1"><legend className="text-sm">Frame rate</legend><div className="flex flex-wrap gap-2">
        {[15, 20, 30].map(value => <Button key={value} size="sm" variant={fps === value ? "tonal" : "ghost"} aria-pressed={fps === value} onClick={() => setFps(value)}>{value} fps</Button>)}
      </div></fieldset>
      <fieldset className="grid gap-1"><legend className="text-sm">Image quality</legend><div className="flex flex-wrap gap-2">
        {([['standard', 'Standard'], ['high', 'High detail']] as const).map(([value, label]) => <Button key={value} size="sm" variant={quality === value ? "tonal" : "ghost"} aria-pressed={quality === value} onClick={() => setQuality(value)}>{label}</Button>)}
      </div></fieldset>
      <small className="text-muted-foreground">Applied when you start. Higher settings use more Wi-Fi and phone power; actual frame rate depends on both devices. Keep the phone app updated.</small>
    </div>}
    {code && !live && <div className="grid justify-items-center gap-3">
      {remaining > 0 ? <>
        {offer?.sent && <p role="status" className="m-0 text-center text-sm">Sent to {offer.sent}. On your phone, tap <strong>Start camera</strong> in Saiph's notification and confirm with your screen lock.</p>}
        {offer?.error && <p role="alert" className="m-0 text-center text-sm text-muted-foreground">{offer.error}</p>}
        {cloudPhone && offer && <Action variant="ghost" size="sm" run={() => send(code.session, cloudPhone)}>Send to {cloudPhone.name} again</Action>}
        <QrImage modules={code.modules} label="Camera session QR code" width={offer?.sent ? 160 : 240} />
        <p className="m-0 text-center text-sm">{offer?.sent ? "Or scan instead: " : "On your phone: "}Saiph → Use phone as webcam → Scan computer's camera code.</p>
        <small className="text-muted-foreground" role="timer">Works once · expires in {remaining}s. Keep this code private.</small>
      </> : <p role="status">Camera code expired. Close it and start a new session.</p>}
    </div>}
    {live && pushed && <canvas ref={preview} role="img" aria-label="Live phone camera preview" className="aspect-video w-full rounded-lg bg-field object-contain" />}
    {live && !pushed && image && <img src={image} alt="Live phone camera preview" className="aspect-video w-full rounded-lg bg-field object-contain"
      style={measurement?.rotation ? { transform: `rotate(${measurement.rotation}deg)` } : undefined} />}
    {live && <p className="m-0 text-sm text-muted-foreground" role="status">
      {camera?.local_resolution || "720p"} · target {activeFps} fps · {camera?.local_quality === "high" ? "High detail" : "Standard"}
      {measurement?.source_width && measurement?.source_height ? ` · phone ${measurement.source_width}×${measurement.source_height}` : ""}
      {typeof measurement?.fps === "number" ? ` · receiving ${measurement.fps.toFixed(1)} fps` : ""}
      {typeof measurement?.shown === "number" ? ` · showing ${measurement.shown.toFixed(1)} fps` : ""}
      . Stop the camera to change settings.
    </p>}
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
