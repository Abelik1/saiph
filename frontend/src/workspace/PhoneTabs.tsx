// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import { Image, LoaderCircle, MessageSquare, PhoneCall, Send, Smartphone } from "lucide-react";
import type { Client } from "./types";
import { Action, Empty, Form } from "./ui";
import "./PhoneTabs.css";

export type SmsMessage = { id: string; message_id?: number; device_id: string; thread: number; body: string; timestamp: number; direction: "incoming" | "outgoing" };
export type SmsThread = { id: string; device_id: string; thread: number; recipients: string[]; message: { body: string; timestamp: number } };
export type PhonePhoto = { id: string; photo_id: string; device_id: string; name: string; timestamp: number; preview?: string };
export type PhotoSave = { id?: string; device_id?: string; photo_id?: string; status: "saving" | "saved" | "failed"; name?: string | null; path?: string | null; folder?: string | null; file_id?: string | null; error?: string | null; updated_at?: string; existing?: boolean };
export type MediaSession = { source: string; app: string; title: string; artist: string; playing: boolean; can_play: boolean; can_pause: boolean; can_next: boolean; can_previous: boolean; can_seek: boolean; position_ms: number; length_ms: number; volume: number };
export type CallLogEntry = { number: string; name: string; timestamp: number; duration: number; type: "incoming" | "outgoing" | "missed" | "rejected" | "other" };
export type PhoneFeatureState = { threads: SmsThread[]; messages: SmsMessage[]; calls: { device_id: string; state: "ringing" | "active" | "missed" | "ended"; number: string; name: string }[]; photos: PhonePhoto[]; files: { id: string; device_id: string; name: string; path: string; size: number }[]; photo_saves?: PhotoSave[];
  media?: { device_id: string; sessions: MediaSession[] }[]; ringers?: { device_id: string; mode: "ring" | "vibrate" | "silent" }[];
  contacts?: { device_id: string; query: string; contacts: { name: string; numbers: string[] }[] }[]; call_logs?: { device_id: string; calls: CallLogEntry[] }[];
  attachments?: { device_id: string; thread: number; message: number; parts: { part: number; mime: string; name: string }[] }[];
  attachment_files?: { id: string; device_id: string; thread: number; message: number; part: number; name: string; mime: string; size: number; preview?: string; ready: boolean }[] };
type PhoneDevice = { id: string; name: string; online: boolean; capabilities: string[] };
const noFeatures: PhoneFeatureState = { threads: [], messages: [], calls: [], photos: [], files: [] };

/** A new conversation: contact suggestions come from the phone on request and are not stored. */
/** MMS parts: fetched from the phone only when the owner asks, then shown or saved. */
function Attachments({ info, phone, message, client }: { info: PhoneFeatureState; phone: PhoneDevice; message: SmsMessage; client: Client }) {
  const parts = info.attachments?.find((row) => row.device_id === phone.id && row.thread === message.thread && row.message === message.message_id)?.parts || [];
  return <>{parts.map((part) => {
    const file = info.attachment_files?.find((row) => row.device_id === phone.id && row.thread === message.thread && row.message === message.message_id && row.part === part.part && row.ready);
    if (file?.preview) return <figure key={part.part} className="phone-attachment"><img src={file.preview} alt={part.name || "Picture"} />
      <Action className="text-button" run={() => client.call("phone.sms.attachment.save", { id: file.id })}>Save<span className="sr-only"> {part.name}</span></Action></figure>;
    if (file) return <div key={part.part} className="actions"><span>{part.name}</span><Action className="text-button" run={() => client.call("phone.sms.attachment.open", { id: file.id })}>Open</Action>
      <Action className="text-button" run={() => client.call("phone.sms.attachment.save", { id: file.id })}>Save</Action></div>;
    return <Action key={part.part} className="text-button" disabled={!phone.online} ariaLabel={"Show " + (part.name || part.mime)}
      run={() => client.call("phone.sms.attachment", { device_id: phone.id, thread: message.thread, message: message.message_id, part: part.part })}>{part.mime.startsWith("image/") ? "Show picture" : "Get " + (part.name || "attachment")}</Action>;
  })}</>;
}
function NewMessage({ info, phone, client, close }: { info: PhoneFeatureState; phone: PhoneDevice; client: Client; close: () => void }) {
  const [address, setAddress] = useState("");
  const [text, setText] = useState("");
  const [queued, setQueued] = useState(false);
  const canSearch = phone.online && phone.capabilities.includes("contacts");
  useEffect(() => {
    const query = address.trim();
    if (!canSearch || query.length < 2 || /^[+\d\s()-]+$/.test(query)) return;
    const timer = window.setTimeout(() => void client.call("phone.contacts.search", { device_id: phone.id, query }).catch(() => {}), 300);
    return () => window.clearTimeout(timer);
  }, [address, canSearch, client, phone.id]);
  const results = info.contacts?.find((row) => row.device_id === phone.id && row.query === address.trim())?.contacts || [];
  return <Form submit={async () => { await client.call("phone.sms.compose", { device_id: phone.id, address, text }); setText(""); setQueued(true); }}>
    <label>To<input aria-label="New message recipient" value={address} maxLength={120} placeholder={canSearch ? "Name or number" : "Phone number"} onChange={(e) => { setAddress(e.target.value); setQueued(false); }} /></label>
    {results.length > 0 && <ul className="contact-suggestions" aria-label="Contact suggestions">{results.flatMap((contact) => contact.numbers.map((number) =>
      <li key={contact.name + number}><button type="button" className="text-button" onClick={() => setAddress(number)}>{contact.name} · {number}</button></li>))}</ul>}
    <label>Message<input aria-label="New message text" value={text} maxLength={4096} onChange={(e) => { setText(e.target.value); setQueued(false); }} /></label>
    <div className="actions"><button disabled={!phone.online || !address.trim() || !text.trim()}><Send size={15} />Send</button><button type="button" className="text-button" onClick={close}>Close</button></div>
    {queued && <small role="status">Message queued for your phone. The conversation appears here once it is sent.</small>}
  </Form>;
}
function Messages({ info, phone, client }: { info: PhoneFeatureState; phone?: PhoneDevice; client: Client }) {
  const [composing, setComposing] = useState(false);
  const [selected, setSelected] = useState(0);
  const [reply, setReply] = useState("");
  const [queued, setQueued] = useState(false);
  const threads = info.threads.filter((r) => r.device_id === phone?.id).sort((a, b) => b.message.timestamp - a.message.timestamp);
  const thread = threads.find((r) => r.thread === selected) || threads[0];
  const available = Boolean(phone?.online && phone.capabilities.includes("sms"));
  useEffect(() => {
    if (available && thread) void client.call("phone.sms.open", { device_id: thread.device_id, thread: thread.thread }).catch(() => {});
  }, [available, client, thread?.device_id, thread?.thread]);
  if (!phone?.capabilities.includes("sms")) return <Empty title="Messages permission">Allow SMS in Saiph on your phone to see conversations and reply here.</Empty>;
  const compose = composing || !thread
    ? <NewMessage info={info} phone={phone} client={client} close={() => setComposing(false)} />
    : <button type="button" className="text-button" disabled={!available} onClick={() => setComposing(true)}>New message</button>;
  if (!thread) return <>{compose}<Empty title="Your messages appear here">Saiph loads conversations automatically from your phone.</Empty></>;
  const messages = info.messages.filter((r) => r.device_id === phone.id && r.thread === thread.thread).sort((a, b) => a.timestamp - b.timestamp);
  return <>{compose}<div className="phone-messages">
    <aside aria-label="Conversations">{threads.map((r) => <button key={r.id} className={r.thread === thread.thread ? "selected" : ""} onClick={() => { setSelected(r.thread); setReply(""); setQueued(false); }}><strong>{r.recipients.join(", ") || "Conversation"}</strong><span>{r.message.body}</span></button>)}</aside>
    <section className="phone-conversation"><h2>{thread.recipients.join(", ") || "Conversation"}</h2><div className="phone-message-list">{messages.map((r) => <article key={r.id} className={"phone-message " + r.direction}>{r.body && <p>{r.body}</p>}<Attachments info={info} phone={phone} message={r} client={client} /><small>{new Date(r.timestamp).toLocaleString()}</small></article>)}</div>
      <Form submit={async () => { await client.call("phone.sms.send", { device_id: phone.id, thread: thread.thread, text: reply }); setReply(""); setQueued(true); }}><label>Message<input aria-label="SMS reply" value={reply} maxLength={4096} disabled={!available || thread.recipients.length!==1} onChange={(e) => { setReply(e.target.value); setQueued(false); }} /></label><button disabled={!available || thread.recipients.length!==1 || !reply.trim()}><Send size={15} />Send</button>{queued && <small role="status">Reply queued for your phone.</small>}{thread.recipients.length!==1 && <small>Group replies stay in your phone's messaging app.</small>}</Form>
    </section>
  </div></>;
}
function SavePhoto({ photo, phone, client, recorded }: { photo: PhonePhoto; phone: PhoneDevice; client: Client; recorded?: PhotoSave }) {
  // The call result shows at once; a newer recorded state (e.g. the download finishing) then takes over.
  const [pending, setPending] = useState(false);
  const [local, setLocal] = useState<{ result: PhotoSave; seen?: string }>();
  const recordedAt = useRef(recorded?.updated_at);
  useEffect(() => { recordedAt.current = recorded?.updated_at; }, [recorded?.updated_at]);
  const shown = pending ? { status: "saving" as const } : local && local.seen === recorded?.updated_at ? local.result : recorded;
  const save = async () => {
    setPending(true);
    try { const result = await client.call<PhotoSave>("phone.photo.save", { device_id: phone.id, photo_id: photo.photo_id }); setLocal({ result: result?.status ? result : { status: "saving" }, seen: recordedAt.current }); }
    catch (error) { setLocal({ result: { status: "failed", error: String(error instanceof Error ? error.message : error) }, seen: recordedAt.current }); }
    finally { setPending(false); }
  };
  if (shown?.status === "saved") return <div className="phone-photo-save"><small role="status" title={shown.path || undefined}>{shown.existing ? "Already saved to " : "Saved to "}{shown.folder || "Downloads → Orion"}</small>{shown.file_id && <Action className="text-button" run={() => client.call("phone.file.open", { id: shown.file_id })}>Show in folder</Action>}</div>;
  const saving = shown?.status === "saving";
  return <div className="phone-photo-save"><button type="button" className="text-button" disabled={!phone.online || saving} onClick={() => void save()}>{saving && <LoaderCircle size={15} className="spin" />}{saving ? "Saving…" : "Save photo"}</button>
    {saving && <small role="status">Saving the original from your phone…</small>}{shown?.status === "failed" && <small className="inline-error" role="alert">{shown.error || "The photo could not be saved. Try again."}</small>}</div>;
}
function Photos({ info, phone, client }: { info: PhoneFeatureState; phone?: PhoneDevice; client: Client }) {
  const [dragStatus, setDragStatus] = useState("");
  if (!phone?.capabilities.includes("photos")) return <Empty title="Photos permission">Allow photos in Saiph on your phone. Your recent photos then appear automatically.</Empty>;
  const rows = info.photos.filter((p) => p.device_id === phone.id).sort((a, b) => b.timestamp - a.timestamp);
  return rows.length ? <><p className="muted">Recent photos from your phone. Save or drag a photo to use it on this computer.</p>{dragStatus && <p role="status">{dragStatus}</p>}<div className="phone-photo-grid">{rows.map((photo) => <article key={photo.id}>
    <div className="phone-photo-image" tabIndex={0} draggable={phone.online} onPointerEnter={() => { if(phone.online)void client.call("phone.photo.prefetch", { device_id: phone.id, photo_id: photo.photo_id }).catch(() => {}); }} onFocus={() => { if(phone.online)void client.call("phone.photo.prefetch", { device_id: phone.id, photo_id: photo.photo_id }).catch(() => {}); }} onDragStart={(e) => { e.preventDefault(); setDragStatus("Preparing the original photo… Keep holding to drag it."); void client.call<{dragged?:boolean;ready?:boolean}>("phone.photo.drag", { device_id: phone.id, photo_id: photo.photo_id }).then((result) => setDragStatus(result.dragged ? "" : result.ready ? "Photo ready. Drag it to another app." : "The original is downloading. Drag it again when it is ready.")).catch((error) => setDragStatus(String(error))); }}>
      {photo.preview ? <img src={photo.preview} alt={photo.name} loading="lazy" /> : <Image size={30} aria-label="Photo preview loading" />}
    </div><small>{photo.name}</small><SavePhoto photo={photo} phone={phone} client={client} recorded={info.photo_saves?.find((s) => s.device_id === phone.id && s.photo_id === String(photo.photo_id))} />
  </article>)}</div></> : <Empty title="Your recent photos appear here">Saiph is reading the photos your phone allows it to share.</Empty>;
}
const callTypes = { incoming: "Incoming", outgoing: "Outgoing", missed: "Missed", rejected: "Declined", other: "Call" };
function Calls({ info, phone, client }: { info: PhoneFeatureState; phone?: PhoneDevice; client: Client }) {
  const [number, setNumber] = useState("");
  const history = phone?.online && phone.capabilities.includes("call-log");
  useEffect(() => { if (history) void client.call("phone.calls.log", { device_id: phone!.id }).catch(() => {}); }, [history, client, phone?.id]);
  if (!phone?.capabilities.includes("calls")) return <Empty title="Calls permission">Allow phone access in Saiph on your phone to see incoming calls here.</Empty>;
  const call = info.calls.find((r) => r.device_id === phone.id);
  const control = phone.online && phone.capabilities.includes("call-control");
  const dial = phone.online && phone.capabilities.includes("call-dial");
  const recent = info.call_logs?.find((row) => row.device_id === phone.id)?.calls || [];
  return <><section className="phone-call"><PhoneCall size={42} strokeWidth={1} /><h2>{call?.state === "ringing" ? "Incoming call" : call?.state === "active" ? "Call in progress" : "Calls"}</h2><p>{call?.name || call?.number || "Incoming calls appear automatically."}</p><p className="muted">Call audio stays on your phone.</p>{call?.state === "ringing" && <div className="phone-call-actions"><Action disabled={!control} run={() => client.call("phone.call", { device_id: phone.id, operation: "answer" })}>Answer</Action><Action disabled={!control} run={() => client.call("phone.call", { device_id: phone.id, operation: "reject" })}>Decline</Action></div>}{call?.state === "ringing" && !control && <small>Answer on your phone, or allow call control in Saiph settings.</small>}</section>
    {phone.capabilities.includes("call-dial") && <Form submit={async () => { await client.call("phone.dial", { device_id: phone.id, number }); setNumber(""); }}>
      <label>Number<input aria-label="Number to call" value={number} inputMode="tel" maxLength={40} onChange={(e) => setNumber(e.target.value)} /></label>
      <button disabled={!dial || !number.trim()}><PhoneCall size={15} />Call on phone</button>
    </Form>}
    {recent.length > 0 && <section aria-label="Recent calls" className="phone-recent-calls">{recent.map((row) => <article key={row.timestamp + row.number}>
      <div className="grow"><b>{row.name || row.number}</b><small>{callTypes[row.type]} · {new Date(row.timestamp).toLocaleString()}</small></div>
      {phone.capabilities.includes("call-dial") && <Action className="text-button" ariaLabel={"Call back " + (row.name || row.number)} disabled={!dial} run={() => client.call("phone.dial", { device_id: phone.id, number: row.number })}>Call back</Action>}
    </article>)}</section>}
  </>;
}
function Files({ info, phone, client }: { info: PhoneFeatureState; phone?: PhoneDevice; client: Client }) {
  const available = Boolean(phone?.online && phone.capabilities.includes("files"));
  const rows = info.files.filter((r) => r.device_id === phone?.id);
  return <><div className="section-head"><div><h2>Shared files</h2><p className="muted">Files arrive in Downloads → Orion on either device.</p></div><Action disabled={!available} run={() => client.call("phone.file.choose", { device_id: phone?.id })}><Send size={15} />Send a file</Action></div>{rows.length ? <div className="phone-file-list">{rows.map((r) => <article key={r.id}><strong>{r.name}</strong><small>{(r.size / 1024).toFixed(1)} KB</small><Action className="text-button" run={() => client.call("phone.file.open", { id: r.id })}>Show in folder</Action></article>)}</div> : <Empty title="Send something across">Choose a file here, or use Share → Saiph on your phone.</Empty>}</>;
}
export function PhoneTabs({ features = noFeatures, phone, client }: { features?: PhoneFeatureState; phone?: PhoneDevice; client: Client }) {
  const [tab, setTab] = useState("Messages");
  return <><nav className="phone-tabs" aria-label="Phone features">{[{ name: "Messages", icon: MessageSquare }, { name: "Photos", icon: Image }, { name: "Calls", icon: PhoneCall }, { name: "Files", icon: Send }].map(({ name, icon: Icon }) => <button key={name} aria-current={tab === name ? "page" : undefined} onClick={() => setTab(name)}><Icon size={17} />{name}</button>)}</nav><div className="phone-tab-content">{!phone ? <Empty title="Your phone, on this computer"><Smartphone size={40} />Use your server invitation to get started.</Empty> : tab === "Messages" ? <Messages info={features} phone={phone} client={client} /> : tab === "Photos" ? <Photos info={features} phone={phone} client={client} /> : tab === "Calls" ? <Calls info={features} phone={phone} client={client} /> : <Files info={features} phone={phone} client={client} />}</div></>;
}
