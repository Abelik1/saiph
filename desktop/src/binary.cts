// SPDX-License-Identifier: AGPL-3.0-or-later
import { EventEmitter } from "node:events";
import { createServer, type Server, type Socket } from "node:net";
import { randomBytes, timingSafeEqual } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

export const MAX_BINARY = 64 * 1024 * 1024;
type Header = { kind: string; bytes: number; source?: string; token?: string; mime?: string; sequence?: number; [key: string]: unknown };
export class BinaryServer extends EventEmitter {
  readonly token = randomBytes(32).toString("hex");
  address = "";
  private server?: Server;
  private socket?: Socket;
  private publisher?: Socket;
  private connections = new Set<Socket>();
  private frames = new Map<string, { header: Header; data: Buffer }>();
  private transfers = new Map<string, { data: Buffer; at: number }>();
  private closing = false;

  async listen(directory: string): Promise<void> {
    this.address = process.platform === "win32" ? `\\\\.\\pipe\\saiph-${this.token}` : path.join(directory, "media.sock");
    this.server = createServer(socket => this.accept(socket));
    await new Promise<void>((resolve, reject) => { this.server!.once("error", reject); this.server!.listen(this.address, resolve); });
    if (process.platform !== "win32") await fs.chmod(this.address, 0o600);
  }

  private accept(socket: Socket): void {
    if (this.connections.size >= 4) { socket.destroy(); return; }
    this.connections.add(socket);
    let buffer = Buffer.alloc(0), authenticated = false;
    const timer = setTimeout(() => { if (!authenticated) socket.destroy(); }, 5000);
    socket.on("error", () => {});
    socket.on("close", () => { clearTimeout(timer); this.connections.delete(socket); if (this.socket === socket) this.socket = undefined; if (this.publisher === socket) this.publisher = undefined; if (authenticated && !this.closing) this.emit("failed"); });
    socket.on("data", chunk => {
      buffer = Buffer.concat([buffer, chunk]);
      try {
        while (buffer.length >= 4) {
          const length = buffer.readUInt32BE(0);
          if (length < 1 || length > 4096) throw new Error();
          if (buffer.length < 4 + length) return;
          const header: Header = JSON.parse(buffer.subarray(4, 4 + length).toString("utf8"));
          if (!Number.isInteger(header.bytes) || header.bytes < 0 || header.bytes > MAX_BINARY) throw new Error();
          if (!authenticated) {
            if (header.kind !== "hello" || header.protocol !== 1 || header.bytes !== 0 || typeof header.token !== "string"
              || !/^[a-f0-9]{64}$/.test(header.token) || !timingSafeEqual(Buffer.from(header.token), Buffer.from(this.token))
              || !["publish", "receive"].includes(String(header.role))) throw new Error();
            if (header.role === "receive") { if (this.socket) throw new Error(); this.socket = socket; }
            else { if (this.publisher) throw new Error(); this.publisher = socket; }
            authenticated = true;
            clearTimeout(timer);
          }
          if (buffer.length < 4 + length + header.bytes) return;
          const data = Buffer.from(buffer.subarray(4 + length, 4 + length + header.bytes));
          buffer = buffer.subarray(4 + length + header.bytes);
          if (header.kind !== "hello" && this.publisher !== socket) throw new Error();
          if (header.kind === "frame" && ["camera", "screen"].includes(header.source || "") && data.length <= 8 * 1024 * 1024) {
            this.frames.set(header.source!, { header, data });
            this.emit("frame", header);
          } else if (["clipboard", "image"].includes(header.kind) && typeof header.token === "string" && /^[a-f0-9]{32}$/.test(header.token)) {
            for (const [key, value] of this.transfers) if (Date.now() - value.at > 30000) this.transfers.delete(key);
            if (this.transfers.size >= 8) throw new Error();
            this.transfers.set(header.token, { data, at: Date.now() });
            this.emit("transfer", header.token);
          } else if (header.kind !== "hello") throw new Error();
        }
        if (buffer.length > MAX_BINARY + 4100) throw new Error();
      } catch { socket.destroy(); }
    });
  }

  frame(source: string): Buffer | undefined { return this.frames.get(source)?.data; }
  metadata(source: string): Header | undefined { return this.frames.get(source)?.header; }
  clearFrames(source?: string): void { if (source) this.frames.delete(source); else this.frames.clear(); }

  async take(token: string): Promise<Buffer> {
    for (let attempt = 0; attempt < 100; attempt++) {
      const item = this.transfers.get(token);
      if (item) { this.transfers.delete(token); return item.data; }
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error("The clipboard delivery expired.");
  }

  async send(header: Record<string, unknown>, data: Buffer): Promise<void> {
    if (!this.socket || data.length > MAX_BINARY || this.socket.writableLength > MAX_BINARY) throw new Error("The native media connection is busy.");
    const metadata = Buffer.from(JSON.stringify({ ...header, bytes: data.length }));
    const size = Buffer.alloc(4);
    size.writeUInt32BE(metadata.length);
    await new Promise<void>((resolve, reject) => {
      this.socket!.write(Buffer.concat([size, metadata, data]), error => error ? reject(error) : resolve());
    });
  }

  async close(): Promise<void> {
    this.closing = true;
    for (const socket of this.connections) socket.destroy();
    this.frames.clear();
    this.transfers.clear();
    if (this.server) await new Promise<void>(resolve => this.server!.close(() => resolve()));
    if (process.platform !== "win32" && this.address) await fs.unlink(this.address).catch(() => {});
  }
}
