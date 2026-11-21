// SPDX-License-Identifier: AGPL-3.0-or-later
// Keep self-contained: sandboxed preloads may require Electron, not local modules.
import { contextBridge, ipcRenderer, webUtils } from "electron";

function subscribe(channel: string, callback: (value: unknown) => void) {
  const listener = (_event: unknown, value: unknown) => callback(value);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld("saiphDesktop", {
  version: 1,
  request: (method: string, args: Record<string, unknown>) => ipcRenderer.invoke("saiph:request", method, args),
  subscribe: (callback: () => void) => subscribe("saiph:event", callback),
  onDrop: (callback: (value: unknown) => void) => subscribe("saiph:drop", callback),
  onDragging: (callback: (value: unknown) => void) => subscribe("saiph:dragging", callback),
  onFrame: (callback: (value: unknown) => void) => {
    let active = true;
    const off = subscribe("saiph:frame", callback);
    void ipcRenderer.invoke("saiph:frame-latest").then(frames => { if (active) for (const frame of frames) callback(frame); }, () => {});
    return () => { active = false; off(); };
  },
});
const nonce = process.argv.find(value => value.startsWith("--saiph-ui-nonce="))?.split("=")[1];
if (nonce) contextBridge.exposeInMainWorld("__saiphUISession", nonce);

// Resolve file paths in the isolated preload, never from renderer strings.
window.addEventListener("DOMContentLoaded", () => {
  window.addEventListener("dragover", event => { event.preventDefault(); ipcRenderer.send("saiph:dragging", true); });
  window.addEventListener("dragleave", event => { if (!event.relatedTarget) ipcRenderer.send("saiph:dragging", false); });
  window.addEventListener("drop", event => {
    event.preventDefault();
    event.stopImmediatePropagation();
    const files = [...(event.dataTransfer?.files || [])].slice(0, 100);
    const paths = files.map(file => webUtils.getPathForFile(file)).filter(Boolean);
    ipcRenderer.send("saiph:files", paths);
  }, true);
});
