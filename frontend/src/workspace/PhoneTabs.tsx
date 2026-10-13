// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { AppWindow, Image, MessageSquare, PhoneCall, Send, Smartphone } from "lucide-react";
import type { Client } from "./types";
import { Action, Empty, Form } from "./ui";
import "./PhoneTabs.css";
import { Photos } from "./PhotoGallery";
import { RetainedView } from "./Navigation";

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
function Messages({
  info,
  phone,
  client,
  active,
}: {
  info: PhoneFeatureState;
  phone?: PhoneDevice;
  client: Client;
  active: boolean;
}) {
  const [composing, setComposing] = useState(false);
  const [selected, setSelected] = useState<Record<string, number>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [queuedFor, setQueuedFor] = useState("");
  const [loadResult, setLoadResult] = useState<{
    key: string;
    error: string;
  }>();
  const [attempt, setAttempt] = useState(0);
  const threads = info.threads
    .filter((r) => r.device_id === phone?.id)
    .sort((a, b) => b.message.timestamp - a.message.timestamp);
  const thread =
    threads.find((r) => r.thread === selected[phone?.id || ""]) || threads[0];
  const available = Boolean(
    phone?.online && phone.capabilities.includes("sms"),
  );
  const draftKey = `${phone?.id}:${thread?.thread}`;
  const reply = drafts[draftKey] || "";
  const setReply = (text: string) =>
    setDrafts((current) => ({ ...current, [draftKey]: text }));
  const threadDevice = thread?.device_id,
    threadNumber = thread?.thread;
  const requestKey = JSON.stringify([threadDevice, threadNumber, attempt]);
  const loading = loadResult?.key !== requestKey;
  const loadError = loadResult?.key === requestKey ? loadResult.error : "";
  useEffect(() => {
    if (!active || !available || !threadDevice || threadNumber === undefined)
      return;
    let current = true;
    client
      .call("phone.sms.open", {
        device_id: threadDevice,
        thread: threadNumber,
      })
      .then(() => {
        if (current) setLoadResult({ key: requestKey, error: "" });
      })
      .catch(() => {
        if (current)
          setLoadResult({
            key: requestKey,
            error:
              "Messages could not be loaded. Check your phone connection and try again.",
          });
      });
    return () => {
      current = false;
    };
  }, [active, available, client, threadDevice, threadNumber, requestKey]);
  if (!phone?.capabilities.includes("sms"))
    return (
      <Empty title="Messages permission">
        Allow SMS in Saiph on your phone to see conversations and reply here.
      </Empty>
    );
  const compose = composing || !thread
    ? <NewMessage info={info} phone={phone} client={client} close={() => setComposing(false)} />
    : <button type="button" className="text-button" disabled={!available} onClick={() => setComposing(true)}>New message</button>;
  if (!thread)
    return (
      <>{compose}<Empty
        title={
          phone.online ? "Your messages appear here" : "No saved conversations"
        }
      >
        {phone.online
          ? "Saiph loads conversations automatically from your phone."
          : "Reconnect your phone to load your conversations."}
      </Empty></>
    );
  const messages = info.messages
    .filter((r) => r.device_id === phone.id && r.thread === thread.thread)
    .sort((a, b) => a.timestamp - b.timestamp);
  const replyable = thread.recipients.length === 1 || (thread.recipients.length <= 10 && phone.capabilities.includes("sms-group"));
  return (
    <>{compose}<div className="phone-messages">
      <aside aria-label="Conversations">
        {threads.map((r) => (
          <button
            key={r.id}
            className={r.thread === thread.thread ? "selected" : ""}
            onClick={() => {
              setSelected((current) => ({ ...current, [phone.id]: r.thread }));
            }}
          >
            <strong>{r.recipients.join(", ") || "Conversation"}</strong>
            <span>{r.message.body}</span>
          </button>
        ))}
      </aside>
      <section className="phone-conversation">
        {!phone.online && (
          <p className="muted" role="status">
            Showing saved messages. Reconnect your phone to load new messages or
            send a reply.
          </p>
        )}
        {active && available && loading && (
          <p role="status">Loading messages…</p>
        )}
        {active && available && loadError && (
          <div>
            <p className="inline-error" role="alert">
              {loadError}
            </p>
            <button
              type="button"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Retry messages
            </button>
          </div>
        )}
        <h2>{thread.recipients.join(", ") || "Conversation"}</h2>
        <div className="phone-message-list">
          {messages.map((r) => (
            <article key={r.id} className={"phone-message " + r.direction}>
              {r.body && <p>{r.body}</p>}
              <Attachments info={info} phone={phone} message={r} client={client} />
              <small>{new Date(r.timestamp).toLocaleString()}</small>
            </article>
          ))}
        </div>
        <Form
          submit={async () => {
            await client.call("phone.sms.send", {
              device_id: phone.id,
              thread: thread.thread,
              text: reply,
            });
            setReply("");
            setQueuedFor(draftKey);
          }}
        >
          <label>
            Message
            <input
              aria-label="SMS reply"
              value={reply}
              maxLength={4096}
              disabled={!available || !replyable}
              onChange={(e) => {
                setReply(e.target.value);
                setQueuedFor("");
              }}
            />
          </label>
          <button
            disabled={
              !available || !replyable || !reply.trim()
            }
          >
            <Send size={15} />
            Send
          </button>
          {reply && (
            <small className="muted">
              Draft kept while you switch conversations.
            </small>
          )}
          {queuedFor === draftKey && (
            <small role="status">Reply queued for your phone.</small>
          )}
          {!replyable && (
            <small>Group replies stay in your phone's messaging app. Update Saiph on your phone to reply here.</small>
          )}
          {replyable && thread.recipients.length > 1 && <small>Group replies are sent as MMS.</small>}
        </Form>
      </section>
    </div></>
  );
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
function Files({
  info,
  phone,
  client,
}: {
  info: PhoneFeatureState;
  phone?: PhoneDevice;
  client: Client;
}) {
  const available = Boolean(
    phone?.online && phone.capabilities.includes("files"),
  );
  const rows = info.files.filter((r) => r.device_id === phone?.id);
  return (
    <>
      <div className="section-head">
        <div>
          <h2>Shared files</h2>
          <p className="muted">
            Files arrive in Downloads → Orion on either device.
          </p>
        </div>
        <Action
          disabled={!available}
          run={() => client.call("phone.file.choose", { device_id: phone?.id })}
        >
          <Send size={15} />
          Send a file
        </Action>
      </div>
      {!available && (
        <p className="muted">
          {!phone
            ? "Connect your phone to send a file."
            : !phone.online
              ? "Reconnect your phone to send files. Previously received files are still available."
              : "Allow file sharing in Saiph on your phone to send files."}
        </p>
      )}
      {rows.length ? (
        <div className="phone-file-list">
          {rows.map((r) => (
            <article key={r.id}>
              <strong>{r.name}</strong>
              <small>{(r.size / 1024).toFixed(1)} KB</small>
              <Action
                className="text-button"
                run={() => client.call("phone.file.open", { id: r.id })}
              >
                Show in folder
              </Action>
            </article>
          ))}
        </div>
      ) : (
        <Empty title="Send something across">
          Choose a file here, or use Share → Saiph on your phone.
        </Empty>
      )}
    </>
  );
}
type PhoneApp = { package: string; name: string; system: boolean };
/** Phone apps in their own windows, through scrcpy over the phone's authorised debugging connection. */
function Apps({ phone, client }: { phone: PhoneDevice; client: Client }) {
  const [apps, setApps] = useState<PhoneApp[] | null>(null);
  const [filter, setFilter] = useState("");
  const [notice, setNotice] = useState("");
  const shown = (apps || []).filter((app) => !filter.trim() || app.name.toLowerCase().includes(filter.trim().toLowerCase()));
  return <>
    <div className="section-head"><div><h2>Phone apps</h2><p className="muted">Open a phone app in its own window here. Needs wireless or USB debugging, like the phone preview, and Android 10 or later.</p></div>
      <Action disabled={!phone.online} run={async () => { const result = await client.call<{ apps: PhoneApp[] }>("phone.apps", { device_id: phone.id }); setApps(result.apps); }}>{apps ? "Refresh apps" : "Show phone apps"}</Action></div>
    {notice && <p role="status">{notice}</p>}
    {apps && <><label>Find an app<input aria-label="Find a phone app" value={filter} onChange={(e) => setFilter(e.target.value)} /></label>
      <div className="phone-app-list">{shown.map((app) => <article key={app.package}><div className="grow"><b>{app.name}</b><small>{app.package}</small></div>
        <Action className="text-button" ariaLabel={"Open " + app.name} disabled={!phone.online} run={() => client.call("phone.app.open", { device_id: phone.id, package: app.package, name: app.name })}>Open</Action>
        <Action className="text-button" ariaLabel={"Pin " + app.name} run={async () => { await client.call("phone.app.pin", { package: app.package, name: app.name }); setNotice(app.name + " was added to your apps menu."); }}>Pin</Action>
      </article>)}</div></>}
  </>;
}
export function PhoneTabs({
  features = noFeatures,
  phone,
  client,
  active = true,
}: {
  features?: PhoneFeatureState;
  phone?: PhoneDevice;
  client: Client;
  active?: boolean;
}) {
  const [tab, setTab] = useState("Messages");
  return (
    <>
      <nav className="phone-tabs" aria-label="Phone features">
        {[
          { name: "Messages", icon: MessageSquare },
          { name: "Photos", icon: Image },
          { name: "Calls", icon: PhoneCall },
          { name: "Files", icon: Send },
          { name: "Apps", icon: AppWindow },
        ].map(({ name, icon: Icon }) => (
          <button
            key={name}
            aria-current={tab === name ? "page" : undefined}
            onClick={() => setTab(name)}
          >
            <Icon size={17} />
            {name}
          </button>
        ))}
      </nav>
      <div className="phone-tab-content">
        {!phone ? (
          <Empty title="Your phone, on this computer">
            <Smartphone size={40} />
            Use your server invitation to get started.
          </Empty>
        ) : (
          <>
            <RetainedView active={tab === "Messages"}>
              <Messages
                info={features}
                phone={phone}
                client={client}
                active={active && tab === "Messages"}
              />
            </RetainedView>
            <RetainedView active={tab === "Photos"}>
              <Photos
                info={features}
                phone={phone}
                client={client}
                active={active && tab === "Photos"}
              />
            </RetainedView>
            <RetainedView active={tab === "Calls"}>
              <Calls info={features} phone={phone} client={client} />
            </RetainedView>
            <RetainedView active={tab === "Files"}>
              <Files info={features} phone={phone} client={client} />
            </RetainedView>
            <RetainedView active={tab === "Apps"}>
              <Apps phone={phone} client={client} />
            </RetainedView>
          </>
        )}
      </div>
    </>
  );
}
