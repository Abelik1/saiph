// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { ArrowDownToLine, Hourglass, RotateCw } from "lucide-react";
import type { AppUpdate, Client } from "./types";

type Progress = {state: string; done: number; total: number};
/** Footer progress is a glance, not a meter: once a second, only while downloading. */
export const PROGRESS_MS = 1000;

/**
 * The footer's Update button. The desktop checks its own update source soon after
 * start-up and every six hours (update_schedule.py); when a newer Saiph is offered the
 * button appears with a still glow and a few slow breaths (motifs.css), never a loop;
 * busy states use still icons, not spinners, since every animated frame costs the
 * window CPU (docs/DESKTOP_PERFORMANCE.md). One click checks again, downloads and
 * verifies, installs and restarts Saiph.
 */
export function UpdateButton({ update, client }: { update?: AppUpdate; client: Client }) {
  const [pending, setPending] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [note, setNote] = useState("");
  const state = update?.state ?? "none";

  useEffect(() => {
    if (state !== "downloading") { setProgress(null); return; }
    let live = true;
    const poll = async () => {
      try { const value = await client.call<Progress>("app.update.progress"); if (live) setProgress(value); } catch { /* the update reports failures */ }
    };
    void poll();
    const timer = window.setInterval(poll, PROGRESS_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [client, state]);

  useEffect(() => {
    if (!note) return;
    const timer = window.setTimeout(() => setNote(""), 6000);
    return () => window.clearTimeout(timer);
  }, [note]);

  const run = async () => {
    setPending(true); setNote("");
    try {
      const result = await client.call<{started: boolean}>("app.update.now");
      if (!result.started) setNote("Saiph is up to date.");
    } catch { /* shown as the failed state; a busy update keeps its own state */ }
    finally { setPending(false); }
  };

  if (note && state === "none") return <span role="status" className="text-muted-foreground">{note}</span>;
  if (state === "none" && !pending) return null;

  const version = update?.version ? ` to ${update.version}` : "";
  const base = "inline-flex h-5 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-semibold tracking-normal outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/35 [&_svg]:size-3 ";
  if (state === "available" || state === "ready") {
    const label = state === "ready" ? "Restart to update" : `Update${version}`;
    return <button type="button" data-slot="update-button" data-state={state} disabled={pending} onClick={run}
      aria-label={state === "ready" ? `Restart Saiph to finish updating${version}` : `Update Saiph${version}`}
      title={state === "ready" ? "The update is downloaded and verified. Saiph will close, install it and reopen."
        : `Saiph ${update?.version ?? ""} is available. Saiph will download it, check it, install it and reopen.`}
      className={base + "update-glow cursor-pointer border-primary bg-primary text-primary-foreground hover:bg-primary-hover disabled:cursor-default disabled:opacity-70"}>
      {pending ? <Hourglass aria-hidden="true" /> : <ArrowDownToLine aria-hidden="true" />}
      {pending ? "Checking…" : label}
    </button>;
  }
  if (state === "failed" && !pending) {
    return <button type="button" data-slot="update-button" data-state="failed" onClick={run}
      title={update?.error || "The update did not finish."}
      aria-label="Update failed. Try again"
      className={base + "cursor-pointer border-status-warn/60 bg-transparent text-status-warn hover:bg-status-warn/10"}>
      <RotateCw aria-hidden="true" />Update failed · Try again
    </button>;
  }
  const busy = state === "downloading"
    ? (progress?.state === "verifying" ? "Checking the download…"
      : progress && progress.total > 0 ? `Downloading… ${Math.floor(progress.done * 100 / progress.total)}%` : "Downloading…")
    : state === "installing" ? "Installing… Saiph will reopen" : "Checking…";
  return <span role="status" data-slot="update-button" data-state={pending && state !== "downloading" && state !== "installing" ? "checking" : state}
    className={base + "border-secondary-border bg-secondary text-secondary-foreground"}>
    <Hourglass aria-hidden="true" />{busy}
  </span>;
}
