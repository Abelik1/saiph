// SPDX-License-Identifier: AGPL-3.0-or-later
// Synthetic desktop state for the design preview. Every name, number and message
// here is made up; nothing comes from a real profile.
import type { AppUpdateState, Client, State } from "../workspace/types";

const now = Date.now();
const minutes = (n: number) => now - n * 60_000;

function swatch(seed: number) {
  // A small generated picture so the photo grid has something to show.
  const hue = (seed * 47) % 360;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl(${hue} 55% 38%)"/><stop offset="1" stop-color="hsl(${(hue + 60) % 360} 60% 72%)"/></linearGradient></defs><rect width="200" height="200" fill="url(#g)"/><circle cx="${60 + (seed % 5) * 20}" cy="70" r="26" fill="hsl(${(hue + 180) % 360} 70% 85%)"/></svg>`;
  return "data:image/svg+xml;base64," + btoa(svg);
}

const people = ["Ada Byrne", "Niamh Walsh", "Conor Doyle", "+353 87 555 0142", "Sam Okafor", "Lena Fischer"];

/** The footer's Update button: /preview.html?update=available (or checking, downloading, ready, installing, failed). */
function previewUpdate(): State["app_update"] {
  const state = new URLSearchParams(window.location.search).get("update") as AppUpdateState | null;
  if (!state || !["available", "checking", "downloading", "ready", "installing", "failed"].includes(state)) return undefined;
  const release = { schema: 1, platform: "windows-x86_64", profile: "link", build: 12, version: "0.1.0-beta.12", sha256: "0".repeat(64), bytes: 58_000_000 };
  return { state, release, version: release.version, bytes: release.bytes, notes: "Faster photo sync.", source: "cloud",
    error: state === "failed" ? "Desktop download is incomplete or damaged" : "", checked_at: Math.floor(now / 1000) };
}

export function fixtureState(): State {
  const threads = people.map((name, i) => ({ id: "t" + i, device_id: "phone", thread: i, recipients: [name], message: { body: ["See you at 7?", "Thanks, got it", "Can you send the slides", "Your code is 482913", "Running 5 min late", "Lovely photo!"][i], timestamp: minutes(i * 37 + 3) } }));
  const messages = Array.from({ length: 14 }, (_, i) => ({
    id: "m" + i, message_id: i, device_id: "phone", thread: 0,
    body: ["Hey! Are we still on for dinner?", "Yes, 7 works", "Great, I booked the place near the canal", "Perfect. Should I bring anything?", "Just yourself", "See you at 7?"][i % 6],
    timestamp: minutes(200 - i * 12), direction: (i % 2 ? "outgoing" : "incoming") as "incoming" | "outgoing",
  }));
  const photos = Array.from({ length: 18 }, (_, i) => ({ id: "p" + i, photo_id: String(i), device_id: "phone", name: `IMG_20261012_${1000 + i}.jpg`, timestamp: minutes(i * 90), preview: swatch(i) }));
  return {
    platform: "windows",
    app_version: "0.1.0-beta.11",
    app_update: previewUpdate(),
    modules: { workspace: { installed: false, enabled: false } },
    settings: {
      machine: { name: "Studio desktop", features: { sleep_plan: false, activity_breaks: false, calendar: false } },
      hub: { base_url: "http://127.0.0.1:1", device_id: "desktop", paired: true },
      link: { clipboard: true, camera: { enabled: true, facing: "front", quality: "720p", rotation: "0" }, microphone: { enabled: true } },
      start_with_windows: true, close_to_tray: true,
    } as unknown as State["settings"],
    enrollment: { ready: false, id: null, expires_at: null, custom_mesh: false },
    camera: { available: true, running: false, verified: true, mode: "windows-obs", device_id: null, message: "" },
    microphone: { available: true, running: false, muted: false, verified: false, mode: "windows-cable", device_id: null, message: "Ready when you start it." },
    dnd: { enabled: true, active: false, source: "", changed_at: null, quiet: false } as unknown as State["dnd"],
    insights: { enabled: true },
    usage: { available: false, consent: "declined" } as unknown as State["usage"],
    phone: {
      status: "Online", error: "",
      devices: [
        { id: "phone", name: "Pixel 8", online: true, last_seen_at: null, capabilities: ["battery", "notifications", "sms", "sms-group", "photos", "calls", "call-log", "call-dial", "call-control", "files", "ring", "ringer", "media", "contacts", "clipboard", "status", "dnd", "hotspot", "mobile_data"], battery: { battery_level: 76, is_charging: true, updated_at: 1 },
          status: { battery: 76, charging: true, wifi: true, cellular: false, metered: false, bluetooth: true, signal: 3, ringer: "vibrate", dnd: false,
            controls: ["status", "ring", "ringer", "dnd", "media", "hotspot", "mobile_data"], mobile_data: true, paused: false } },
        { id: "tablet", name: "Galaxy Tab", online: false, last_seen_at: new Date(minutes(300)).toISOString(), capabilities: ["battery", "photos"], battery: { battery_level: 41, is_charging: false, updated_at: 1 } },
      ],
      notifications: [
        { id: "n1", device_id: "phone", key: "k1", app: "Messages", package: "msg", title: "Ada Byrne", text: "See you at 7?", timestamp: minutes(3), actions: [{ index: 0, label: "Mark as read" }], reply_key: "r1" },
        { id: "n2", device_id: "phone", key: "k2", app: "Bank", package: "bank", title: "Sign-in code", text: "Your code is 482913. It expires in 10 minutes.", timestamp: minutes(9), actions: [], code: "482913" },
        { id: "n3", device_id: "phone", key: "k3", app: "Calendar", package: "cal", title: "Team sync in 15 minutes", text: "Room 2 · Video link in invite", timestamp: minutes(14), actions: [{ index: 1, label: "Snooze" }] },
        { id: "n4", device_id: "phone", key: "k4", app: "Messages", package: "msg", title: "Liam Walsh", text: "Running a bit late. The train is stuck outside the station and nobody knows how long it will be, so start without me and I'll catch up when I get there. Save me a seat near the back!", timestamp: minutes(26), actions: [], reply_key: "r4" },
      ],
    },
    phone_features: {
      threads, messages, photos, calls: [], files: [{ id: "f1", device_id: "phone", name: "Boarding pass.pdf", path: "", size: 184_320 }, { id: "f2", device_id: "phone", name: "Lease draft.docx", path: "", size: 52_480 }],
      media: [{ device_id: "phone", sessions: [{ source: "s", app: "Spotify", title: "Weightless", artist: "Marconi Union", playing: true, can_play: true, can_pause: true, can_next: true, can_previous: true, can_seek: false, position_ms: 0, length_ms: 0, volume: 50 }] }],
      ringers: [{ device_id: "phone", mode: "vibrate" }],
      call_logs: [{ device_id: "phone", calls: [{ number: "+353 1 555 0100", name: "Dentist", timestamp: minutes(80), duration: 120, type: "incoming" }, { number: "+353 87 555 0142", name: "", timestamp: minutes(260), duration: 0, type: "missed" }] }],
    },
    hub_inbox: {
      synced_at: new Date(minutes(2)).toISOString(), error: "",
      items: [{ id: "h1", kind: "proposal", source: "calendar-assistant", title: "Dentist appointment", body: "Found in a message from your dentist.", link: "", proposal: { events: [{ title: "Dentist", start: new Date(now + 3 * 86_400_000).toISOString(), end: null, all_day: false, reminders: [1440], location: "", description: "" }] }, status: "new", decided_by: null, decided_at: null, result: "", created_at: new Date(minutes(40)).toISOString() }],
    },
    handoffs: [],
    projects: [], transcripts: [], tasks: [], reminders: [], jobs: [], messages: [], emails: [], providers: {}, skills: [], plugins: [], ticker: [],
    api: {} as State["api"], google: { signed_in: false } as State["google"], calendar: { events: [], synced_at: null, error: "" }, agenda: { items: [], sources: [], window: ["", ""] },
  } as unknown as State;
}

/** A client that answers from the fixture and pretends each action took a moment. */
export function fixtureClient(): Client {
  const state = fixtureState();
  const listeners = new Set<() => void>();
  return {
    async call<T>(method: string): Promise<T> {
      if (method === "state") return state as T;
      await new Promise((resolve) => setTimeout(resolve, 600));
      if (method === "app.update.progress") return { state: "downloading", done: 29_000_000, total: 58_000_000 } as T;
      if (method === "insights.week") return { enabled: true, actions: 42, busiest_day: "Tuesday", screen: "messages", top: [{ feature: "sms", label: "Messages sent", count: 18 }], people: [] } as T;
      if (method === "phone.apps") return {
        apps: ["Calendar", "Camera", "Chat", "Clock", "Files", "Fitness", "Maps", "Music", "Notes", "Photos", "Podcasts", "Weather", "Wallet", "Video calls"]
          .map((name) => ({ package: "com.example." + name.toLowerCase().replace(/\s+/g, ""), name, system: false })),
        pinned: ["com.example.chat", "com.example.maps"], usage: { "com.example.music": 9, "com.example.notes": 4, "com.example.photos": 2 }, icons: false,
      } as T;
      return { ok: true } as T;
    },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
}
