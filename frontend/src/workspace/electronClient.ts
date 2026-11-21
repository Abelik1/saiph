// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, DroppedFiles, FrameInfo } from "./types";

type Reply = { ok: boolean; result?: unknown; error?: string; revision?: string; unchanged?: boolean };
export type ElectronBridge = {
  version: number;
  request(method: string, args: Record<string, unknown>): Promise<Reply>;
  subscribe(callback: () => void): () => void;
  onDrop?(callback: (files: DroppedFiles) => void): () => void;
  onDragging?(callback: (active: boolean) => void): () => void;
  onFrame?(callback: (frame: FrameInfo) => void): () => void;
};

export function electronClient(bridge: ElectronBridge, share: (previous: unknown, next: unknown) => unknown): Client {
  if (bridge.version !== 1) throw new Error("The desktop connection version is incompatible. Reopen Saiph.");
  let last: { revision?: string; value: unknown } | undefined;
  return {
    async call<T>(method: string, args: Record<string, unknown> = {}): Promise<T> {
      const reply = await bridge.request(method, method === "state" && last?.revision ? { ...args, revision: last.revision } : args);
      if (!reply.ok) throw new Error(reply.error || "The operation failed.");
      if (method !== "state") return reply.result as T;
      if (reply.unchanged) {
        if (!last?.revision || reply.revision !== last.revision) throw new Error("The dashboard needs a fresh snapshot. Reopen Saiph.");
        return last.value as T;
      }
      const value = share(last?.value, reply.result);
      last = { value, revision: typeof reply.revision === "string" && /^[a-f0-9]{64}$/.test(reply.revision) ? reply.revision : undefined };
      return value as T;
    },
    subscribe: (callback) => bridge.subscribe(callback),
    ...(bridge.onDrop ? { onDrop: bridge.onDrop } : {}),
    ...(bridge.onDragging ? { onDragging: bridge.onDragging } : {}),
    ...(bridge.onFrame ? { onFrame: bridge.onFrame } : {}),
  };
}
