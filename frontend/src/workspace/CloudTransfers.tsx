// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, FileText, LoaderCircle, RotateCw, X } from "lucide-react";
import type { Client, HostedOffer, HostedTransfer } from "./types";
import { Action } from "./ui";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";
import { cn } from "@/lib/utils";

/** "1.4 MB" or "42 KB": the units Saiph's size limit is written in. */
export function fileSize(size: number) {
  return size >= 1024 * 1024 ? `${(size / 1048576).toFixed(1)} MB` : `${Math.max(0.1, size / 1024).toFixed(1)} KB`;
}

/** Saiph Cloud keeps a file offer for five minutes; say how long is left. */
export function offerExpiry(expiresAt: number | undefined, now = Date.now() / 1000) {
  if (!expiresAt) return "Ready to save";
  const left = Math.floor(expiresAt - now);
  if (left <= 0) return "Expired · ask the sender to share it again";
  if (left < 60) return `Save within ${left} s`;
  return `Save within ${Math.ceil(left / 60)} min`;
}

/** Re-render on a slow tick while something on screen counts down. */
export function useNow(active: boolean, seconds = 5) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    setNow(Date.now() / 1000);
    const timer = window.setInterval(() => setNow(Date.now() / 1000), seconds * 1000);
    return () => window.clearInterval(timer);
  }, [active, seconds]);
  return now;
}

export function transferStatus(transfer: HostedTransfer) {
  switch (transfer.state) {
    case "queued": return `Waiting to send to ${transfer.target_name}`;
    case "connecting": return `Connecting to ${transfer.target_name} on your network…`;
    case "sending": return `Sending to ${transfer.target_name}${transfer.route === "lan" ? " directly" : ""} · ${Math.round(transfer.progress * 100)}%`;
    case "retrying": return `Connection lost · retrying${transfer.retry_in ? ` in ${transfer.retry_in} s` : ""}`;
    case "failed": return transfer.error || "Not sent.";
    case "sent": return `Sent to ${transfer.target_name}`;
  }
}

/**
 * Files this computer is sending, directly over the local network or with Saiph Cloud:
 * progress, automatic retries after a dropped connection, a final failure with Retry,
 * and a brief "Sent to …".
 */
export function CloudTransfers({ transfers, target, client }: { transfers?: HostedTransfer[]; target?: string; client: Client }) {
  const rows = (transfers || []).filter((row) => !target || row.target === target);
  if (!rows.length) return null;
  return (
    <div className="mb-3 grid gap-1.5" aria-label="Files you are sending">
      {rows.map((row) => {
        const busy = row.state === "queued" || row.state === "connecting" || row.state === "sending" || row.state === "retrying";
        const Icon = row.state === "sent" ? CheckCircle2 : row.state === "failed" ? AlertCircle : busy ? LoaderCircle : FileText;
        return (
          <Item key={row.id} variant="outline" size="sm" data-state={row.state}>
            <ItemMedia className={cn("size-8", row.state === "failed" && "bg-status-off-surface text-status-off", row.state === "sent" && "bg-status-on-surface text-status-on")}>
              <Icon className={cn((row.state === "sending" || row.state === "connecting") && "spin")} />
            </ItemMedia>
            <ItemContent>
              <ItemTitle>{row.name}</ItemTitle>
              <ItemDescription role={row.state === "failed" ? "alert" : "status"}>
                {fileSize(row.size)} · {transferStatus(row)}
              </ItemDescription>
              {busy && row.state !== "queued" && row.state !== "connecting" && (
                <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={`Sending ${row.name}`}
                  aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(row.progress * 100)}>
                  <div className={cn("h-full rounded-full bg-primary transition-[width]", row.state === "retrying" && "opacity-50")} style={{ width: `${Math.round(row.progress * 100)}%` }} />
                </div>
              )}
            </ItemContent>
            {row.state === "failed" && (
              <ItemActions>
                <Action variant="tonal" size="sm" ariaLabel={`Retry ${row.name}`} run={() => client.call("hosted.file.retry", { id: row.id })}><RotateCw />Retry</Action>
                <Action variant="ghost" size="icon-sm" ariaLabel={`Dismiss ${row.name}`} run={() => client.call("hosted.file.dismiss", { id: row.id })}><X /></Action>
              </ItemActions>
            )}
          </Item>
        );
      })}
    </div>
  );
}

/** A received file's line: Cloud offers count down; files received over the network show progress, then wait for Save. */
export function offerStatus(offer: HostedOffer, now = Date.now() / 1000) {
  if (offer.route !== "lan") return offerExpiry(offer.expires_at, now);
  if (offer.state === "receiving") return `Receiving over your network · ${Math.round((offer.progress || 0) * 100)}%`;
  if (offer.state === "failed") return offer.error || "Not received.";
  return `Received over your network · ${offerExpiry(offer.expires_at, now)}`;
}

/**
 * One file offered to this computer. Save puts it in Downloads → Saiph. A Cloud offer
 * needs Saiph Cloud to save (`cloudReady`); a file received over the network is already here.
 */
export function ReceivedFile({ offer, client, now, cloudReady = true }: { offer: HostedOffer; client: Client; now?: number; cloudReady?: boolean }) {
  const lan = offer.route === "lan";
  const receiving = lan && offer.state === "receiving";
  const failed = lan && offer.state === "failed";
  const progress = Math.round((offer.progress || 0) * 100);
  return (
    <Item variant="outline" size="sm" data-state={offer.state || "ready"}>
      <ItemMedia className={cn("size-8", failed && "bg-status-off-surface text-status-off")}>
        {receiving ? <LoaderCircle className="spin" /> : failed ? <AlertCircle /> : <FileText />}
      </ItemMedia>
      <ItemContent>
        <ItemTitle>{offer.name}</ItemTitle>
        <ItemDescription role={failed ? "alert" : "status"}>{fileSize(offer.size)} · {offerStatus(offer, now)}</ItemDescription>
        {receiving && (
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={`Receiving ${offer.name}`}
            aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
            <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${progress}%` }} />
          </div>
        )}
      </ItemContent>
      <ItemActions>
        {!receiving && !failed && <Action variant="tonal" size="sm" ariaLabel={"Save " + offer.name} disabled={!lan && !cloudReady}
          run={() => client.call("hosted.file.save", { id: offer.id })}>Save file</Action>}
        {(receiving || failed) && <Action variant="ghost" size="icon-sm" ariaLabel={`${receiving ? "Stop receiving" : "Dismiss"} ${offer.name}`}
          run={() => client.call("hosted.file.dismiss", { id: offer.id })}><X /></Action>}
      </ItemActions>
    </Item>
  );
}
