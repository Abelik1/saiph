// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { Card } from "./ui";

/** QR modules from the desktop. The grid is itself a private invitation credential. */
export type PairingQrCode = { modules: string[]; expires_at: string; expires_in: number };

export function validQr(qr: unknown): qr is PairingQrCode {
  const value = qr as PairingQrCode;
  const size = Array.isArray(value?.modules) ? value.modules.length : 0;
  return size >= 29 && size <= 185 && size % 4 === 1
    && Number.isFinite(value.expires_in) && value.expires_in > 0 && value.expires_in <= 3660
    && typeof value.expires_at === "string" && Number.isFinite(Date.parse(value.expires_at))
    && value.modules.every((row) => typeof row === "string" && row.length === size && /^[01]+$/.test(row));
}

function secondsLeft(qr: PairingQrCode, shownAt: number) {
  return Math.max(0, Math.ceil(qr.expires_in - (Date.now() - shownAt) / 1000));
}

function remaining(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export function PairingQr({ qr, shownAt, onExpire, onClose }: { qr: PairingQrCode; shownAt: number; onExpire: () => void; onClose: () => void }) {
  const [seconds, setSeconds] = useState(() => secondsLeft(qr, shownAt));
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds(secondsLeft(qr, shownAt)), 1000);
    return () => window.clearInterval(timer);
  }, [qr, shownAt]);
  useEffect(() => { if (seconds <= 0) onExpire(); }, [seconds, onExpire]);
  const size = qr.modules.length;
  const path = qr.modules.map((row, y) => [...row].map((cell, x) => cell === "1" ? `M${x} ${y}h1v1h-1z` : "").join("")).join("");
  return <Card title="Pair a phone" subtitle="In the Saiph app on your phone, tap Scan pairing QR." actions={<button type="button" className="text-button" onClick={onClose}>Close</button>}>
    {/* Fixed black on white in every theme so phone cameras can read it. */}
    <svg className="pairing-qr" role="img" aria-label="Pairing QR code" viewBox={`0 0 ${size} ${size}`} width={264} height={264} shapeRendering="crispEdges">
      <rect width={size} height={size} fill="#fff" /><path d={path} fill="#000" />
    </svg>
    <p role="timer" aria-live="off">Expires in {remaining(seconds)}. Works once.</p>
    <p className="muted">This QR is a private invitation. Show it only to your own phone, and don't photograph, share or screen-share it. Close it if someone else can see your screen.</p>
  </Card>;
}
