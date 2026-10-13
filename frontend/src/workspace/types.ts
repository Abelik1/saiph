// SPDX-License-Identifier: AGPL-3.0-or-later
import type { PhoneFeatureState } from "./PhoneTabs";
export type AIConfig = {
  provider: string;
  model: string;
  credential_source: string;
  ollama_url?: string;
};
export type CameraConfig = {enabled?:boolean;facing?:"front"|"back";quality?:"720p"|"1080p";rotation?:"0"|"90"|"180"|"270";v4l2_sink?:string;obs_profile?:string;obs_collection?:string;obs_scene?:string;obs_scene_file?:string;obs_executable?:string;scrcpy_executable?:string};
export type CameraStatus = {available:boolean;running:boolean;verified:boolean;mode:"linux-v4l2"|"windows-obs"|"unavailable";device_id:string|null;message:string;facing?:"front"|"back";quality?:"720p"|"1080p";rotation?:string};
export type MicrophoneConfig = {enabled?:boolean;scrcpy_executable?:string};
export type MicrophoneStatus = {available:boolean;running:boolean;muted:boolean;verified:boolean;mode:"linux-pulse"|"windows-cable"|"unavailable";device_id:string|null;message:string};
export type DeskflowConfig = {enabled?:boolean;role?:"desktop"|"laptop";desktop?:string;local?:string;certificate?:string;executable?:string};
export type DeskflowStatus = {error:string;running?:boolean;crashes?:number;exit_code?:number|null;uptime?:number;setup?:{executable:string;certificates:string[];trust_file:string;trusted:boolean;mesh_addresses:string[]}};
export type Settings = {
  cloud?: {path?:string;enabled?:boolean;recordings?:boolean};
  link?: {focus?:boolean;dnd_sync?:boolean;auto_copy_codes?:boolean;battery_alerts?:boolean;pause_media_on_calls?:boolean;new_photo_notices?:boolean;ring_computer?:boolean;clipboard?:boolean;timezone?:string;wake_hour?:number;wake_minute?:number;camera?:CameraConfig;microphone?:MicrophoneConfig;deskflow?:DeskflowConfig;hotspot?:{profile?:string;auto?:boolean};remote?:{enabled?:boolean;devices?:string[];adapters?:Record<string,boolean>}};
  projects: string[];
  selected_project: string;
  start_with_windows: boolean;
  close_to_tray: boolean;
  ai: AIConfig;
  email: { gmail_client?: string; gmail_token?: string };
  hub: { base_url: string; device_id: string; paired: boolean };
  sleep_plan: {
    hour: number;
    minute: number;
    attention: string;
    warn_minutes?: number;
    insist?: boolean;
    every_minutes?: number;
    settle_minutes?: number;
  };
  transcription: { model: string; device: string };
  default_attention: string;
  watched_folders: string[];
  watched_media: Recording[];
  machine: Machine;
};
export type Features = {
  sleep_plan: boolean;
  activity_breaks: boolean;
  calendar: boolean;
};
export type CalendarEvent = {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string;
  calendar: string;
  color: string;
  url: string;
};
/** One occurrence on the Calendar page. All-day items use dates, with an exclusive end. */
export type AgendaItem = {
  id: string;
  event: string;
  source: string;
  source_name: string;
  kind: "deadline" | "exam" | "class" | "event" | "task" | "google";
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  detail: string;
  location: string;
  group: string;
  tentative: boolean;
  repeats?: boolean;
  color: string;
  url: string;
};
export type Agenda = {
  items: AgendaItem[];
  sources: {
    id: string;
    name: string;
    count: number;
    reported_at: string | null;
  }[];
  window: [string, string];
};
/** A proposed calendar event, created by the calendar scout once accepted. */
export type ProposedEvent = {
  title: string;
  start: string;
  end: string | null;
  all_day: boolean;
  reminders: number[];
  location: string;
  description: string;
};
/** One item in Saiph Hub's inbox, shared by the phone and both computers. */
export type HubItem = {
  id: string;
  kind: "notice" | "proposal";
  source: string;
  title: string;
  body: string;
  link: string;
  proposal: { events?: ProposedEvent[]; calendar?: string; action?: {type:string}; review?: {phone:string;type:string;operation:string;recipients?:string[];text?:string;app?:string;title?:string} } | null;
  status: "new" | "accepted" | "dismissed" | "applied" | "done";
  decided_by: string | null;
  decided_at: string | null;
  result: string;
  created_at: string;
};
export type GoogleStatus = {
  client: boolean;
  client_source: string;
  signed_in: boolean;
  email: string;
  gmail: boolean;
  calendar: boolean;
};
export type Machine = { name: string; features: Features };
export type PluginStatus = {
  state: "ok" | "warning" | "error" | "running" | "login_required" | "idle";
  summary: string;
  detail: string;
  metrics: Record<string, string | number | boolean>;
  next_run: string | null;
  reported_at: string;
  overdue: boolean;
  links: PluginLink[];
};
export type PluginLink = {
  label: string;
  file: string;
  report: string | null;
  exists: boolean;
};
export type PluginReview = {
  id: string;
  title: string;
  detail: string;
  flags: string[];
  severity: "info" | "warning" | "error";
  actions: { action: string; value: string | null; label: string }[];
};
export type PluginAction = {
  id: string;
  label: string;
  description: string;
  hint: string;
  console: boolean;
  command: string;
  value: { choices?: string[]; pattern?: string; label?: string; names?: Record<string, string> } | null;
};
export type PluginRun = {
  id: string;
  action: string;
  value?: string | null;
  label: string;
  status: "running" | "succeeded" | "failed" | "opened" | "unknown";
  started_at: string;
  finished_at?: string;
  exit_code?: number;
  note?: string;
  console: boolean;
};
export type TickerItem = {
  id: string;
  plugin: string;
  source: string;
  text: string;
  severity: "info" | "warning" | "error";
};
export type Plugin = {
  id: string;
  name: string;
  description: string;
  path: string;
  error: string;
  approved: boolean;
  previously_approved?: boolean;
  fingerprint: string;
  actions: PluginAction[];
  logs: { id: string; name: string; path: string }[];
  reports: { id: string; name: string; glob: string; description: string }[];
  status: PluginStatus | null;
  reviews: PluginReview[];
  events: { at: string; level: string; message: string }[];
  ticker: TickerItem[];
  runs: PluginRun[];
};
export type ApiInfo = {
  running: boolean;
  url: string;
  error: string;
  discovery: string;
};
export type Recording = { name: string; path: string; size: number };
export type Project = { name: string; path: string; available: boolean };
export type Task = {
  id: string;
  title: string;
  done?: boolean;
  due?: string;
  notes?: string;
  project?: string;
};
export type Reminder = {
  id: string;
  title: string;
  kind: string;
  due_at: string | null;
  status: string;
  recurrence: string | null;
  attention: string;
  payload: Record<string, number | boolean | string>;
};
export type TrackCounter = { completed: number; total: number };
export type Job = {
  id: string;
  kind: string;
  status: string;
  progress: string;
  error?: string;
  payload: Record<string, unknown>;
  result?: Record<string, unknown>;
  tracks?: Record<string, TrackCounter>;
  track_count?: number;
  updated_at: string;
};
export type Message = {
  id: string;
  text: string;
  role: string;
  project: string;
};
export type Email = {
  id: string;
  subject: string;
  sender: string;
  snippet: string;
  text?: string;
  summary?: string;
  unread: boolean;
  date: string;
  url: string;
};
export type Segment = {
  id: string;
  track: number;
  start: number | null;
  end: number | null;
  raw_text: string;
  text: string;
};
export type Transcript = {
  segments: Segment[];
  text: string;
  notes: string;
  summary: null | {
    content: string;
    stale: boolean;
    model: string;
    provider: string;
  };
  annotations: { id: string; body: string; segment_ids: string[] }[];
  track_labels: Record<string, string>;
};
export type HostedConfig = {service_url: string; issuer: string; audience: string; client_id: string; refresh_tokens: boolean};
export type HostedState = {available: boolean; enabled: boolean; status: string; identity: boolean; configured?: boolean; config?: HostedConfig; self_hosted_paired?: boolean; error?: string; account?: {status: string; error: string; refresh_tokens: boolean}; fingerprint?: string | null; roster?: {expires_at: number; version: number; clock_warning: boolean; members: {id: string; label: string; root: boolean; fingerprint: string}[]} | null; offers?: {id: string; name: string; size: number}[]; notifications?: {id: string; app: string; title: string; text: string}[]; user_verification?: UserVerification; security_events?: {id: string; kind: "added" | "removed"; device_id: string; label: string; at: number}[]};
/** Whether the operating system confirms the person before a device is added. */
export type UserVerification = "windows_hello" | "unavailable" | "checking";
export type SetupStatus = {completed:boolean;connected:boolean;show:boolean;mode:"hub"|"hosted"|null;platform:string;
  tools:Record<string,{found:boolean;purpose:string;link:string}>;linux:Record<string,{found:boolean;package:string;purpose:string}>};
export type BluetoothLockStatus = {supported:boolean;enabled:boolean;device:string;seconds:number;devices:{address:string;name:string}[];error:string;windows:boolean};
export type RemoteStatus = {enabled:boolean;devices:string[];adapters:Record<string,{name:string;enabled:boolean;available:boolean}>;wayland:boolean;last:{device_id:string;app:string;control:string;at:number}|null};
export type HotspotStatus = {profiles:string[];profile:string;auto:boolean;active:string|null;error:string;supported:boolean};
export type DndStatus = {enabled:boolean;active:boolean;source:string;changed_at:number|null;quiet:boolean};
export type State = {
  hosted?: HostedState;
  user_verification?: UserVerification;
  platform?: string;
  update_status?: {state: string; code: string};
  cloud_status?: {installed: boolean; profile_present: boolean; inspection_complete: boolean; prepared: boolean; selected_libraries: number; state: string; installation_supported?: boolean; management_available?: boolean; service_state?: 'not_managed' | 'reachable' | 'unavailable' | 'needs_attention'};
  modules?: { workspace: { installed: boolean; enabled: boolean } };
  enrollment?: {ready:boolean;id:string|null;expires_at:string|null;custom_mesh:boolean;approved?:boolean};
  components?: {mesh_installed:boolean;mesh_running:boolean;busy:boolean;message:string};
  deskflow?: DeskflowStatus;
  dnd?: DndStatus;
  hotspot?: HotspotStatus;
  remote?: RemoteStatus;
  bt_lock?: BluetoothLockStatus;
  setup?: SetupStatus;
  camera?: CameraStatus;
  microphone?: MicrophoneStatus;
  handoffs?: import("./Handoff").HandoffItem[];
  backup_status?: {configured:boolean;targets:Record<string,{ok?:boolean;completed_at?:number;error?:string}>;error?:string};
  phone_features?: PhoneFeatureState;
  phone?: {
    status: string;
    error: string;
    devices: { id: string; name: string; online: boolean; last_seen_at: string | null; capabilities: string[]; battery?: { battery_level: number; is_charging: boolean; updated_at: number } | null }[];
    notifications: PhoneNotification[];
  };
  settings: Settings;
  projects: Project[];
  transcripts: { id: string; title: string; has_summary: boolean }[];
  tasks: Task[];
  reminders: Reminder[];
  jobs: Job[];
  messages: Message[];
  emails: Email[];
  providers: Record<string, boolean>;
  skills: { id: string; name: string; content: string }[];
  plugins: Plugin[];
  ticker: TickerItem[];
  api: ApiInfo;
  google: GoogleStatus;
  calendar: {
    events: CalendarEvent[];
    synced_at: string | null;
    error: string;
  };
  agenda: Agenda;
  hub_inbox: { items: HubItem[]; synced_at: string | null; error: string };
};
export type CloudInfo = {configured:boolean;state:string;libraries:{id:string;name:string;permission:string}[]};
export type CloudPreparation = {state?:"prepared"|"link_requested"|"existing_binding";needs_library_link?:boolean;cancelled?:boolean};
export type DroppedFiles = {
  paths: string[];
  rejected: { name: string; reason: string }[];
};
export type Client = {
  call<T = unknown>(method: string, args?: Record<string, unknown>): Promise<T>;
  subscribe(fn: () => void): () => void;
  // Only the desktop shell can see a dropped file's real path.
  onDrop?(fn: (files: DroppedFiles) => void): () => void;
  onDragging?(fn: (active: boolean) => void): () => void;
};
export type Page =
  | "Phone"
  | "Cloud"
  | "Today"
  | "Assistant"
  | "Library"
  | "Calendar"
  | "Tasks"
  | "Reminders"
  | "Inbox"
  | "Plugins"
  | "Settings";

export type PhoneNotification = {
  id: string; device_id: string; key: string; app: string; package: string;
  title: string; text: string; timestamp: number; actions: {index: number; label: string}[];
  reply_key?: string | null; silent?: boolean; code?: string | null;
};
