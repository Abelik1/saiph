// SPDX-License-Identifier: AGPL-3.0-or-later
import { cn } from "@/lib/utils";
import type { State } from "./types";

/** What this computer is receiving from the phone right now: only the camera and the phone screen count as live. */
export function liveSources(state: Pick<State, "camera" | "phone_screen">): ("camera" | "screen")[] {
  const sources: ("camera" | "screen")[] = [];
  if (state.camera?.running || state.camera?.local_state === "live") sources.push("camera");
  if (state.phone_screen?.state === "live") sources.push("screen");
  return sources;
}

export function liveLabel(sources: ("camera" | "screen")[]): string {
  if (sources.length === 2) return "Camera and phone screen are live";
  return sources[0] === "camera" ? "Camera is live" : "Phone screen is live";
}

/** An unmistakable red "Live" pill with a pulsing dot. */
export function LiveBadge({ label = "Live", title, className }: { label?: string; title?: string; className?: string }) {
  return <span className={cn("live-badge", className)} role="status" title={title} aria-label={title || label}>
    <span aria-hidden="true" className="live-dot" />{label}
  </span>;
}
