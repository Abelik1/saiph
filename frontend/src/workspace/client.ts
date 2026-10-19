// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, DroppedFiles, FrameInfo } from "./types";

type Signal<T> = {
  connect(fn: (value: T) => void): void;
  disconnect?(fn: (value: T) => void): void;
};
type ChannelBridge = {
  request(id: string, method: string, args: string): void;
  response: Signal<string>;
  changed: Signal<void>;
  // Held by the shell while its window is hidden; absent in older shells.
  refresh?: Signal<void>;
  dropped: Signal<string>;
  dragging: Signal<boolean>;
  // Absent in shells from before the frame feed.
  frame?: Signal<string>;
};
type HostWindow = {
  qt?: { webChannelTransport: unknown };
  QWebChannel?: new (
    transport: unknown,
    ready: (channel: { objects: { orionMini: ChannelBridge } }) => void,
  ) => unknown;
};

let connection: Promise<Client> | undefined;

// Keep unchanged subtrees when one part of a native snapshot changes, so a
// connection heartbeat or usage counter need not rerender every saved photo.
function shareSnapshot(previous: unknown, next: unknown, depth = 0): unknown {
  if (previous === next) return previous;
  if (depth > 32 || !previous || !next || typeof previous !== "object" || typeof next !== "object") return next;
  if (Array.isArray(previous) && Array.isArray(next)) {
    if (previous.length !== next.length) return next;
    let same = true;
    for (let i = 0; i < next.length; i++) {
      next[i] = shareSnapshot(previous[i], next[i], depth + 1);
      if (next[i] !== previous[i]) same = false;
    }
    return same ? previous : next;
  }
  if (Array.isArray(previous) || Array.isArray(next)) return next;
  const a = previous as Record<string, unknown>, b = next as Record<string, unknown>;
  const keys = Object.keys(b);
  let same = keys.length === Object.keys(a).length;
  for (const key of keys) {
    b[key] = shareSnapshot(a[key], b[key], depth + 1);
    if (!Object.hasOwn(a, key) || b[key] !== a[key]) same = false;
  }
  return same ? previous : next;
}
export function desktopClient(): Promise<Client> {
  if (connection) return connection;
  connection = new Promise<Client>((resolve, reject) => {
    const host = window as unknown as HostWindow;
    if (!host.qt?.webChannelTransport || !host.QWebChannel) {
      reject(
        new Error(
          "The desktop connection is unavailable. Open Saiph from its desktop shortcut.",
        ),
      );
      return;
    }
    new host.QWebChannel(host.qt.webChannelTransport, (channel) => {
      const bridge = channel.objects.orionMini;
      const pending = new Map<
        string,
        {
          method: string;
          resolve: (value: unknown) => void;
          reject: (error: Error) => void;
          timer: number;
        }
      >();
      // The page asks for the whole state every second and it is usually the same
      // megabytes as last time. An identical answer resolves to the same object
      // without parsing, so the page can tell nothing changed by reference.
      let lastState: { body: string; value: unknown; revision?: string } | undefined;
      bridge.response.connect((raw) => {
        const head = /^\{"id": ?"([^"]+)", ?/.exec(raw);
        const early = head ? pending.get(head[1]) : undefined;
        const body = head && early?.method === "state" ? raw.slice(head[0].length) : "";
        if (body && body === lastState?.body) {
          clearTimeout(early!.timer);
          pending.delete(head![1]);
          early!.resolve(lastState.value);
          return;
        }
        const response = JSON.parse(raw);
        const item = pending.get(response.id);
        if (!item) return;
        clearTimeout(item.timer);
        pending.delete(response.id);
        if (response.ok && item.method === "state" && response.unchanged) {
          if (lastState?.revision && response.revision === lastState.revision) item.resolve(lastState.value);
          else item.reject(new Error("The dashboard needs a fresh snapshot. Reopen Saiph."));
          return;
        }
        if (response.ok && body) {
          response.result = shareSnapshot(lastState?.value, response.result);
          lastState = { body, value: response.result,
            revision: typeof response.revision === "string" && /^[a-f0-9]{64}$/.test(response.revision) ? response.revision : undefined };
        }
        if (response.ok) item.resolve(response.result);
        else item.reject(new Error(response.error || "The operation failed."));
      });
      resolve({
        call<T>(method: string, args: Record<string, unknown> = {}) {
          return new Promise<T>((resolve, reject) => {
            const id = crypto.randomUUID();
            const timer = window.setTimeout(() => {
              pending.delete(id);
              reject(
                new Error(
                  "The desktop did not respond. Check the job list or reopen Saiph.",
                ),
              );
            }, method === "app.update.download" || method === "app.update.now" ? 30 * 60 * 1000 : method === "cloud.client.install" ? 11 * 60 * 1000 : method === "components.install" ? 10 * 60 * 1000 : 150000);
            pending.set(id, {
              method,
              resolve: (value) => resolve(value as T),
              reject,
              timer,
            });
            bridge.request(id, method, JSON.stringify(method === "state" && lastState?.revision
              ? { ...args, revision: lastState.revision } : args));
          });
        },
        subscribe(fn) {
          const signal = bridge.refresh || bridge.changed;
          signal.connect(fn);
          return () => signal.disconnect?.(fn);
        },
        onDrop(fn) {
          const handler = (raw: string) => fn(JSON.parse(raw) as DroppedFiles);
          bridge.dropped.connect(handler);
          return () => bridge.dropped.disconnect?.(handler);
        },
        onDragging(fn) {
          bridge.dragging.connect(fn);
          return () => bridge.dragging.disconnect?.(fn);
        },
        ...(bridge.frame ? {
          onFrame(fn: (frame: FrameInfo) => void) {
            const frame = bridge.frame!;
            const handler = (raw: string) => {
              try { fn(JSON.parse(raw) as FrameInfo); } catch { /* Not a frame announcement. */ }
            };
            frame.connect(handler);
            return () => frame.disconnect?.(handler);
          },
        } : {}),
      });
    });
  });
  return connection;
}
