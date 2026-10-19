// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import type { AppUpdate, Client, UpdateRelease } from "./types";
import { Action, Card } from "./ui";

type Release = UpdateRelease;
type Reason = "cloud_manual" | "cloud_unavailable" | "cloud_signed_out" | "cloud_unofficial";
type Check = {supported: boolean; available: boolean; release: Release | null; reason?: Reason; notes?: string; source?: "hub" | "cloud"};
type Progress = {state: "idle" | "downloading" | "verifying" | "ready" | "failed"; done: number; total: number};

const REASONS: Record<Reason, string> = {
  cloud_manual: "Desktop updates from your Saiph account aren't available in this build. Download the latest version from your account.",
  cloud_unavailable: "Your Saiph account doesn't offer desktop updates yet. Download the latest version from your account.",
  cloud_signed_out: "Sign in to your Saiph account to check for updates.",
  cloud_unofficial: "Automatic updates come only from the official Saiph service. Download updates from your deployment's administrator.",
};

function size(bytes: number) {
  return bytes >= 1_000_000 ? `${Math.round(bytes / 1_000_000)} MB` : `${Math.max(1, Math.round(bytes / 1000))} kB`;
}

/**
 * Check, download and verify, then a separate Restart to update. The source is this
 * computer's own: its Saiph account, or its paired self-hosted server. ``update`` is
 * the state shared with the footer's Update button and the six-hourly check, so an
 * update found or started there shows here too.
 */
export function Updates({ client, status, cloud = false, update }: { client: Client; status?: {state: string; code: string}; cloud?: boolean; update?: AppUpdate }) {
  const [result, setResult] = useState<Check | null>(null);
  const [localDownload, setDownloading] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [localReady, setReady] = useState<string | null>(null);
  const [localRestart, setRestarting] = useState(false);
  const shared = update?.state ?? "none";
  const downloading = localDownload || shared === "downloading";
  const ready = localReady ?? (shared === "ready" ? update?.version ?? null : null);
  const restarting = localRestart || shared === "installing";

  useEffect(() => {
    if (!downloading) return;
    let live = true;
    const poll = async () => {
      try { const value = await client.call<Progress>("app.update.progress"); if (live) setProgress(value); } catch { /* the download call reports failures */ }
    };
    void poll();
    const timer = window.setInterval(poll, 500);
    return () => { live = false; window.clearInterval(timer); };
  }, [client, downloading]);

  // An offer found by the six-hourly check or the footer, until this panel checks itself.
  const found = !result && shared === "available" && update?.release ? update : null;
  const place = result?.source === "cloud" || (!result && (cloud || update?.source === "cloud")) ? "your Saiph account" : "your Saiph server";
  const message = restarting ? "Installing your update. Saiph will close and reopen when installation finishes."
    : ready ? `Saiph ${ready} is downloaded and verified. Restart Saiph to finish updating.`
    : downloading ? (progress?.state === "verifying" ? "Checking the download…"
      : progress && progress.total > 0 ? `Downloading… ${Math.floor(progress.done * 100 / progress.total)}% (${size(progress.done)} of ${size(progress.total)})` : "Downloading…")
    : result?.reason ? REASONS[result.reason] ?? REASONS.cloud_manual
    : found ? `Saiph ${found.version} is available.`
    : shared === "checking" ? "Checking for updates…"
    : !result ? `Updates come from ${place}.`
    : !result.supported ? "This development build uses its existing source update tools."
    : result.available ? `Saiph ${result.release?.version} is available.`
    : result.source === "cloud" ? "You have the latest version." : "You have the latest build available on your server.";

  const download = async (release: Release) => {
    setDownloading(true); setProgress(null);
    try {
      const staged = await client.call<{staged: boolean; version: string}>("app.update.download", {release});
      setReady(staged.version);
    } finally { setDownloading(false); }
  };

  const offered = ready ? null : result?.available ? result.release : found?.release ?? null;
  const notes = result ? result.notes : found?.notes;
  const busy = downloading || restarting || shared === "checking";
  return <Card title="Updates" subtitle="Keep this edition of Saiph up to date.">
    {status?.state === "failed" && <p className="inline-error" role="alert">The previous update did not finish. Your installed version is still available. Check for updates to try again.</p>}
    {shared === "failed" && update?.error && status?.state !== "failed" && <p className="inline-error" role="alert">{update.error}</p>}
    <p className="muted" role="status">{message}</p>
    {downloading && <progress aria-label="Download progress" max={progress?.total || undefined} value={progress?.total ? progress.done : undefined} />}
    {offered && notes && <div className="update-notes"><strong>What's new</strong><p className="muted">{notes}</p></div>}
    {!ready && <Action disabled={busy} run={async () => setResult(await client.call<Check>("app.update.check"))}>Check for updates</Action>}
    {offered && <Action className="primary" disabled={busy} run={() => download(offered)}>
      Download update ({size(offered.bytes)})</Action>}
    {ready && <Action className="primary" disabled={restarting} run={async () => {
      setRestarting(true);
      try { await client.call("app.update.restart"); }
      catch (error) { setRestarting(false); throw error; }
    }}>Restart to update</Action>}
  </Card>;
}
