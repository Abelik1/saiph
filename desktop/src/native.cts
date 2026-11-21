// SPDX-License-Identifier: AGPL-3.0-or-later
import { app, BrowserWindow, clipboard, ClipboardItem, dialog, Menu, nativeImage, Notification, protocol, screen, shell, Tray } from "electron";
import type { NativeImage } from "electron";
import fs from "node:fs/promises";
import { randomBytes, createHash } from "node:crypto";
import path from "node:path";
import { PythonService } from "./service.cjs";
import { BinaryServer, MAX_BINARY } from "./binary.cjs";
import { EVENT_CHANNEL } from "./contract.cjs";

const SCREEN_URL = "saiph-app://desktop/screen.html";
const origin = "saiph-app://desktop";
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
type ShellSettings = { close_to_tray: boolean; clipboard: boolean; unread: number; live: boolean; camera_live?: boolean; screen_live?: boolean };

export class NativeHost {
  tray?: Tray;
  viewer?: BrowserWindow;
  settings: ShellSettings = { close_to_tray: false, clipboard: false, unread: 0, live: false };
  private screenSession = "";
  private quietViewers = new WeakSet<BrowserWindow>();
  private media = new Map<string, { file: string; at: number }>();
  private polling = false;
  private clipboardDigest = "";
  private closing = false;
  private ringing = false;
  private cameraPrompt = false;
  private screenOpening = false;
  private clipboardTimer?: NodeJS.Timeout;
  private memoryClipboard = new Map<string, Buffer>();

  constructor(readonly window: BrowserWindow, readonly service: PythonService, readonly binary: BinaryServer,
    readonly isolated: boolean, readonly preload: string, readonly icon: string, readonly profile: string,
    readonly sessionDirectory?: string, readonly nonce?: string) {}

  async install(): Promise<void> {
    protocol.handle("saiph-frame", request => {
      const url = new URL(request.url), initiator = (request as Request & { initiatorOrigin?: string }).initiatorOrigin;
      if (request.method !== "GET" || !["camera", "screen"].includes(url.hostname) || !/^\/\d{1,15}$/.test(url.pathname)
        || url.search || url.username || url.password || (initiator && initiator !== origin)) return new Response(null, { status: 403 });
      const data = this.binary.frame(url.hostname);
      return data ? new Response(new Uint8Array(data), { headers: { ...headers, "Content-Type": "image/jpeg" } }) : new Response(null, { status: 404 });
    });
    protocol.handle("saiph-media", async request => {
      const url = new URL(request.url), initiator = (request as Request & { initiatorOrigin?: string }).initiatorOrigin;
      const item = this.media.get(url.hostname);
      if (request.method !== "GET" || url.pathname !== "/image" || url.search || (initiator && initiator !== origin)
        || !item || Date.now() - item.at > 10 * 60_000) return new Response(null, { status: 403 });
      const stat = await fs.stat(item.file);
      if (stat.size > MAX_BINARY) return new Response(null, { status: 413 });
      const data = await fs.readFile(item.file);
      return new Response(new Uint8Array(data), { headers: { ...headers, "Content-Type": "image/" + (path.extname(item.file).toLowerCase() === ".png" ? "png" : path.extname(item.file).toLowerCase() === ".webp" ? "webp" : "jpeg") } });
    });
    this.binary.on("frame", header => {
      const { kind: _kind, bytes: _bytes, ...metadata } = header;
      if (!this.window.isDestroyed() && this.window.isVisible()) this.window.webContents.send("saiph:frame", metadata);
      if (metadata.source === "screen" && this.viewer && !this.viewer.isDestroyed() && metadata.session === this.screenSession) this.viewer.webContents.send("saiph:frame", metadata);
    });
    this.service.on("shell", packet => {
      this.settings = packet.settings;
      if (!this.settings.camera_live) this.binary.clearFrames("camera");
      if (!this.settings.screen_live) this.binary.clearFrames("screen");
      if (!this.isolated) {
        this.updateBadge();
        this.tray?.setToolTip(this.settings.live ? "Saiph · Live sharing" : "Saiph");
        this.tray?.setImage(this.settings.live ? this.liveIcon() : nativeImage.createFromPath(this.icon));
      }
    });
    this.service.on("screen", packet => { void this.screenState(packet.status).catch(() => this.notify("Saiph", "The phone window could not open.")); });
    this.service.on("notification", packet => this.notify(packet.title, packet.text));
    this.service.on("native", packet => {
      void this.handle(packet.method, packet.args).then(value => this.service.nativeReply(packet.native_id, value),
        () => this.service.nativeReply(packet.native_id, null, true));
    });
    this.window.on("close", event => {
      if (!this.closing && !this.isolated && this.settings.close_to_tray && this.tray) { event.preventDefault(); this.window.hide(); }
    });
    if (!this.isolated) {
      this.tray = new Tray(this.icon);
      this.tray.setToolTip("Saiph");
      this.tray.on("click", () => this.show());
      this.tray.on("right-click", () => { void this.phoneMenu(); });
      this.clipboardTimer = setInterval(() => { void this.pollClipboard(); }, 500);
      this.clipboardTimer.unref();
    }
  }

  show(): void { this.window.restore(); this.window.show(); this.window.focus(); }
  notify(title: string, body: string): void {
    if (this.isolated || !Notification.isSupported()) return;
    const notification = new Notification({ title, body, icon: this.icon });
    notification.on("click", () => { this.show(); void this.service.control("open.phone").catch(() => {}); });
    notification.show();
  }

  private filters(value: unknown) {
    if (typeof value !== "string") return undefined;
    const result = [...value.matchAll(/([^;]+?)\s*\(([^)]+)\)/g)].map(match => ({ name: match[1].trim(),
      extensions: match[2].split(/\s+/).map(item => item.replace(/^\*\./, "")).filter(item => /^[a-z0-9_-]+$/i.test(item)) })).filter(item => item.extensions.length);
    return result.length ? result : undefined;
  }

  private async pick(method: string, args: Record<string, unknown>): Promise<string> {
    if (this.isolated) {
      // Fixture pickers cannot select owner files or change the system clipboard.
      if (!this.sessionDirectory) return "";
      try {
        const fixture = JSON.parse(await fs.readFile(path.join(this.sessionDirectory, "native-fixtures.json"), "utf8"));
        if (fixture.nonce !== this.nonce || typeof fixture[method] !== "string") return "";
        const selected = path.resolve(fixture[method]);
        const relative = path.relative(this.profile, selected);
        if (relative.startsWith("..") || path.isAbsolute(relative)) return "";
        return selected;
      } catch { return ""; }
    }
    const title = typeof args.title === "string" ? args.title.slice(0, 200) : "Saiph";
    if (method === "dialog.save") return (await dialog.showSaveDialog(this.window, { title, filters: this.filters(args.filter) })).filePath || "";
    const result = await dialog.showOpenDialog(this.window, { title, filters: this.filters(args.filter), properties: [method === "dialog.directory" ? "openDirectory" : "openFile"] });
    return result.canceled ? "" : result.filePaths[0] || "";
  }

  async handle(method: string, args: Record<string, unknown>): Promise<unknown> {
    if (method === "beep") { if (!this.isolated) shell.beep(); return { ok: true }; }
    if (["dialog.open", "dialog.save", "dialog.directory"].includes(method)) return this.pick(method, args);
    if (method === "window.show") { this.show(); return { shown: true }; }
    if (method === "app.quit") { setImmediate(() => app.quit()); return { ok: true }; }
    if (method === "app.restart") { app.relaunch(); setImmediate(() => app.quit()); return { ok: true }; }
    if (method === "screen.show") { if (!this.viewer) await this.screenState({ state: "live", session: this.screenSession, input: true }); this.viewer?.show(); this.viewer?.focus(); return { shown: true }; }
    if (method === "clipboard.text") { await this.writeClipboard("text/plain", Buffer.from(String(args.text), "utf8")); return { copied: true }; }
    if (method === "clipboard.write") {
      const token = String(args.token), data = await this.binary.take(token);
      const permitted = await this.service.control("clipboard.authorize", { token }) as { allowed: boolean };
      if (!permitted.allowed) return { copied: false };
      await this.writeClipboard(String(args.mime), data);
      return { copied: true };
    }
    if (["photo.view", "photo.copy", "photo.drag"].includes(method)) {
      if (typeof args.path !== "string" || !path.isAbsolute(args.path)) throw new Error("Invalid photo.");
      const info = await fs.stat(args.path);
      if (!info.isFile() || info.size > MAX_BINARY) throw new Error("Invalid photo size.");
      const width = Number(args.width), height = Number(args.height);
      if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width < 1 || height < 1 || width * height > 40_000_000) throw new Error("Invalid image dimensions.");
      if (method !== "photo.view") {
        if (typeof args.token !== "string" || !/^[a-f0-9]{32}$/.test(args.token)) throw new Error("Invalid original image delivery.");
        const data = await this.binary.take(args.token);
        // Python applies EXIF before native allocation; nativeImage ignores
        // JPEG orientation, so copying the original JPEG would turn it sideways.
        const picture = nativeImage.createFromBuffer(data);
        if (picture.isEmpty() || picture.getSize().width !== width || picture.getSize().height !== height) throw new Error("The original image could not be decoded.");
        if (method === "photo.copy") { await this.writeClipboard("image/png", data); return { copied: true, width, height }; }
        if (!this.isolated) this.window.webContents.startDrag({ file: args.path, icon: picture.resize({ width: 64 }) });
        return { dragged: !this.isolated, ready: true };
      }
      const token = randomBytes(24).toString("hex");
      if (this.media.size >= 64) this.media.delete(this.media.keys().next().value!);
      this.media.set(token, { file: args.path, at: Date.now() });
      return { url: `saiph-media://${token}/image`, width, height, size: info.size };
    }
    if (method === "open") {
      if (this.isolated) return { opened: false, isolated: true };
      if (typeof args.path === "string" && path.isAbsolute(args.path)) {
        const error = await shell.openPath(args.path);
        if (error) throw new Error(error);
      } else {
        const url = new URL(String(args.url));
        if (!["https:", "http:", "mailto:", "ms-settings:"].includes(url.protocol) || url.username || url.password) throw new Error("Unsupported external link.");
        await shell.openExternal(url.href);
      }
      return { opened: true };
    }
    if (method === "send.confirm") {
      if (this.isolated) return -1;
      const names = args.devices as string[];
      const result = await dialog.showMessageBox(this.window, { type: "question", title: "Send to phone",
        message: `Send ${String(args.description)} to:`, buttons: [...names, "Cancel"], defaultId: names.length, cancelId: names.length });
      return result.response < names.length ? result.response : -1;
    }
    if (method === "ring") {
      if (this.ringing || this.isolated) return { ok: true };
      this.ringing = true;
      this.show();
      const timer = setInterval(() => shell.beep(), 1200);
      // Rings for 30 seconds, then the window closes itself: nobody may be at this computer.
      const lapse = new AbortController();
      const stop = setTimeout(() => lapse.abort(), 30000);
      try { shell.beep(); await dialog.showMessageBox(this.window, { type: "info", title: "Saiph", message: `${String(args.phone)} is looking for this computer.`, buttons: ["Stop"], signal: lapse.signal }); }
      finally { clearInterval(timer); clearTimeout(stop); this.ringing = false; }
      return { stopped: true };
    }
    if (method === "camera.request") {
      if (this.cameraPrompt || this.isolated) return false;
      this.cameraPrompt = true;
      this.show();
      // An unanswered request lapses with the phone's own one-minute wait.
      const lapse = new AbortController();
      const timer = setTimeout(() => lapse.abort(), 60000);
      try {
        const result = await dialog.showMessageBox(this.window, { type: "question", title: "Saiph",
          message: `${String(args.phone)} wants to be this computer's webcam.`,
          detail: "Audio stays off. Closing the camera page on the phone stops it.",
          buttons: ["Accept", "Decline"], defaultId: 0, cancelId: 1, signal: lapse.signal });
        return result.response === 0 && !lapse.signal.aborted;
      } finally { clearTimeout(timer); this.cameraPrompt = false; }
    }
    throw new Error("Unknown native desktop action.");
  }

  private async writeClipboard(mime: string, data: Buffer): Promise<void> {
    if (!["text/plain", "image/png"].includes(mime) || data.length > MAX_BINARY) throw new Error("Unsupported clipboard content.");
    this.clipboardDigest = createHash("sha256").update(mime).update(data).digest("hex");
    if (this.isolated) { this.memoryClipboard.clear(); this.memoryClipboard.set(mime, data); return; }
    await clipboard.write([new ClipboardItem({ [mime]: new Blob([new Uint8Array(data)], { type: mime }) })]);
  }

  private async pollClipboard(): Promise<void> {
    if (!this.settings.clipboard || this.polling || this.closing) return;
    this.polling = true;
    try {
      const items = await clipboard.read();
      const item = items[0];
      const mime = ["image/png", "image/jpeg", "image/webp", "text/plain"].find(type => item?.types.includes(type));
      if (!mime) { if (this.clipboardDigest !== "clear") await this.binary.send({ kind: "clipboard.local", mime: "clear" }, Buffer.alloc(0)); this.clipboardDigest = "clear"; return; }
      const blob = await item.getType(mime) as Blob;
      if (blob.size > 16 * 1024 * 1024 || !this.settings.clipboard) return;
      const data = Buffer.from(await blob.arrayBuffer()), digest = createHash("sha256").update(mime).update(data).digest("hex");
      if (digest === this.clipboardDigest) return;
      this.clipboardDigest = digest;
      await this.binary.send({ kind: "clipboard.local", mime }, data);
    } catch { /* A locked OS clipboard is retried on the next tick. */ }
    finally { this.polling = false; }
  }

  async screenState(state: Record<string, unknown>): Promise<void> {
    if (state.state !== "live") {
      if (this.viewer) { this.quietViewers.add(this.viewer); this.viewer.close(); this.viewer = undefined; }
      this.screenSession = "";
      this.binary.clearFrames("screen");
      return;
    }
    const sessionId = String(state.session);
    if (this.viewer && this.screenSession === sessionId) { this.viewer.webContents.send(EVENT_CHANNEL); return; }
    if (this.screenOpening && this.screenSession === sessionId) return;
    if (this.viewer) { this.quietViewers.add(this.viewer); this.viewer.close(); }
    this.screenSession = sessionId;
    this.screenOpening = true;
    try {
    const geometry = await this.service.control("screen.geometry.read") as Record<string, number> | null;
    if (this.screenSession !== sessionId || this.closing) return;
    const valid = geometry && ["x", "y", "width", "height"].every(key => Number.isInteger(geometry[key])) && geometry.width >= 200 && geometry.height >= 200 && geometry.width <= 20000 && geometry.height <= 20000;
    const display = valid ? screen.getDisplayMatching({ x: geometry.x, y: geometry.y, width: geometry.width, height: geometry.height }) : screen.getPrimaryDisplay();
    const area = display.workArea;
    const width = Math.max(300, Math.min(valid ? geometry.width : 420, area.width));
    const height = Math.max(360, Math.min(valid ? geometry.height : 800, area.height));
    const x = valid ? Math.max(area.x, Math.min(geometry.x, area.x + area.width - width)) : area.x + Math.round((area.width - width) / 2);
    const y = valid ? Math.max(area.y, Math.min(geometry.y, area.y + area.height - height)) : area.y + Math.round((area.height - height) / 2);
    const viewer = this.viewer = new BrowserWindow({ width, height, x, y, minWidth: 300, minHeight: 360, title: "Saiph phone screen", icon: this.icon, backgroundColor: "#040916",
      webPreferences: { preload: this.preload, sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: !this.sessionDirectory } });
    viewer.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    viewer.webContents.on("will-navigate", (event, url) => { if (url !== SCREEN_URL) event.preventDefault(); });
    let timer: NodeJS.Timeout | undefined;
    const remember = () => { clearTimeout(timer); timer = setTimeout(() => { if (!viewer.isDestroyed()) void this.service.control("screen.geometry", { bounds: viewer.getBounds() }).catch(() => {}); }, 400); };
    viewer.on("move", remember);
    viewer.on("resize", remember);
    viewer.on("close", () => {
      clearTimeout(timer);
      void this.service.control("screen.geometry", { bounds: viewer.getBounds() }).catch(() => {});
      if (!this.quietViewers.has(viewer) && !this.closing && this.screenSession === sessionId) void this.service.call("screen.stop", {}).catch(() => {});
      if (this.viewer === viewer) this.viewer = undefined;
    });
    await viewer.loadURL(SCREEN_URL);
    } finally { if (this.screenSession === sessionId) this.screenOpening = false; }
  }

  acceptsViewer(contents: Electron.WebContents): boolean { return !!this.viewer && !this.viewer.isDestroyed() && contents === this.viewer.webContents; }

  private async phoneMenu(): Promise<void> {
    const entries = await this.service.control("tray.entries").catch(() => []) as [string, string | null, Record<string, unknown>][];
    const phones = entries.map(([label, method, args]) => ({ label, enabled: method !== null, click: () => {
      if (method === "window.show") this.show();
      else if (method) void this.service.call(method, args || {}).catch(() => this.notify("Saiph", "The phone action did not finish."));
    } }));
    this.tray?.popUpContextMenu(Menu.buildFromTemplate([{ label: "Open Saiph", click: () => this.show() },
      { label: "Phone", submenu: phones }, { label: "Check for updates", click: () => { this.show(); void this.service.call("app.update.check", {}).then(packet => {
        const result = packet.result as { available?: boolean; release?: { version: string } };
        this.notify("Saiph", packet.ok ? result?.available ? `Saiph ${result.release?.version} is available. Use Update in the window to install it.` : "No newer desktop build was offered." : packet.error || "Updates are temporarily unavailable.");
      }); } }, { type: "separator" }, { label: "Quit", click: () => app.quit() }]));
  }

  private liveIcon(): NativeImage {
    const image = nativeImage.createFromPath(this.icon).resize({ width: 32, height: 32 });
    const bitmap = image.toBitmap();
    for (let y = 21; y < 32; y++) for (let x = 21; x < 32; x++) if ((x - 26) ** 2 + (y - 26) ** 2 < 25) {
      const at = (y * 32 + x) * 4;
      bitmap[at] = 0x44; bitmap[at + 1] = 0x44; bitmap[at + 2] = 0xef; bitmap[at + 3] = 255;
    }
    return nativeImage.createFromBitmap(bitmap, { width: 32, height: 32 });
  }
  private updateBadge(): void {
    const count = Math.max(0, Math.min(99, this.settings.unread || 0));
    app.setBadgeCount(count);
    if (process.platform === "win32") {
      if (!count) { this.window.setOverlayIcon(null, ""); return; }
      const bitmap = Buffer.alloc(16 * 16 * 4);
      for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) if ((x - 7.5) ** 2 + (y - 7.5) ** 2 < 60) { const at = (y * 16 + x) * 4; bitmap[at] = 0x2c; bitmap[at + 1] = 0x2b; bitmap[at + 2] = 0xc4; bitmap[at + 3] = 255; }
      const glyphs = ["111101101101111", "010110010010111", "111001111100111", "111001111001111", "101101111001001", "111100111001111", "111100111101111", "111001010010010", "111101111101111", "111101111001111"];
      const text = String(count), left = text.length === 1 ? 6 : 4;
      for (let digit = 0; digit < text.length; digit++) for (let y = 0; y < 5; y++) for (let x = 0; x < 3; x++) if (glyphs[Number(text[digit])][y * 3 + x] === "1") {
        const at = ((y + 5) * 16 + left + digit * 4 + x) * 4;
        bitmap[at] = bitmap[at + 1] = bitmap[at + 2] = bitmap[at + 3] = 255;
      }
      this.window.setOverlayIcon(nativeImage.createFromBitmap(bitmap, { width: 16, height: 16 }), `${count} unread notifications`);
    }
  }

  close(): void { this.closing = true; clearInterval(this.clipboardTimer); if (this.viewer) this.quietViewers.add(this.viewer); this.viewer?.destroy(); this.tray?.destroy(); this.media.clear(); }
}
