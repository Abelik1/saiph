// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import { Wifi } from "lucide-react";
import type { Client } from "./types";
import { Action } from "./ui";

type Peer = { name: string; code: string; state: "comparing" | "requested" };
export type NearbyStatus = { listening: boolean; expires_in?: number; peer: Peer | null; error?: string };

const validCode = (code: unknown): code is string => typeof code === "string" && /^\d{3} \d{3}$/.test(code);

/**
 * Connect without a QR code: while this is shown, the main computer answers a
 * signed-in phone on the same network. The owner compares six digits on both
 * screens; approving still asks for Windows Hello. Leaving stops listening.
 */
export function NearbyPhone({ client, onActive, onApproved }: {
  client: Client; onActive?: (active: boolean) => void; onApproved?: (label: string) => void;
}) {
  const [status, setStatus] = useState<NearbyStatus | null>(null);
  const [error, setError] = useState("");
  const active = useRef(false);
  useEffect(() => {
    let alive = true;
    let timer = 0;
    const look = () => client.call<NearbyStatus>("hosted.link.status").then(value => {
      if (!alive || !value || typeof value !== "object") return;
      const peer = value.peer && typeof value.peer.name === "string" && validCode(value.peer.code)
        && (value.peer.state === "comparing" || value.peer.state === "requested") ? value.peer : null;
      setStatus({ ...value, peer });
    }).catch(() => undefined);
    client.call<NearbyStatus>("hosted.link.start").then(value => {
      if (!alive) return;
      setStatus(value); void look();
      timer = window.setInterval(look, 1500);
    }).catch((reason: unknown) => { if (alive) setError(reason instanceof Error && reason.message ? reason.message : "Connecting without a code is unavailable. Scan the code instead."); });
    return () => {
      alive = false; window.clearInterval(timer);
      void client.call("hosted.link.stop").catch(() => undefined);
    };
  }, [client]);
  const peer = status?.peer ?? null;
  useEffect(() => {
    const now = Boolean(peer);
    if (now !== active.current) { active.current = now; onActive?.(now); }
  }, [peer, onActive]);
  if (error) return <p className="m-0 text-sm text-muted-foreground" role="status">{error}</p>;
  if (!status) return null;
  if (peer) return <div className="grid gap-3 rounded-[12px] border border-secondary-border p-4" aria-label="Nearby phone">
    <p className="m-0 font-medium">{peer.name} wants to connect</p>
    <p className="m-0 text-sm text-muted-foreground">Check that your phone shows this code:</p>
    <p className="m-0 font-mono text-[32px] font-semibold tracking-[0.18em]" aria-label={"Comparison code " + peer.code}>{peer.code}</p>
    {peer.state === "comparing"
      ? <p role="status" className="m-0 text-sm text-muted-foreground">Tap <strong>Codes match</strong> on your phone first. If the codes differ, stop on the phone and scan the code instead.</p>
      : <div className="flex flex-wrap items-center gap-3">
        <Action variant="default" run={async () => {
          const result = await client.call<{ approved?: string; label?: string }>("hosted.link.approve", { code: peer.code, confirmed: true });
          if (result?.approved) onApproved?.(typeof result.label === "string" ? result.label : peer.name);
        }}>Codes match, approve</Action>
        <small className="text-muted-foreground">Windows asks you to confirm it's you.</small>
      </div>}
  </div>;
  return <p className="m-0 flex items-center gap-2 text-sm text-muted-foreground" role="status">
    <Wifi className="size-4 shrink-0" />{status.listening
      ? "On the same Wi-Fi? On your phone, tap Find my computer. No code to scan."
      : status.error || "Stopped looking for nearby phones. Close and reopen this window to try again."}
  </p>;
}
