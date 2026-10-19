// SPDX-License-Identifier: AGPL-3.0-or-later
// Live camera and phone-screen pictures pushed by the desktop shell.
// The shell announces each new frame with a little metadata; the picture itself
// is loaded as an image from the local frame feed, so it arrives as bytes and
// Chromium decodes it off the main thread. Only the newest frame is ever loaded:
// one decodes at a time, and anything that arrives meanwhile replaces the queue.
import type { Client, FrameInfo } from "./types";

export type FrameSource = "camera" | "screen";

export function frameUrl(source: FrameSource, sequence: number) {
  return `saiph-frame://${source}/${sequence}`;
}

/** A frame announcement from the shell, or null when it is not one we can use. */
export function validFrame(value: unknown, source: FrameSource): FrameInfo | null {
  if (!value || typeof value !== "object") return null;
  const info = value as FrameInfo;
  if (info.source !== source || !Number.isSafeInteger(info.sequence) || info.sequence < 0) return null;
  if (info.rotation !== undefined && ![0, 90, 180, 270].includes(info.rotation)) return null;
  return info;
}

/**
 * Follows `source` while the shell supports pushed frames; returns null when it
 * does not, so the caller can fall back to asking for frames.
 */
export function followFrames(client: Client, source: FrameSource,
  show: (info: FrameInfo, image: HTMLImageElement, url: string) => void, wanted: () => boolean = () => true): (() => void) | null {
  if (!client.onFrame) return null;
  let busy = false, stopped = false;
  let queued: FrameInfo | null = null;
  const load = async (info: FrameInfo) => {
    busy = true;
    const url = frameUrl(source, info.sequence);
    try {
      const image = new Image();
      image.decoding = "async";
      image.src = url;
      await image.decode();
      if (!stopped) show(info, image, url);
    } catch {
      // A frame that ended with its session, or was never served; the next one follows.
    }
    busy = false;
    const next = queued;
    queued = null;
    if (next && !stopped) void load(next);
  };
  const off = client.onFrame((raw) => {
    const info = validFrame(raw, source);
    // Hidden previews (another tab, a minimised window) skip frames entirely.
    if (!info || stopped || document.visibilityState === "hidden" || !wanted()) return;
    if (busy) queued = info;
    else void load(info);
  });
  return () => { stopped = true; queued = null; off(); };
}

/** Frames shown over the last two seconds, as a rate. */
export function showRate() {
  const times: number[] = [];
  return () => {
    const now = performance.now();
    times.push(now);
    while (times.length && times[0] < now - 2000) times.shift();
    return times.length > 1 ? (times.length - 1) / ((times[times.length - 1] - times[0]) / 1000) : 0;
  };
}
