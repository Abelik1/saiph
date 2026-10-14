// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, DroppedFiles } from "./types";

type Signal<T> = {
  connect(fn: (value: T) => void): void;
  disconnect?(fn: (value: T) => void): void;
};
type ChannelBridge = {
  request(id: string, method: string, args: string): void;
  response: Signal<string>;
  changed: Signal<void>;
  dropped: Signal<string>;
  dragging: Signal<boolean>;
};
type HostWindow = {
  qt?: { webChannelTransport: unknown };
  QWebChannel?: new (
    transport: unknown,
    ready: (channel: { objects: { orionMini: ChannelBridge } }) => void,
  ) => unknown;
};

let connection: Promise<Client> | undefined;
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
      let lastState: { body: string; value: unknown } | undefined;
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
        if (response.ok && body) lastState = { body, value: response.result };
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
            }, method === "app.update.install" ? 30 * 60 * 1000 : method === "cloud.client.install" ? 11 * 60 * 1000 : method === "components.install" ? 10 * 60 * 1000 : 150000);
            pending.set(id, {
              method,
              resolve: (value) => resolve(value as T),
              reject,
              timer,
            });
            bridge.request(id, method, JSON.stringify(args));
          });
        },
        subscribe(fn) {
          bridge.changed.connect(fn);
          return () => bridge.changed.disconnect?.(fn);
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
      });
    });
  });
  return connection;
}
