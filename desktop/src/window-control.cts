// SPDX-License-Identifier: AGPL-3.0-or-later
// File control belongs only to the explicitly launched isolated UI-test session.
import type { BrowserWindow } from "electron";

export function applyWindowControl(window: BrowserWindow, request: Record<string, unknown>, nonce: string): void {
  if (request.nonce !== nonce || !Number.isInteger(request.id) || (request.id as number) < 1
    || Object.keys(request).some(key => !["nonce", "id", "action", "bounds"].includes(key))) throw new Error("Invalid test-window request.");
  switch (request.action) {
    case "bounds": {
      const bounds = request.bounds as Record<string, unknown>;
      if (!bounds || Object.keys(bounds).sort().join(",") !== "height,width,x,y"
        || !["x", "y", "width", "height"].every(key => Number.isInteger(bounds[key]))
        || Math.abs(bounds.x as number) > 10000 || Math.abs(bounds.y as number) > 10000
        || (bounds.width as number) < 900 || (bounds.width as number) > 2000
        || (bounds.height as number) < 620 || (bounds.height as number) > 1400) throw new Error("Invalid test-window bounds.");
      window.setBounds(bounds as { x: number; y: number; width: number; height: number });
      break;
    }
    case "maximize": window.maximize(); break;
    case "minimize": window.minimize(); break;
    case "restore": window.restore(); break;
    default: throw new Error("Unknown test-window action.");
  }
}
