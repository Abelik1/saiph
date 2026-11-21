// SPDX-License-Identifier: AGPL-3.0-or-later
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";
import { MAX_RESPONSE_BYTES, PROTOCOL, validateCall, type Packet } from "./contract.cjs";

export class PythonService extends EventEmitter {
  private child?: ChildProcessWithoutNullStreams;
  private pending = new Map<string, { resolve: (packet: Packet) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }>();
  private ready = false;
  private stopping = false;
  private buffer = Buffer.alloc(0);

  async start(python: string, repo: string, config: string, mode = "isolated", packaged = false): Promise<void> {
    const env: NodeJS.ProcessEnv = { ...process.env, PYTHONPATH: `${repo}/src`, ORION_MINI_TEST: "1", PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" };
    delete env.ELECTRON_RUN_AS_NODE;
    delete env.NODE_OPTIONS;
    if (mode === "live") delete env.ORION_MINI_TEST;
    const child = this.child = spawn(python, [...(packaged ? [] : ["-m", "orion_mini.electron_service"]), "--config", config], {
      cwd: repo, env, windowsHide: true, stdio: ["pipe", "pipe", "pipe"],
    });
    // Drain diagnostics separately. Protocol output never goes into application logs.
    child.stderr.on("data", () => {});
    child.stdin.on("error", () => this.fail(new Error("The desktop service connection closed.")));
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => { reject(new Error("The desktop service did not become ready.")); void this.stop(); }, 30_000);
      const startupFailed = (error: Error) => { clearTimeout(timer); reject(error); };
      this.once("failed", startupFailed);
      child.on("error", () => this.fail(new Error("The desktop service could not start.")));
      child.on("exit", () => this.fail(new Error("The desktop service stopped. Reopen this test session.")));
      child.stdout.on("data", (chunk: Buffer) => {
        this.buffer = Buffer.concat([this.buffer, chunk]);
        let end: number;
        while ((end = this.buffer.indexOf(10)) !== -1) {
          if (end > MAX_RESPONSE_BYTES) { this.fail(new Error("Desktop service response is too large.")); void this.stop(); return; }
          const line = this.buffer.subarray(0, end);
          this.buffer = this.buffer.subarray(end + 1);
          try {
            const packet = JSON.parse(line.toString("utf8"));
            if (!this.ready) {
              if (packet.type !== "ready" || packet.protocol !== PROTOCOL || packet.mode !== mode
                || !Array.isArray(packet.methods) || !packet.methods.includes("state")) throw new Error();
              this.ready = true;
              clearTimeout(timer);
              this.removeListener("failed", startupFailed);
              resolve();
            } else if (typeof packet.type === "string") {
              if (!["changed", "native", "frame", "shell", "screen", "notification"].includes(packet.type)) throw new Error();
              this.emit(packet.type, packet);
            } else {
              if (typeof packet.id !== "string" || typeof packet.ok !== "boolean") throw new Error();
              const pending = this.pending.get(packet.id);
              if (!pending) continue;
              clearTimeout(pending.timer);
              this.pending.delete(packet.id);
              pending.resolve(packet);
            }
          } catch {
            this.fail(new Error("Invalid desktop service protocol.")); void this.stop(); return;
          }
        }
        if (this.buffer.length > MAX_RESPONSE_BYTES) { this.fail(new Error("Desktop service response is too large.")); void this.stop(); }
      });
    });
  }

  call(method: string, args: unknown, control = false): Promise<Packet> {
    validateCall(method, args);
    if (!this.ready || this.stopping) return Promise.reject(new Error("The desktop service is unavailable."));
    if (this.pending.size >= 16) return Promise.reject(new Error("The desktop service is busy. Try again shortly."));
    const id = randomUUID();
    return new Promise((resolve, reject) => {
      const timeout = method === "app.update.now" || method === "app.update.download" ? 30 * 60 * 1000
        : method === "cloud.client.install" ? 11 * 60 * 1000 : method === "components.install" ? 10 * 60 * 1000 : 150_000;
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("The desktop service did not respond.")); }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.child!.stdin.write(JSON.stringify({ id, method, args, ...(control ? { type: "control" } : {}) }) + "\n");
    });
  }

  async control(method: string, args: unknown = {}): Promise<unknown> {
    const result = await this.call(method, args, true);
    if (!result.ok) throw new Error(result.error || "The native operation failed.");
    return result.result;
  }

  nativeReply(id: string, result: unknown, error = false): void {
    if (this.ready && !this.stopping) this.child!.stdin.write(JSON.stringify({ native_id: id, ok: !error, result }) + "\n");
  }

  private fail(error: Error): void {
    this.ready = false;
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error); }
    this.pending.clear();
    if (!this.stopping) this.emit("failed", error);
  }

  async stop(): Promise<void> {
    this.stopping = true;
    this.fail(new Error("The desktop is closing."));
    const child = this.child;
    if (!child || !child.pid || child.exitCode !== null || child.signalCode !== null) return;
    await new Promise<void>(resolve => {
      const timer = setTimeout(() => { child.kill(); }, 3000);
      child.once("close", () => { clearTimeout(timer); resolve(); });
      child.stdin.end(); // EOF also shuts down the child when its parent disappears.
    });
  }
}
