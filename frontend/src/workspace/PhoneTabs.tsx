// SPDX-License-Identifier: AGPL-3.0-or-later
import { Fragment, memo, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AppWindow, ArrowDownLeft, ArrowUpRight, FileText, FolderOpen, Image, MessageSquare, PhoneCall, PhoneMissed, Plus, RefreshCw, Search, Send, Share2, Smartphone, X } from "lucide-react";
import type { CallAudioStatus, Client, HostedState, PhoneScreenStatus } from "./types";
import { CallAudioSession, CallAudioSetup, callAudioOn } from "./CallAudio";
import { Action, Empty, Form } from "./ui";
import { Photos } from "./PhotoGallery";
import { PhoneScreen } from "./PhoneScreen";
import { AppGrid, type PhoneApp } from "./PhoneAppGrid";
import { RetainedView } from "./Navigation";
import { Handoff, type HandoffItem } from "./Handoff";
import { CallBanner } from "./callBanner";
import { CloudTransfers, ReceivedFile, useNow } from "./CloudTransfers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export type SmsMessage = { id: string; message_id?: number; device_id: string; thread: number; body: string; timestamp: number; direction: "incoming" | "outgoing" };
export type SmsThread = { id: string; device_id: string; thread: number; recipients: string[]; message: { body: string; timestamp: number } };
export type PhonePhoto = { id: string; photo_id: string; device_id: string; name: string; timestamp: number; preview?: string };
export type PhotoSave = { id?: string; device_id?: string; photo_id?: string; status: "saving" | "saved" | "failed"; name?: string | null; path?: string | null; folder?: string | null; file_id?: string | null; error?: string | null; updated_at?: string; existing?: boolean };
export type MediaSession = { source: string; app: string; title: string; artist: string; playing: boolean; can_play: boolean; can_pause: boolean; can_next: boolean; can_previous: boolean; can_seek: boolean; position_ms: number; length_ms: number; volume: number };
export type CallLogEntry = { number: string; name: string; timestamp: number; duration: number; type: "incoming" | "outgoing" | "missed" | "rejected" | "other" };
export type PhoneFeatureState = { threads: SmsThread[]; messages: SmsMessage[]; calls: { device_id: string; state: "ringing" | "active" | "missed" | "ended"; number: string; name: string; handled?: "answer" | "reject" | null; handled_by?: string | null }[]; photos: PhonePhoto[]; files: { id: string; device_id: string; name: string; path: string; size: number }[]; photo_saves?: PhotoSave[];
  media?: { device_id: string; sessions: MediaSession[] }[]; ringers?: { device_id: string; mode: "ring" | "vibrate" | "silent" }[];
  contacts?: { device_id: string; query: string; contacts: { name: string; numbers: string[] }[] }[]; call_logs?: { device_id: string; calls: CallLogEntry[] }[];
  attachments?: { device_id: string; thread: number; message: number; parts: { part: number; mime: string; name: string }[] }[];
  attachment_files?: { id: string; device_id: string; thread: number; message: number; part: number; name: string; mime: string; size: number; preview?: string; ready: boolean }[] };
type PhoneDevice = { id: string; name: string; online: boolean; capabilities: string[]; screen?: string[]; hosted?: boolean; call_notice?: string | null };
/** Saiph Cloud phones also need the phone's own Texts and calls switch. */
const hostedPermission = (permission: string, result: string) =>
  `On your phone, tap Allow texts and calls in Saiph and allow ${permission} to ${result}.`;
const noFeatures: PhoneFeatureState = { threads: [], messages: [], calls: [], photos: [], files: [] };

/** A heading for a tab, with its main action on the right. */
function TabHead({ title, children, actions }: { title: string; children?: React.ReactNode; actions?: React.ReactNode }) {
  return <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
    <div className="grid min-w-0 gap-1"><h2 className="m-0 text-[17px] font-semibold tracking-[-0.02em]">{title}</h2>{children && <p className="m-0 max-w-[60ch] text-[13px] leading-relaxed text-muted-foreground">{children}</p>}</div>
    {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
  </div>;
}

/** MMS parts: fetched from the phone only when the owner asks, then shown or saved. */
function Attachments({ info, phone, message, client }: { info: PhoneFeatureState; phone: PhoneDevice; message: SmsMessage; client: Client }) {
  const parts = info.attachments?.find((row) => row.device_id === phone.id && row.thread === message.thread && row.message === message.message_id)?.parts || [];
  return <>{parts.map((part) => {
    const file = info.attachment_files?.find((row) => row.device_id === phone.id && row.thread === message.thread && row.message === message.message_id && row.part === part.part && row.ready);
    if (file?.preview) return <figure key={part.part} className="m-0 grid justify-items-start gap-1.5"><img className="max-h-60 max-w-60 rounded-[10px] object-contain" src={file.preview} alt={part.name || "Picture"} />
      <Action variant="tonal" size="sm" run={() => client.call("phone.sms.attachment.save", { id: file.id })}>Save<span className="sr-only"> {part.name}</span></Action></figure>;
    if (file) return <div key={part.part} className="flex flex-wrap items-center gap-2"><FileText className="size-4 text-muted-foreground" /><span className="text-[12.5px]">{part.name}</span><Action variant="tonal" size="sm" run={() => client.call("phone.sms.attachment.open", { id: file.id })}>Open</Action>
      <Action variant="tonal" size="sm" run={() => client.call("phone.sms.attachment.save", { id: file.id })}>Save</Action></div>;
    return <Action key={part.part} variant="tonal" size="sm" className="justify-self-start" disabled={!phone.online} ariaLabel={"Show " + (part.name || part.mime)}
      run={() => client.call("phone.sms.attachment", { device_id: phone.id, thread: message.thread, message: message.message_id, part: part.part })}>{part.mime.startsWith("image/") ? "Show picture" : "Get " + (part.name || "attachment")}</Action>;
  })}</>;
}

/** A message field that grows with its text. Enter sends; Shift+Enter starts a new line. */
function MessageField({ onSend, ...props }: React.ComponentProps<typeof Textarea> & { onSend: () => void }) {
  const field = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const node = field.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = node.scrollHeight + "px";
  }, [props.value]);
  return <Textarea ref={field} rows={1} {...props}
    className={cn("max-h-40 min-h-10 resize-none overflow-y-auto py-2.5 leading-normal", props.className)}
    onKeyDown={(event) => {
      props.onKeyDown?.(event);
      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); }
    }} />;
}

/** A new conversation: contact suggestions come from the phone on request and are not stored. */
function NewMessage({ info, phone, client, close }: { info: PhoneFeatureState; phone: PhoneDevice; client: Client; close?: () => void }) {
  const [address, setAddress] = useState("");
  const [text, setText] = useState("");
  const [queued, setQueued] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const toId = useId(), textId = useId();
  const canSearch = phone.online && phone.capabilities.includes("contacts");
  useEffect(() => {
    const query = address.trim();
    if (!canSearch || query.length < 2 || /^[+\d\s()-]+$/.test(query)) return;
    const timer = window.setTimeout(() => void client.call("phone.contacts.search", { device_id: phone.id, query }).catch(() => {}), 300);
    return () => window.clearTimeout(timer);
  }, [address, canSearch, client, phone.id]);
  const results = info.contacts?.find((row) => row.device_id === phone.id && row.query === address.trim())?.contacts || [];
  const ready = phone.online && address.trim() && text.trim();
  return <Form className="flex h-full flex-col gap-3" submit={async () => { await client.call("phone.sms.compose", { device_id: phone.id, address, text }); setText(""); setQueued(true); }}>
    <div ref={(node) => { form.current = node?.closest("form") || null; }} className="flex items-center justify-between border-b border-border pb-3">
      <h2 className="m-0 text-[15px] font-semibold">New message</h2>
      {close && <Button variant="ghost" size="icon-sm" aria-label="Close new message" title="Close (Esc)" onClick={close}><X /></Button>}
    </div>
    <Field label="To" htmlFor={toId}>
      <Input id={toId} autoFocus aria-label="New message recipient" value={address} maxLength={120} placeholder={canSearch ? "Name or number" : "Phone number"}
        onChange={(e) => { setAddress(e.target.value); setQueued(false); }} onKeyDown={(e) => { if (e.key === "Escape" && close) close(); }} />
    </Field>
    {results.length > 0 && <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Contact suggestions">{results.flatMap((contact) => contact.numbers.map((number) =>
      <li key={contact.name + number}><Button variant="tonal" size="sm" onClick={() => setAddress(number)}>{contact.name} · {number}</Button></li>))}</ul>}
    <div className="flex-1" />
    <Field label="Message" htmlFor={textId}>
      <div className="flex items-end gap-2">
        <MessageField id={textId} aria-label="New message text" value={text} maxLength={4096} onChange={(e) => { setText(e.target.value); setQueued(false); }}
          onKeyDown={(e) => { if (e.key === "Escape" && close) close(); }} onSend={() => { if (ready) form.current?.requestSubmit(); }} />
        <Button type="submit" variant="default" disabled={!ready}><Send />Send</Button>
      </div>
    </Field>
    {queued && <small role="status" className="text-[12px] text-status-on">Message queued for your phone. The conversation appears here once it is sent.</small>}
  </Form>;
}

function sameDay(a: number, b: number) {
  return new Date(a).toDateString() === new Date(b).toDateString();
}
function dayLabel(timestamp: number) {
  const day = new Date(timestamp), today = new Date();
  if (sameDay(timestamp, today.getTime())) return "Today";
  if (sameDay(timestamp, today.getTime() - 86_400_000)) return "Yesterday";
  return day.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: day.getFullYear() === today.getFullYear() ? undefined : "numeric" });
}
function timeLabel(timestamp: number) {
  return new Date(timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function Messages({
  info,
  phone,
  client,
  active,
  composing,
  setComposing,
}: {
  info: PhoneFeatureState;
  phone?: PhoneDevice;
  client: Client;
  active: boolean;
  composing: boolean;
  setComposing: (open: boolean) => void;
}) {
  const [selected, setSelected] = useState<Record<string, number>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [queuedFor, setQueuedFor] = useState("");
  const [loadResult, setLoadResult] = useState<{
    key: string;
    error: string;
  }>();
  const [attempt, setAttempt] = useState(0);
  const replyForm = useRef<HTMLFormElement>(null);
  const newButton = useRef<HTMLButtonElement>(null);
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
      <Empty title={phone?.online || phone?.hosted ? "Messages aren't shared" : "No saved messages"}>
        {phone?.online || phone?.hosted
          ? phone.hosted ? hostedPermission("SMS", "see conversations and reply here")
            : `${phone.name} isn't sharing text messages. If it can send texts, allow SMS in Saiph on it.`
          : `Reconnect ${phone?.name || "your phone"} to see its messages.`}
      </Empty>
    );
  const close = () => { setComposing(false); requestAnimationFrame(() => newButton.current?.focus()); };
  const query = search.trim().toLowerCase();
  const shown = query ? threads.filter((r) => r.recipients.join(" ").toLowerCase().includes(query) || r.message.body.toLowerCase().includes(query)) : threads;
  if (!thread && !composing)
    return (
      <div className="grid h-full grid-rows-[1fr_auto]">
        <NewMessage info={info} phone={phone} client={client} />
        <p className="m-0 pt-3 text-center text-[12.5px] text-muted-foreground">
          {phone.online ? "Your conversations appear here once Saiph has loaded them from your phone." : "Reconnect your phone to load your conversations."}
        </p>
      </div>
    );
  const messages = thread ? info.messages
    .filter((r) => r.device_id === phone.id && r.thread === thread.thread)
    .sort((a, b) => a.timestamp - b.timestamp) : [];
  const replyable = thread ? thread.recipients.length === 1 || (thread.recipients.length <= 10 && phone.capabilities.includes("sms-group")) : false;
  return (
    <div className="grid h-full min-h-[420px] grid-cols-[250px_minmax(0,1fr)] max-[1100px]:grid-cols-[200px_minmax(0,1fr)]">
      <aside aria-label="Conversations" className="flex min-h-0 flex-col gap-2 border-r border-border pr-3">
        <div className="flex items-center gap-1.5">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input aria-label="Search conversations" placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-8" />
          </div>
          <Button ref={newButton} variant="tonal" size="icon-sm" className="size-9" aria-label="New message" title="New message (Ctrl+N)" disabled={!available} onClick={() => setComposing(true)}><Plus /></Button>
        </div>
        <div className="grid min-h-0 flex-1 content-start gap-0.5 overflow-y-auto">
          {shown.map((r) => (
            <button
              key={r.id}
              type="button"
              data-slot="conversation"
              aria-current={!composing && r.thread === thread?.thread ? "true" : undefined}
              className={cn("grid w-full min-w-0 cursor-pointer gap-0.5 rounded-[10px] border-0 bg-transparent px-3 py-2.5 text-left transition-colors hover:bg-muted/70",
                !composing && r.thread === thread?.thread && "bg-secondary shadow-[inset_2px_0_0_var(--primary)] hover:bg-secondary")}
              onClick={() => {
                setComposing(false);
                setSelected((current) => ({ ...current, [phone.id]: r.thread }));
              }}
            >
              <span className="flex min-w-0 items-baseline gap-2">
                <strong className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">{r.recipients.join(", ") || "Conversation"}</strong>
                <small className="shrink-0 text-[12px] text-muted-foreground tabular">{sameDay(r.message.timestamp, Date.now()) ? timeLabel(r.message.timestamp) : new Date(r.message.timestamp).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</small>
              </span>
              <span className="truncate text-[12.5px] text-muted-foreground">{r.message.body}</span>
            </button>
          ))}
          {!shown.length && <p className="m-0 px-3 py-4 text-[12.5px] text-muted-foreground">No conversation matches “{search.trim()}”.</p>}
        </div>
      </aside>
      <section className="flex min-h-0 min-w-0 flex-col pl-5" aria-label={composing ? "New message" : "Conversation"}>
        {composing || !thread ? <NewMessage info={info} phone={phone} client={client} close={close} /> : <>
        <h2 className="m-0 border-b border-border pb-3 text-[15px] font-semibold">{thread.recipients.join(", ") || "Conversation"}</h2>
        {!phone.online && (
          <p className="m-0 mt-3 text-[12.5px] text-muted-foreground" role="status">
            Showing saved messages. Reconnect your phone to load new messages or
            send a reply.
          </p>
        )}
        {active && available && loading && (
          <p className="m-0 mt-3 text-[12.5px] text-muted-foreground" role="status">Loading messages…</p>
        )}
        {active && available && loadError && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <p className="inline-error m-0" role="alert">
              {loadError}
            </p>
            <Button size="sm" onClick={() => setAttempt((value) => value + 1)}>
              Retry messages
            </Button>
          </div>
        )}
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto py-4">
          {messages.map((r, index) => (
            <Fragment key={r.id}>
              {(index === 0 || !sameDay(messages[index - 1].timestamp, r.timestamp)) &&
                <p className="m-0 my-1 self-center rounded-full bg-muted/70 px-3 py-0.5 text-[12px] text-muted-foreground">{dayLabel(r.timestamp)}</p>}
              <article className={cn("grid max-w-[78%] gap-1.5 rounded-[16px] px-3.5 py-2.5",
                r.direction === "outgoing" ? "self-end rounded-br-[6px] bg-secondary text-foreground" : "self-start rounded-bl-[6px] bg-muted/80")}>
                {r.body && <p className="m-0 whitespace-pre-wrap text-[13px] leading-relaxed [overflow-wrap:anywhere]">{r.body}</p>}
                <Attachments info={info} phone={phone} message={r} client={client} />
                <time dateTime={new Date(r.timestamp).toISOString()} title={new Date(r.timestamp).toLocaleString()} className={cn("text-[12px] text-muted-foreground tabular", r.direction === "outgoing" && "text-right")}>{timeLabel(r.timestamp)}</time>
              </article>
            </Fragment>
          ))}
        </div>
        <Form
          className="grid gap-1.5 border-t border-border pt-3"
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
          <div ref={(node) => { replyForm.current = node?.closest("form") || null; }} className="flex items-end gap-2">
            <MessageField
              aria-label="SMS reply"
              placeholder={replyable ? "Message" : "Reply on your phone"}
              value={reply}
              maxLength={4096}
              disabled={!available || !replyable}
              onChange={(e) => {
                setReply(e.target.value);
                setQueuedFor("");
              }}
              onSend={() => { if (available && replyable && reply.trim()) replyForm.current?.requestSubmit(); }}
            />
            <Button type="submit" variant="default" disabled={!available || !replyable || !reply.trim()}>
              <Send />
              Send
            </Button>
          </div>
          {reply && (
            <small className="text-[12px] text-muted-foreground">
              Draft kept while you switch conversations. Shift+Enter for a new line.
            </small>
          )}
          {queuedFor === draftKey && (
            <small role="status" className="text-[12px] text-status-on">Reply queued for your phone.</small>
          )}
          {!replyable && (
            <small className="text-[12px] text-muted-foreground">Group replies stay in your phone's messaging app. Update Saiph on your phone to reply here.</small>
          )}
          {replyable && thread.recipients.length > 1 && <small className="text-[12px] text-muted-foreground">Group replies are sent as MMS.</small>}
        </Form>
        </>}
      </section>
    </div>
  );
}
const callTypes = { incoming: "Incoming", outgoing: "Outgoing", missed: "Missed", rejected: "Declined", other: "Call" };
const callIcons = { incoming: ArrowDownLeft, outgoing: ArrowUpRight, missed: PhoneMissed, rejected: PhoneMissed, other: PhoneCall };
function Calls({ info, phone, client, callAudio }: { info: PhoneFeatureState; phone?: PhoneDevice; client: Client; callAudio?: CallAudioStatus }) {
  const [number, setNumber] = useState("");
  const banner = useContext(CallBanner);
  const history = phone?.online && phone.capabilities.includes("call-log");
  useEffect(() => { if (history) void client.call("phone.calls.log", { device_id: phone!.id }).catch(() => {}); }, [history, client, phone?.id]);
  if (!phone?.capabilities.includes("calls")) return <Empty title="Calls aren't shared">{phone?.hosted ? hostedPermission("phone access", "see incoming calls here") : "Allow phone access in Saiph on your phone to see incoming calls here."}</Empty>;
  const call = info.calls.find((r) => r.device_id === phone.id && (r.state === "ringing" || r.state === "active"));
  const control = phone.online && phone.capabilities.includes("call-control");
  const dial = phone.online && phone.capabilities.includes("call-dial");
  const recent = info.call_logs?.find((row) => row.device_id === phone.id)?.calls || [];
  const handled = info.calls.find((r) => r.device_id === phone.id && r.state !== "ringing" && r.handled_by);
  const here = callAudioOn(callAudio);
  return <>
    <TabHead title="Calls" actions={phone.capabilities.includes("call-dial") && <Form className="flex items-center gap-2" submit={async () => { await client.call("phone.dial", { device_id: phone.id, number }); setNumber(""); }}>
      <Input aria-label="Number to call" placeholder="Number" value={number} inputMode="tel" maxLength={40} onChange={(e) => setNumber(e.target.value)} className="h-9 w-48" />
      <Button type="submit" variant="default" size="sm" className="h-9" disabled={!dial || !number.trim()}><PhoneCall />Call on phone</Button>
    </Form>}>{here ? "Calls you answer here use this computer's microphone and speakers, over Bluetooth." : "Call audio stays on your phone."}</TabHead>
    {handled && <p className="m-0 mb-2 text-[13px] text-muted-foreground">{handled.handled === "reject" ? "Declined" : "Answered"} on {handled.handled_by}</p>}
    {phone.call_notice && <p role="status" className="m-0 mb-4 text-[13px] text-muted-foreground">{phone.call_notice}</p>}
    {call && <section className="string-edge mb-5 flex flex-wrap items-center gap-4 rounded-[14px] border border-secondary-border bg-field/50 px-5 py-4" aria-label="Current call">
      <span className="flex size-11 items-center justify-center rounded-full bg-secondary text-secondary-foreground"><PhoneCall className="size-5" strokeWidth={1.5} /></span>
      <div className="grid min-w-0 flex-1">
        <b className="text-[15px] font-semibold">{call.state === "ringing" ? "Incoming call" : "Call in progress"}</b>
        <span className="text-[13px] text-muted-foreground">{call.name || call.number}</span>
      </div>
      {call.state === "ringing" && !banner && <div className="flex gap-2"><Action variant="default" disabled={!control} run={() => client.call("phone.call", { device_id: phone.id, operation: "answer" })}>{here ? "Answer here" : "Answer"}</Action>
        {here && <Action variant="secondary" disabled={!control} run={() => client.call("phone.call", { device_id: phone.id, operation: "answer", audio: "phone" })}>Answer on phone</Action>}
        <Action variant="destructive" disabled={!control} run={() => client.call("phone.call", { device_id: phone.id, operation: "reject" })}>Decline</Action></div>}
      {call.state === "ringing" && !control && <small className="basis-full text-[12px] text-muted-foreground">Answer on your phone, or allow call control in Saiph settings.</small>}
      <CallAudioSession status={callAudio} live={call.state === "active"} client={client} />
    </section>}
    {recent.length > 0 ? <section aria-label="Recent calls" className="grid gap-1.5">
      <h3 className="m-0 mb-1 text-[13px] font-semibold text-muted-foreground">Recent calls</h3>
      {recent.map((row) => { const Icon = callIcons[row.type]; return <Item key={row.timestamp + row.number} variant="outline" size="sm">
        <ItemMedia className={cn("size-8", row.type === "missed" || row.type === "rejected" ? "bg-status-off-surface text-status-off" : "")}><Icon /></ItemMedia>
        <ItemContent><ItemTitle>{row.name || row.number}</ItemTitle><ItemDescription>{callTypes[row.type]} · {new Date(row.timestamp).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</ItemDescription></ItemContent>
        {phone.capabilities.includes("call-dial") && <ItemActions><Action variant="tonal" size="sm" ariaLabel={"Call back " + (row.name || row.number)} disabled={!dial} run={() => client.call("phone.dial", { device_id: phone.id, number: row.number })}>Call back</Action></ItemActions>}
      </Item>; })}
    </section> : !call && <Empty title="No recent calls">{phone.online ? "Incoming calls appear here, and on every page of Saiph while they ring." : "Reconnect your phone to see recent calls."}</Empty>}
    <CallAudioSetup status={callAudio} client={client} />
  </>;
}
type Handoffs = { handoffs: HandoffItem[]; devices: { id: string; name: string; online?: boolean; capabilities?: string[] }[]; currentDeviceId?: string };
type CloudFiles = { cloudOffers?: HostedState["offers"]; cloudTransfers?: HostedState["transfers"] };
/** Everything that moves between devices: files to and from the phone, and links and text to any device. */
function Share({
  info,
  phone,
  client,
  handoffs,
  devices,
  currentDeviceId,
  cloudOffers,
  cloudTransfers,
}: {
  info: PhoneFeatureState;
  phone?: PhoneDevice;
  client: Client;
} & Handoffs & CloudFiles) {
  const available = Boolean(
    phone?.online && phone.capabilities.includes("files"),
  );
  const rows = info.files.filter((r) => r.device_id === phone?.id);
  const offers = phone?.hosted ? (cloudOffers || []).filter((offer) => offer.source === phone.id) : [];
  const now = useNow(offers.length > 0);
  return (
    <>
      <TabHead title="Share" actions={<Action variant="default" size="sm" disabled={!available} run={() => client.call("phone.file.choose", { device_id: phone?.id })}><Send />Send a file to {phone?.name || "your phone"}</Action>}>
        Files you receive are saved in your Downloads folder.
      </TabHead>
      {!available && (
        <p className="m-0 mb-4 text-[12.5px] text-muted-foreground">
          {!phone
            ? "Connect your phone to send a file."
            : !phone.online
              ? "Reconnect your phone to send files. Previously received files are still available."
              : "Allow file sharing in Saiph on your phone to send files."}
        </p>
      )}
      {phone?.hosted && <CloudTransfers transfers={cloudTransfers} target={phone.id} client={client} />}
      <h3 className="m-0 mb-2 text-[13px] font-semibold text-muted-foreground">Received from {phone?.name || "your phone"}</h3>
      {offers.length > 0 && <div className="mb-3 grid gap-1.5">
        {offers.map((offer) => <ReceivedFile key={offer.id} offer={offer} client={client} now={now} cloudReady={available} />)}
      </div>}
      {rows.length ? (
        <div className="mb-6 grid gap-1.5">
          {rows.map((r) => (
            <Item key={r.id} variant="outline" size="sm">
              <ItemMedia className="size-8"><FileText /></ItemMedia>
              <ItemContent><ItemTitle>{r.name}</ItemTitle><ItemDescription className="tabular">{(r.size / 1024).toFixed(1)} KB</ItemDescription></ItemContent>
              <ItemActions>
                <Action variant="tonal" size="sm" run={() => client.call("phone.file.open", { id: r.id })}><FolderOpen />Show in folder</Action>
              </ItemActions>
            </Item>
          ))}
        </div>
      ) : offers.length === 0 && (
        <p className="m-0 mb-6 text-[12.5px] text-muted-foreground">Nothing yet. On your phone, use Share → Saiph.</p>
      )}
      <h3 className="m-0 mb-3 text-[13px] font-semibold text-muted-foreground">Links and text</h3>
      <Handoff items={handoffs} devices={devices} currentDeviceId={currentDeviceId} phoneId={phone?.id} client={client} />
    </>
  );
}
type AppList = { apps?: PhoneApp[]; pending?: boolean; unavailable?: boolean; message?: string; refreshing?: boolean;
  pinned?: string[]; usage?: Record<string, number>; icons?: boolean };
/**
 * The phone's screen and apps over the local network (docs/PHONE_SCREEN.md): no cable, adb or scrcpy.
 * Apps are a grid of icons with Pinned and Most used rows (PhoneAppGrid.tsx).
 * scrcpy windows over authorised USB/wireless debugging remain under Advanced.
 */
function Apps({ phone, client, active, screen, usbDebugging = false }: { phone: PhoneDevice; client: Client; active: boolean; screen?: PhoneScreenStatus; usbDebugging?: boolean }) {
  const [apps, setApps] = useState<PhoneApp[] | null>(null);
  const [pinned, setPinned] = useState<string[]>([]);
  const [usage, setUsage] = useState<Record<string, number>>({});
  const [icons, setIcons] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [unavailable, setUnavailable] = useState("");
  const [legacy, setLegacy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const attempt = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const accept = useCallback((result: AppList) => {
    if (Array.isArray(result.pinned)) setPinned(result.pinned.filter((name) => typeof name === "string"));
    if (result.usage && typeof result.usage === "object") setUsage(result.usage);
    setIcons(result.icons === true);
  }, []);
  const load = useCallback(async () => {
    setError(""); attempt.current = 0; window.clearTimeout(timer.current);
    if (legacy) {
      try { setApps((await client.call<{ apps: PhoneApp[] }>("phone.apps.legacy", { device_id: phone.id })).apps); setUnavailable(""); setIcons(false); }
      catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
      return;
    }
    // The phone answers over Saiph Cloud (or the live screen session) a moment later; ask again briefly.
    const ask = async () => {
      try {
        const result = await client.call<AppList>("phone.apps", { device_id: phone.id });
        accept(result);
        if (result.apps) { setApps(result.apps); setWaiting(false); setUnavailable(""); return; }
        if (result.unavailable) { setWaiting(false); setUnavailable(result.message || ""); return; }
        setWaiting(true);
        if (++attempt.current < 15) timer.current = window.setTimeout(() => void ask(), 2000);
        else { setWaiting(false); setError("Your phone did not send its apps. Open Saiph on your phone and try again."); }
      } catch (reason) { setWaiting(false); setError(reason instanceof Error ? reason.message : String(reason)); }
    };
    await ask();
  }, [client, phone.id, legacy, accept]);
  // The list loads the first time the tab is opened, then on request.
  const [asked, setAsked] = useState(false);
  if (active && phone.online && !asked) setAsked(true);
  useEffect(() => { if (asked) void load(); }, [asked, load]);
  // A live session can list apps even for phones that cannot over Cloud.
  const live = screen?.state === "live";
  useEffect(() => { if (live && unavailable && !legacy) void load(); }, [live, unavailable, legacy, load]);
  const report = (reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason));
  const open = async (app: PhoneApp) => {
    setNotice(""); setError("");
    setUsage((current) => ({ ...current, [app.package]: (current[app.package] || 0) + 1 }));
    if (legacy) { await client.call("phone.app.open.legacy", { device_id: phone.id, package: app.package, name: app.name }); return; }
    const result = await client.call<{ live: boolean }>("phone.app.open", { device_id: phone.id, package: app.package, name: app.name });
    setNotice(result.live ? `Opening ${app.name} on your phone.` : `Opening ${app.name} once you start sharing on your phone.`);
  };
  const pin = async (app: PhoneApp, value: boolean) => {
    const result = await client.call<{ pinned: string[] }>("phone.app.favorite", { device_id: phone.id, package: app.package, pinned: value });
    if (Array.isArray(result.pinned)) setPinned(result.pinned);
  };
  const shortcut = async (app: PhoneApp) => {
    await client.call("phone.app.pin", { package: app.package, name: app.name });
    setNotice(app.name + " was added to your apps menu.");
  };
  return <>
    <TabHead title="Phone apps" actions={<Action variant="ghost" size="icon-sm" ariaLabel="Refresh apps" title="Refresh apps" disabled={!phone.online && !live} run={load}><RefreshCw /></Action>}>
      Use your phone's screen and open its apps on this computer. Both devices need the same Wi-Fi; no cable or debugging setup.
    </TabHead>
    {!legacy && <div className="mb-5"><PhoneScreen screen={screen} deviceId={phone.id} client={client} /></div>}
    {notice && <p role="status" className="m-0 mb-4 text-[12.5px] text-status-on">{notice}</p>}
    {error && <p role="alert" className="inline-error m-0 mb-4 text-[12.5px]">{error}</p>}
    {!phone.online && !apps && !live && <Empty title="Phone offline">Reconnect your phone to see its apps.</Empty>}
    {(phone.online || live) && !apps && !error && (unavailable
      ? <p className="m-0 text-[12.5px] text-muted-foreground" role="status">{unavailable}</p>
      : <p className="m-0 text-[12.5px] text-muted-foreground" role="status">{waiting ? "Asking your phone for its apps…" : "Loading apps…"}</p>)}
    {apps && <AppGrid apps={apps} deviceId={phone.id} client={client} icons={icons && !legacy} pinned={pinned} usage={usage} disabled={!phone.online && !live}
      onOpen={(app) => void open(app).catch(report)} onPin={(app, value) => void pin(app, value).catch(report)} onShortcut={(app) => void shortcut(app).catch(report)} />}
    {/* Only after the explicit opt-in in Settings → Advanced: nothing here asks to install scrcpy or adb. */}
    {(usbDebugging || legacy) && <details className="mt-6 text-[12.5px] text-muted-foreground" open={legacy}>
      <summary className="cursor-pointer select-none">USB debugging: separate app windows</summary>
      <p className="m-0 mt-2 max-w-[60ch] leading-relaxed">You turned on USB debugging in Settings → Advanced. With scrcpy and authorised debugging, each app can open in its own window instead.</p>
      <Button className="mt-2" size="sm" variant="ghost" aria-pressed={legacy} onClick={() => { setApps(null); setError(""); setUnavailable(""); setLegacy(!legacy); }}>
        {legacy ? "Use the phone screen instead" : "Use USB debugging (scrcpy)"}</Button>
    </details>}
  </>;
}
const noTabs: string[] = [];
const tabs = [
  { name: "Messages", icon: MessageSquare },
  { name: "Photos", icon: Image },
  { name: "Calls", icon: PhoneCall },
  { name: "Share", icon: Share2 },
  { name: "Apps", icon: AppWindow },
];

export const PhoneTabs = memo(function PhoneTabs({
  features = noFeatures,
  phone,
  client,
  active = true,
  onTab,
  handoffs = [],
  devices = [],
  currentDeviceId,
  cloudOffers,
  cloudTransfers,
  hidden = noTabs,
  screen,
  showApps = 0,
  usbDebugging = false,
  callAudio,
}: {
  features?: PhoneFeatureState;
  phone?: PhoneDevice;
  client: Client;
  active?: boolean;
  onTab?: (tab: string) => void;
  /** Tabs turned off in Settings → Phone. */
  hidden?: string[];
  screen?: PhoneScreenStatus;
  /** Raised by the header's Mirror screen: show Phone → Apps, where the phone screen request is. */
  showApps?: number;
  /** Settings → Advanced → USB debugging: offer scrcpy app windows in Phone → Apps. */
  usbDebugging?: boolean;
  /** Linux: talk through this computer over Bluetooth Hands-Free (Phone → Calls). */
  callAudio?: CallAudioStatus;
} & Partial<Handoffs> & CloudFiles) {
  const shown = useMemo(() => tabs.filter(({ name }) => !hidden.includes(name)), [hidden]);
  const [chosen, setTab] = useState("Messages");
  const tab = shown.some(({ name }) => name === chosen) ? chosen : shown[0].name;
  const [composing, setComposing] = useState(false);
  const ringing = features.calls.some((row) => row.device_id === phone?.id && row.state === "ringing");
  const open = useCallback((name: string) => { setTab(name); onTab?.(name); }, [onTab]);
  // A pinned phone app opened from the Start menu shows its session here.
  const revealed = useRef(screen?.reveal || 0);
  useEffect(() => {
    if ((screen?.reveal || 0) > revealed.current) { revealed.current = screen?.reveal || 0; open("Apps"); }
  }, [screen?.reveal, open]);
  const shownApps = useRef(showApps);
  useEffect(() => {
    if (showApps > shownApps.current) { shownApps.current = showApps; open("Apps"); }
  }, [showApps, open]);
  // Ctrl+1 to Ctrl+5 open the tabs; Ctrl+N starts a new message.
  useEffect(() => {
    if (!active) return;
    function onKey(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return;
      const index = Number(event.key) - 1;
      if (index >= 0 && index < shown.length) { event.preventDefault(); open(shown[index].name); }
      else if (event.key.toLowerCase() === "n" && phone?.capabilities.includes("sms") && !hidden.includes("Messages")) { event.preventDefault(); open("Messages"); setComposing(true); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, open, phone, shown, hidden]);
  // Each panel mounts on its first visit and then stays, so drafts survive a switch.
  const panel = (name: string, content: React.ReactNode, fill = false) => hidden.includes(name) ? null : (
    <TabsContent value={name} forceMount className={cn("data-[state=inactive]:hidden", fill && "h-full")}>
      <RetainedView active={tab === name} className={fill ? "h-full" : undefined}>{content}</RetainedView>
    </TabsContent>
  );
  return (
    <Tabs value={tab} onValueChange={open} className="h-full min-h-0">
      <TabsList aria-label="Phone features" className="shrink-0">
        {shown.map(({ name, icon: Icon }, index) => (
          <TabsTrigger key={name} value={name} title={`${name} (Ctrl+${index + 1})`}>
            <Icon aria-hidden="true" />
            {name}
            {name === "Calls" && ringing && <Badge aria-hidden="true" tone="attention" className="ml-0.5 px-1.5">Ringing</Badge>}
          </TabsTrigger>
        ))}
      </TabsList>
      <div className="min-h-0 flex-1 overflow-y-auto p-6 max-[1100px]:p-5">
        {!phone ? (
          <Empty title="Your phone, on this computer">
            <Smartphone size={40} />
            Use your server invitation to get started.
          </Empty>
        ) : (
          <>
            {panel("Messages", <Messages info={features} phone={phone} client={client} active={active && tab === "Messages"} composing={composing} setComposing={setComposing} />, true)}
            {panel("Photos", <Photos info={features} phone={phone} client={client} active={active && tab === "Photos"} />)}
            {panel("Calls", <Calls info={features} phone={phone} client={client} callAudio={callAudio} />)}
            {panel("Share", <Share info={features} phone={phone} client={client} handoffs={handoffs} devices={devices} currentDeviceId={currentDeviceId} cloudOffers={cloudOffers} cloudTransfers={cloudTransfers} />)}
            {panel("Apps", <Apps phone={phone} client={client} active={active && tab === "Apps"} screen={screen} usbDebugging={usbDebugging} />)}
          </>
        )}
      </div>
    </Tabs>
  );
});
