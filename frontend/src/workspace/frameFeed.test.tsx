// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { followFrames, frameUrl, validFrame } from "./frameFeed";
import { PhoneCamera } from "./PhoneCamera";
import type { CameraStatus, Client, FrameInfo, State } from "./types";

/** A shell that pushes frames, with image decoding the test resolves by hand. */
function pushingClient(call = vi.fn()) {
  let listener: ((frame: FrameInfo) => void) | null = null;
  const client = {
    call, subscribe: () => () => undefined,
    onFrame(fn: (frame: FrameInfo) => void) { listener = fn; return () => { listener = null; }; },
  } as unknown as Client;
  return { client, push: (frame: FrameInfo) => listener?.(frame), listening: () => listener !== null };
}

/** jsdom has no image decoding; each decode waits until the test finishes it. */
function controlledDecode() {
  const loads: { src: string; finish: () => void }[] = [];
  Object.defineProperty(HTMLImageElement.prototype, "decode", { configurable: true, writable: true,
    value(this: HTMLImageElement) { return new Promise<void>((resolve) => loads.push({ src: this.src, finish: resolve })); } });
  return { loads, restore: () => { delete (HTMLImageElement.prototype as { decode?: unknown }).decode; } };
}

afterEach(() => vi.restoreAllMocks());

describe("Live frame feed", () => {
  it("accepts only well-formed announcements for its own source", () => {
    expect(validFrame({ source: "camera", sequence: 4, rotation: 90 }, "camera")).toMatchObject({ sequence: 4 });
    expect(validFrame({ source: "screen", sequence: 4 }, "camera")).toBeNull();
    expect(validFrame({ source: "camera", sequence: -1 }, "camera")).toBeNull();
    expect(validFrame({ source: "camera", sequence: 1.5 }, "camera")).toBeNull();
    expect(validFrame({ source: "camera", sequence: 2, rotation: 45 }, "camera")).toBeNull();
    expect(frameUrl("screen", 12)).toBe("saiph-frame://screen/12");
  });

  it("is unavailable in shells without pushed frames", () => {
    expect(followFrames({ call: vi.fn(), subscribe: () => () => undefined } as unknown as Client, "camera", vi.fn())).toBeNull();
  });

  it("decodes one frame at a time and skips straight to the newest", async () => {
    const { client, push, listening } = pushingClient();
    const decode = controlledDecode();
    const shown: number[] = [];
    const stop = followFrames(client, "camera", (info) => shown.push(info.sequence))!;
    push({ source: "camera", sequence: 1 });
    push({ source: "camera", sequence: 2 });
    push({ source: "camera", sequence: 3 });
    expect(decode.loads.map((load) => load.src)).toEqual(["saiph-frame://camera/1"]);
    await act(async () => { decode.loads[0].finish(); });
    expect(shown).toEqual([1]);
    expect(decode.loads.map((load) => load.src)).toEqual(["saiph-frame://camera/1", "saiph-frame://camera/3"]);
    await act(async () => { decode.loads[1].finish(); });
    expect(shown).toEqual([1, 3]);
    stop();
    expect(listening()).toBe(false);
    decode.restore();
  });

  it("draws pushed camera frames without polling the bridge", async () => {
    const call = vi.fn();
    const { client, push } = pushingClient(call);
    const decode = controlledDecode();
    const camera: CameraStatus = { available: false, running: true, verified: false, mode: "unavailable", device_id: null, message: "",
      integrated_available: true, local_state: "live", local_resolution: "1080p", local_fps: 20, local_quality: "high" };
    render(<PhoneCamera camera={camera} client={client} />);
    expect(await screen.findByRole("img", { name: "Live phone camera preview" })).toBeInstanceOf(HTMLCanvasElement);
    push({ source: "camera", sequence: 5, fps: 19.6, rotation: 90, source_width: 1920, source_height: 1080 });
    expect(call).not.toHaveBeenCalledWith("camera.frame");
    decode.restore();
  });
});

describe("Dashboard refresh", () => {
  it("fetches once more for a change announced while a snapshot was in flight", async () => {
    const snapshot = { usage: { available: false, consent: null, pending: [], last_sent: null },
      hub_inbox: { items: [], synced_at: null, error: "" }, setup: { completed: true, connected: true, show: false, mode: "hub", platform: "windows", tools: {}, linux: {} },
      settings: { hub: { paired: true, base_url: "", device_id: "desktop" }, machine: { name: "Desk", features: {} }, link: {} },
      hosted: { available: true, enabled: false, status: "off", identity: false, configured: true },
      phone: { status: "", error: "", notifications: [], devices: [] } } as unknown as State;
    let changed = () => {};
    const answers: ((value: State) => void)[] = [];
    const call = vi.fn((method: string) => method === "state" ? new Promise<State>((resolve) => answers.push(resolve)) : Promise.resolve({}));
    render(<App providedClient={{ call, subscribe: (fn: () => void) => { changed = fn; return () => undefined; } } as unknown as Client} />);
    await waitFor(() => expect(answers).toHaveLength(1));
    // Three announcements while the first snapshot is still being built.
    changed(); changed(); changed();
    await act(async () => { answers[0](snapshot); });
    await waitFor(() => expect(answers).toHaveLength(2));
    await act(async () => { answers[1](snapshot); });
    expect(call.mock.calls.filter(([method]) => method === "state")).toHaveLength(2);
  });
});
