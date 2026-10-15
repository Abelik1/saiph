// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useRef, useState } from "react";
import { BatteryCharging, BatteryMedium, Bell, BellOff, BellRing, ChevronDown, Copy, ExternalLink, Info, MessageSquare, Mic, MonitorSmartphone, Plus, QrCode, Save, Settings2, Smartphone, Video, X } from "lucide-react";
import type { Client, PhoneNotification, State } from "./types";
import { Action, Form } from "./ui";
import { HubSuggestions } from "./HubInbox";
import { PhoneTabs } from "./PhoneTabs";
import { PhonePanel } from "./PhonePanel";
import { Enrollment } from "./Enrollment";
import { HostedPhoneSetup, PhoneSetup } from "./PhoneSetup";
import { PhoneCamera } from "./PhoneCamera";
import { PhoneMicrophone } from "./PhoneMicrophone";
import { PairingQr, validQr, type PairingQrCode } from "./PairingQr";
import { useSettingsNavigation } from "./settingsNavigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Eyebrow } from "@/components/ui/item";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";

/** How long a dismissal waits for Undo before it reaches every device. */
const UNDO_MS = 5000;

function Notification({
  row,
  client,
  online,
  dismiss,
}: {
  row: PhoneNotification;
  client: Client;
  online: boolean;
  dismiss: () => void;
}) {
  const [replying, setReplying] = useState(false);
  const [reply, setReply] = useState("");
  const [sent, setSent] = useState(false);
  const command = (operation: string, extra = {}) => client.call("phone.notification", { id: row.id, operation, ...extra });
  return <article className="grid gap-2 rounded-[12px] border border-border bg-field/50 p-3.5">
    <div className="flex items-center gap-1">
      <Eyebrow className="min-w-0 flex-1 truncate normal-case tracking-normal">{row.app}</Eyebrow>
      <Action variant="ghost" size="icon-sm" className="-my-1" title="Open on phone" ariaLabel={"Open " + row.title + " on phone"} disabled={!online} run={() => command("open")}><ExternalLink /></Action>
      <Button variant="ghost" size="icon-sm" className="-my-1 -mr-1.5" title="Dismiss on all devices" aria-label="Dismiss on all devices" disabled={!online} onClick={dismiss}><X /></Button>
    </div>
    <h3 className="m-0 text-[13.5px] font-semibold leading-snug [overflow-wrap:anywhere]">{row.title}</h3>
    {row.text && <p className="m-0 whitespace-pre-wrap text-[12.5px] leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">{row.text}</p>}
    {(row.code || row.actions.length > 0 || row.reply_key) && <div className="flex flex-wrap gap-1.5 pt-0.5">
      {row.code && <Action variant="tonal" size="sm" run={() => client.call("phone.code.copy", { id: row.id })}><Copy />Copy code {row.code}</Action>}
      {row.actions.map((action) => <Action key={action.index} variant="tonal" size="sm" disabled={!online} run={() => command("action", { index: action.index })}>{action.label}</Action>)}
      {row.reply_key && !replying && <Button variant="tonal" size="sm" disabled={!online} onClick={() => setReplying(true)}><MessageSquare />Reply</Button>}
    </div>}
    {row.reply_key && replying && <Form className="grid gap-1.5 pt-1" submit={async () => { await command("reply", { reply_key: row.reply_key, text: reply }); setReply(""); setSent(true); }}>
      <div className="flex gap-2">
        <Input autoFocus aria-label={"Reply to " + row.title} placeholder={"Reply to " + row.title} value={reply} maxLength={4096} className="h-9"
          onChange={(e) => { setReply(e.target.value); setSent(false); }} disabled={!online}
          onKeyDown={(e) => { if (e.key === "Escape" && !reply) setReplying(false); }} />
        <Button type="submit" variant="tonal" size="icon-sm" className="size-9" aria-label="Send reply" title="Send reply" disabled={!online || !reply.trim()}><MessageSquare /></Button>
      </div>
      {sent && <small role="status" className="text-[12px] text-status-on">Reply queued for your phone.</small>}
    </Form>}
  </article>;
}

/** Shared Do Not Disturb: the newest change from any paired device wins. */
export function DoNotDisturb({ state, client }: { state: State; client: Client }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const dnd = state.dnd;
  if (!dnd?.enabled || !state.settings?.hub?.paired) return null;
  const from = dnd.source && dnd.source !== state.settings.hub.device_id ? state.phone?.devices.find((d) => d.id === dnd.source)?.name : "";
  async function toggle(active: boolean) {
    setPending(true); setError("");
    try { await client.call("continuity.dnd", { active }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setPending(false); }
  }
  return <div className="grid gap-1" role="group" aria-label="Do Not Disturb">
    <div className="flex items-center gap-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-secondary text-secondary-foreground [&_svg]:size-4">{dnd.active ? <BellOff /> : <Bell />}</span>
      <span className="grid min-w-0 flex-1">
        <b className="text-[13px] font-medium">Do Not Disturb</b>
        <small className="text-[12px] text-muted-foreground"><span>{dnd.active ? "On" + (from ? " · from " + from : "") : "Off"}</span> · all your devices</small>
      </span>
      <Switch checked={dnd.active} disabled={pending} aria-label="Do Not Disturb on all devices" onCheckedChange={(active) => void toggle(active)} />
    </div>
    {error && <span className="inline-error" role="alert">{error}</span>}
  </div>;
}

type Device = NonNullable<State["phone"]>["devices"][number];

function BatteryLevel({ phone }: { phone: Device }) {
  if (!phone.battery) return null;
  const Icon = phone.battery.is_charging ? BatteryCharging : BatteryMedium;
  return <span className="inline-flex items-center gap-1 text-[12px] text-muted-foreground tabular [&_svg]:size-4">
    <Icon aria-hidden="true" /><span>{phone.battery.battery_level}%</span>
    {phone.battery.is_charging && <span>· charging</span>}{!phone.online && <span>· last reported</span>}
  </span>;
}

function DeviceStatus({ phone }: { phone?: Device }) {
  return phone?.online ? <Badge tone="good">Online</Badge> : phone ? <Badge tone="quiet">Offline</Badge> : <Badge tone="attention">Pair once to get started</Badge>;
}

/** The device the page shows. With more than one, the name is the switcher. */
function DeviceSwitcher({ phones, phone, choose }: { phones: Device[]; phone?: Device; choose: (id: string) => void }) {
  const name = <h2 className="m-0 truncate text-[20px] font-semibold tracking-[-0.03em]">{phone?.name || "Your phone"}</h2>;
  if (phones.length < 2) return name;
  return <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button variant="ghost" aria-label={"Device: " + (phone?.name || "")} className="-ml-3 h-auto justify-self-start justify-start gap-1.5 px-3 py-1 text-foreground hover:text-foreground">
        {name}<ChevronDown className="size-4 text-muted-foreground" />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent>
      <DropdownMenuLabel>Show device</DropdownMenuLabel>
      <DropdownMenuRadioGroup value={phone?.id} onValueChange={choose}>
        {phones.map((d) => <DropdownMenuRadioItem key={d.id} value={d.id}>
          <span className={"size-2 shrink-0 rounded-full " + (d.online ? "bg-status-on" : "bg-muted-foreground/50")} aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">{d.name}</span>
          <small className="text-[12px] text-muted-foreground tabular">{d.online ? "Online" : "Offline"}{d.battery ? ` · ${d.battery.battery_level}%` : ""}</small>
        </DropdownMenuRadioItem>)}
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>;
}

/** Clipboard sharing needs a one-time helper start; the detail is there when asked for. */
function ClipboardNotice({ phone }: { phone: Device }) {
  return <div className="flex items-center gap-2 rounded-[10px] bg-attention-surface px-3 py-2 text-[12.5px] text-attention-foreground">
    <span className="min-w-0 flex-1">Clipboard isn't shared with {phone.name} yet.</span>
    <Popover>
      <PopoverTrigger asChild><Button variant="link" className="text-[12.5px] text-attention-foreground"><Info className="size-3.5" />How to fix</Button></PopoverTrigger>
      <PopoverContent className="text-[12.5px] leading-relaxed text-muted-foreground">
        <p className="m-0">Check that Clipboard is on in Saiph on your phone. Then connect the phone to this computer once, over USB or wireless debugging, so Saiph can start its clipboard helper.</p>
        <p className="m-0">The setup guide's Optional tools step shows whether the Android tools (adb) are installed.</p>
      </PopoverContent>
    </Popover>
  </div>;
}

export function Phone({
  state,
  client,
  active = true,
}: {
  state: State;
  client: Client;
  active?: boolean;
}) {
  const info = state.phone;
  // Link phones report their battery; Saiph Hosted phones are marked by the computer.
  const phones =
    info?.devices.filter((d) => d.capabilities.includes("battery") || d.hosted) || [];
  const hostedOn = state.hosted?.enabled === true;
  const [selected, setSelected] = useState("");
  const phone = phones.find((d) => d.id === selected) || phones[0];
  const hasPhone = Boolean(phone);
  const { openSettings, phoneSetupRequest = 0 } = useSettingsNavigation();
  const canAct = Boolean(phone?.online && phone.capabilities.includes("notifications"));
  const hub = state.settings?.hub;
  const hubIdentity = JSON.stringify([hub?.paired, hub?.base_url, hub?.device_id]);
  // A pending response must not restore a QR after unmount or a Hub change.
  const sessionRef = useRef({ identity: hubIdentity, active: true });
  if (sessionRef.current.identity !== hubIdentity) sessionRef.current = { identity: hubIdentity, active: true };
  useEffect(() => {
    const session = sessionRef.current;
    session.active = true;
    return () => { session.active = false; };
  }, [hubIdentity]);
  // The module grid is itself a private credential. Keep it only in this page's memory.
  const [pairing, setPairing] = useState<{ qr: PairingQrCode; shownAt: number; known: string[] | null; hub: string } | null>(null);
  const [pairingNotice, setPairingNotice] = useState("");
  const [adding, setAdding] = useState(false);
  const handledSetup = useRef(0);
  useEffect(() => {
    if (handledSetup.current !== phoneSetupRequest) {
      handledSetup.current = phoneSetupRequest;
      setAdding(hasPhone);
    }
  }, [phoneSetupRequest, hasPhone]);
  useEffect(() => {
    if (!active) { setAdding(false); setPairing(null); }
  }, [active]);
  if (pairing && (!hub?.paired || pairing.hub !== hubIdentity || (info &&
      (pairing.known === null || info.devices.some((d) => !pairing.known?.includes(d.id)))))) {
    setPairing(null);
    setPairingNotice(pairing.known && info?.devices.some((d) => !pairing.known?.includes(d.id))
      ? "Your new device was added. The pairing QR was closed."
      : "The connection or device list changed. Show a new pairing QR when your phone is ready.");
  }
  const expirePairing = useCallback(() => { setPairing(null); setPairingNotice("The pairing QR expired. Show a new one when your phone is ready."); }, []);
  async function showPairingQr() {
    setPairingNotice("");
    const session = sessionRef.current;
    const shownAt = Date.now(); // Include bridge/network delay in the countdown conservatively.
    const qr = await client.call<unknown>("enrollment.qr");
    if (!session.active || sessionRef.current !== session) return;
    if (!validQr(qr)) throw new Error("The pairing QR could not be shown. Save an invitation file instead.");
    setPairing({ qr, shownAt, known: info ? info.devices.map((d) => d.id) : null, hub: hubIdentity });
  }
  // Closing the dialog also closes the QR: it is a credential, so it never lingers out of sight.
  function addDevice(open: boolean) {
    setAdding(open);
    if (!open) { setPairing(null); setPairingNotice(""); }
  }

  // "Dismiss on all devices" waits briefly so it can be undone, then reaches every device.
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [dismissError, setDismissError] = useState("");
  const [undoable, setUndoable] = useState(0);
  const timer = useRef<number | undefined>(undefined);
  const queued = useRef<string[]>([]);
  const send = useCallback(() => {
    window.clearTimeout(timer.current);
    const ids = queued.current;
    queued.current = [];
    setUndoable(0);
    if (!ids.length) return;
    void Promise.all(ids.map((id) => client.call("phone.notification", { id, operation: "dismiss" })))
      .catch((reason) => { setDismissError(reason instanceof Error ? reason.message : String(reason)); setDismissed((current) => current.filter((id) => !ids.includes(id))); });
  }, [client]);
  useEffect(() => send, [send]);
  function dismiss(ids: string[]) {
    setDismissError("");
    queued.current = [...queued.current, ...ids];
    setUndoable(queued.current.length);
    setDismissed((current) => [...current, ...ids]);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(send, UNDO_MS);
  }
  function undo() {
    window.clearTimeout(timer.current);
    const ids = queued.current;
    queued.current = [];
    setUndoable(0);
    setDismissed((current) => current.filter((id) => !ids.includes(id)));
  }
  const notices = (info?.notifications || []).filter((n) => (!phone || n.device_id === phone.id) && !dismissed.includes(n.id));

  const camera = state.settings?.link?.camera?.enabled !== false;
  const microphone = state.settings?.link?.microphone?.enabled === true || state.microphone?.running;
  // While the phone's camera or microphone is capturing it stays in plain sight; otherwise it waits in the device bar.
  const cameraLive = camera && Boolean(state.camera?.running);
  const microphoneLive = Boolean(state.microphone?.running);
  const quick = phone && (phone.capabilities.includes("ringer") || state.phone_features?.media?.some((row) => row.device_id === phone.id && row.sessions.length) || state.dnd?.enabled);
  if (!phone && !hub?.paired) return active ? <PhoneSetup state={state} client={client} /> : null;
  return <div className="flex min-h-[560px] flex-col gap-5 lg:h-[calc(100dvh-168px)]">
    <header className="flex flex-wrap items-center gap-x-5 gap-y-3" aria-label="Device">
      <span aria-hidden="true" className="flex h-[52px] w-8 shrink-0 items-center justify-center rounded-[9px] border border-secondary-border text-wave-2 [background-image:linear-gradient(155deg,color-mix(in_srgb,var(--wave-1)_24%,var(--card)),var(--card)_65%,color-mix(in_srgb,var(--wave-3)_22%,var(--card)))] [&_svg]:size-4"><Smartphone strokeWidth={1.5} /></span>
      <div className="grid min-w-0 gap-1">
        <DeviceSwitcher phones={phones} phone={phone} choose={setSelected} />
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1"><DeviceStatus phone={phone} />{phone && <BatteryLevel phone={phone} />}</div>
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {phone?.capabilities.includes("ring") && <Action variant="secondary" size="sm" title={"Ring " + phone.name + " so you can find it"} disabled={!phone.online} run={() => client.call("phone.ring", { device_id: phone.id })}><BellRing />Find phone</Action>}
        {phone && <Action variant="secondary" size="sm" title={"Show " + phone.name + "'s screen on this computer"} disabled={!phone.online} run={() => client.call("phone.mirror", { device_id: phone.id })}><MonitorSmartphone />Mirror screen</Action>}
        {camera && !cameraLive && <Popover>
          <PopoverTrigger asChild><Button variant="secondary" size="sm" title="Use your phone as this computer's webcam"><Video />Webcam</Button></PopoverTrigger>
          <PopoverContent className="w-96 p-0"><PhoneCamera camera={state.camera} config={state.settings?.link?.camera} deviceId={phone?.online && !phone.hosted ? phone.id : undefined} client={client} /></PopoverContent>
        </Popover>}
        {microphone && !microphoneLive && <Popover>
          <PopoverTrigger asChild><Button variant="secondary" size="sm" title="Use your phone as this computer's microphone"><Mic />Microphone</Button></PopoverTrigger>
          <PopoverContent className="w-80 p-0"><PhoneMicrophone microphone={state.microphone} deviceId={phone?.online && !phone.hosted ? phone.id : undefined} deviceName={phone?.name} client={client} /></PopoverContent>
        </Popover>}
        {(hub?.paired || state.hosted?.available) && <Dialog open={adding} onOpenChange={addDevice}>
          <DialogTrigger asChild><Button variant="tonal" size="sm"><Plus />{hub?.paired ? "Add a device" : "Connect a phone"}</Button></DialogTrigger>
          <DialogContent className={hub?.paired ? undefined : "w-[min(640px,calc(100vw-32px))]"}>
            <DialogHeader>
              <DialogTitle>{hub?.paired ? "Add a device" : "Connect a phone"}</DialogTitle>
              <DialogDescription>{hub?.paired ? "Pair another phone or computer with this one." : "Sign in on your phone, scan the code and approve it here."}</DialogDescription>
            </DialogHeader>
            {!hub?.paired ? state.hosted && <HostedPhoneSetup hosted={state.hosted} client={client} onDone={() => setAdding(false)} /> : <>
            {pairing && <PairingQr qr={pairing.qr} shownAt={pairing.shownAt} onExpire={expirePairing} onClose={() => setPairing(null)} />}
            <div className="grid gap-3" role="group" aria-label="Add a device">
                  {pairingNotice && <p className="m-0 rounded-[10px] bg-muted px-3 py-2.5 text-[13px]" role="status">{pairingNotice}</p>}
                  <div className="flex flex-wrap gap-2">
                    <Action variant="default" disabled={Boolean(pairing)} run={showPairingQr}><QrCode />Show pairing QR</Action>
                    <Action variant="secondary" run={() => client.call("enrollment.export")}><Save />Save invitation file</Action>
                  </div>
                  <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">A QR works once and only for a few minutes. Use an invitation file for a device that can't scan.</p>
                  {state.user_verification === "unavailable" && <p className="m-0 text-[12.5px] text-muted-foreground">Set up Windows Hello so adding a device needs your face, fingerprint or PIN.</p>}
            </div>
            </>}
          </DialogContent>
        </Dialog>}
        {openSettings && <Button variant="ghost" size="icon-sm" aria-label="Device settings" title="Device settings" onClick={() => openSettings("Devices")}><Settings2 /></Button>}
      </div>
    </header>
    {/* Server invitations are for self-hosting; a Saiph account never sees them. */}
    {(state.enrollment?.ready || state.setup?.mode === "hub") && <Enrollment state={state} client={client} />}
    {!phone && hub?.paired && <Card className="gap-3 p-6">
      <h2 className="m-0 text-xl font-semibold">Connect your phone</h2>
      <p className="m-0 text-muted-foreground">Open Saiph on your phone and scan a pairing QR from this computer.</p>
      <div><Button variant="default" onClick={() => addDevice(true)}><QrCode />Connect a phone</Button></div>
    </Card>}
    <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)] gap-5 max-[1100px]:grid-cols-[272px_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col gap-4" aria-label="Phone status and notifications">
        {phone && !phone.online && <p className="m-0 rounded-[12px] border border-border bg-card/90 px-4 py-3 text-[12.5px] leading-relaxed text-muted-foreground" role="status">
          {phone.last_seen_at ? `Last seen ${new Date(phone.last_seen_at).toLocaleString()}. ` : ""}
          {phone.hosted
            ? "Open Saiph on your phone and check that Saiph Hosted is connected. Saved content remains available."
            : "Open Saiph on your phone and check that both devices can reach your server. Saved content remains available."}</p>}
        {!phone && hostedOn && <p className="m-0 rounded-[12px] border border-border bg-card/90 px-4 py-3 text-[12.5px] leading-relaxed text-muted-foreground" role="status">
          With Saiph Hosted, your approved phone appears here when it connects with an up-to-date Saiph app.
          To see texts and calls, turn on Texts and calls in Saiph Hosted on the phone.</p>}
        {/* The phone shares its clipboard only while Saiph's helper runs; this computer starts it with adb. */}
        {phone?.online && !phone.hosted && state.settings?.link?.clipboard !== false && !phone.capabilities.includes("clipboard") && <ClipboardNotice phone={phone} />}
        {(cameraLive || microphoneLive) && <Card className="string-edge shrink-0 gap-0 border-secondary-border py-0" aria-label="Capturing now">
          {cameraLive && <PhoneCamera camera={state.camera} config={state.settings?.link?.camera} deviceId={phone?.online && !phone.hosted ? phone.id : undefined} client={client} />}
          {cameraLive && microphoneLive && <Separator />}
          {microphoneLive && <PhoneMicrophone microphone={state.microphone} deviceId={phone?.online && !phone.hosted ? phone.id : undefined} deviceName={phones.find(row=>row.id===state.microphone?.device_id)?.name} client={client} />}
        </Card>}
        {quick && <Card className="shrink-0 gap-4 p-4" aria-label="Quick controls">
          <PhonePanel features={state.phone_features} phone={phone} client={client} />
          <DoNotDisturb state={state} client={client} />
        </Card>}
        <Card className="min-h-[240px] flex-1 gap-0 overflow-hidden py-0" aria-label="Notifications">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-3">
            <h2 className="m-0 flex-1 text-[15px] font-semibold">Notifications</h2>
            {notices.length > 0 && <Badge tone="default" className="tabular">{notices.length}</Badge>}
            {notices.length > 1 && canAct && <Button variant="ghost" size="sm" className="h-7 px-2.5 text-[12.5px]" onClick={() => dismiss(notices.map((n) => n.id))}>Clear all</Button>}
          </div>
          {undoable > 0 && <div className="flex shrink-0 items-center gap-2 bg-secondary px-4 py-2 text-[12.5px]" role="status">
            <span className="flex-1">{undoable === 1 ? "Notification dismissed" : `${undoable} notifications dismissed`} on all devices.</span>
            <Button variant="link" className="text-[12.5px]" onClick={undo}>Undo</Button>
          </div>}
          {dismissError && <p className="inline-error m-0 px-4 pt-2 text-[12.5px]" role="alert">{dismissError}</p>}
          <div className="grid min-h-0 flex-1 content-start gap-2.5 overflow-y-auto p-4">
            <HubSuggestions state={state} client={client} />
            {phone?.hosted ? <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">With Saiph Hosted, your phone's notifications appear in Settings → Saiph Hosted.</p>
              : notices.length ? notices.map((row) => <Notification key={row.id} row={row} client={client} online={canAct} dismiss={() => dismiss([row.id])} />)
              : <div className="grid gap-1 py-6 text-center">
                  <h3 className="m-0 text-[14px] font-semibold">{!phone ? "Connect your phone" : !phone.online ? "Phone disconnected" : !canAct ? "Allow notifications" : "All clear"}</h3>
                  <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">{!phone ? "Pair your phone to see its notifications here." : !phone.online ? "Notifications will update when your phone reconnects."
                    : !canAct ? "Allow notification access in Saiph on your phone." : "Your phone notifications appear here automatically."}</p>
                </div>}
            {!phone?.hosted && notices.length > 0 && !canAct && <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">{phone?.online
              ? "Allow notification access in Saiph on your phone to use these actions."
              : "Showing saved notifications. Reconnect your phone to reply or dismiss."}</p>}
          </div>
        </Card>
      </aside>
      <Card className="min-h-0 gap-0 overflow-hidden py-0" aria-label="Phone features and sharing">
        <PhoneTabs active={active} features={state.phone_features} phone={phone} client={client}
          handoffs={state.handoffs || []} devices={info?.devices || []} currentDeviceId={state.settings?.hub?.device_id}
          onTab={state.usage?.consent === "granted" || state.insights?.enabled === true ? (tab) => void client.call("usage.screen", { screen: tab.toLowerCase() }).catch(() => undefined) : undefined} />
      </Card>
    </div>
  </div>;
}
