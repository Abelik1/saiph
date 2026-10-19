// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BatteryCharging, BatteryMedium, Bell, BellOff, Bluetooth, BluetoothOff, ChevronDown, Info, Mic, MonitorSmartphone, Plus, QrCode, RefreshCw, Save, Settings2, Signal, SignalHigh, SignalLow, SignalMedium, SignalZero, Smartphone, Video, Wifi, WifiHigh, WifiLow, WifiOff, WifiZero } from "lucide-react";
import type { Client, State } from "./types";
import { Action } from "./ui";
import { HubSuggestions } from "./HubInbox";
import { PhoneTabs } from "./PhoneTabs";
import { NotificationList, NotificationsEmpty } from "./PhoneNotifications";
import { PhonePanel, quickHint } from "./PhonePanel";
import { hiddenTabs, phonePreferences } from "./phonePreferences";
import { Enrollment } from "./Enrollment";
import { HostedPhoneSetup, PhoneSetup } from "./PhoneSetup";
import { PhoneCamera } from "./PhoneCamera";
import { LiveBadge, liveLabel, liveSources } from "./LiveIndicator";
import { cn } from "@/lib/utils";
import { PhoneMicrophone } from "./PhoneMicrophone";
import { PairingQr, validQr, type PairingQrCode } from "./PairingQr";
import { useSettingsNavigation } from "./settingsNavigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";

/** How long a dismissal waits for Undo before it reaches every device. */
const UNDO_MS = 5000;

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

const bars = [SignalZero, SignalLow, SignalMedium, SignalHigh, Signal];
/** Wi-Fi 0-4 on the icon's three arcs: no arc, one, two, then all three for 3 and 4. */
const wifiBars = [WifiZero, WifiLow, WifiHigh, Wifi, Wifi];

/**
 * Phone Link's header icons: Bluetooth, Wi-Fi and mobile bars from the phone's latest status.
 * Bars come from phone.signal, each from its own radio, so mobile bars show while on Wi-Fi,
 * as on the phone. A phone that predates phone.signal shows Wi-Fi as connected or not.
 */
function NetworkStatus({ phone }: { phone: Device }) {
  const status = phone.online ? phone.status : null;
  if (!status) return null;
  const signal = phone.signal;
  const mobile = signal ? signal.cellular_level : status.signal;
  const Bars = mobile === null ? null : bars[mobile];
  const wifi = signal ? (signal.wifi_level === null
    ? { Icon: WifiOff, label: "Wi-Fi not connected" }
    : { Icon: wifiBars[signal.wifi_level], label: `Wi-Fi signal ${signal.wifi_level} of 4` })
    : status.wifi === null ? null : { Icon: status.wifi ? Wifi : WifiOff, label: status.wifi ? "Wi-Fi connected" : "Wi-Fi not connected" };
  const icon = "inline-flex items-center text-muted-foreground [&_svg]:size-4";
  return <span className="inline-flex items-center gap-2" role="group" aria-label="Phone connections">
    {status.bluetooth !== null && <span className={icon} title={status.bluetooth ? "Bluetooth on" : "Bluetooth off"} role="img" aria-label={status.bluetooth ? "Bluetooth on" : "Bluetooth off"}>
      {status.bluetooth ? <Bluetooth /> : <BluetoothOff />}</span>}
    {wifi && <span className={icon} title={wifi.label} role="img" aria-label={wifi.label}><wifi.Icon /></span>}
    {Bars && <span className={icon} title={`Mobile signal ${mobile} of 4`} role="img" aria-label={`Mobile signal ${mobile} of 4`}><Bars /></span>}
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
  // Link phones report their battery; Saiph Cloud phones are marked by the computer.
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
  const [finishingSetup, setFinishingSetup] = useState(false);
  const handledSetup = useRef(0);
  useEffect(() => {
    if (handledSetup.current !== phoneSetupRequest) {
      handledSetup.current = phoneSetupRequest;
      setAdding(hasPhone);
    }
  }, [phoneSetupRequest, hasPhone]);
  useEffect(() => {
    if (!active) { setAdding(false); setPairing(null); setFinishingSetup(false); }
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
  const cloudNotices = (state.hosted?.notifications || []).filter((n) => n.device_id === phone?.id);
  const noticeCount = phone?.hosted ? cloudNotices.length : notices.length;
  const countingTabs = state.usage?.consent === "granted" || state.insights?.enabled === true;
  const countTab = useCallback((tab: string) => {
    if (countingTabs) void client.call("usage.screen", { screen: tab.toLowerCase() }).catch(() => undefined);
  }, [client, countingTabs]);

  const camera = Boolean(state.camera);
  const microphone = state.settings?.link?.microphone?.enabled === true || state.microphone?.running;
  // While the phone's camera or microphone is capturing it stays in plain sight; otherwise it waits in the device bar.
  const cameraLive = camera && Boolean(state.camera?.running);
  const microphoneLive = Boolean(state.microphone?.running);
  // Camera and phone screen only: red and unmistakable whenever this computer receives either.
  const liveNow = liveSources(state);
  // Mirror screen: the local-network phone screen (its own window in the desktop app), never scrcpy.
  const [showApps, setShowApps] = useState(0);
  const mirror = async () => {
    if (!phone) return;
    const screenState = state.phone_screen?.state;
    if (screenState === "live" && state.phone_screen?.window && state.phone_screen.window !== "unavailable") await client.call("screen.window");
    else if (screenState !== "live" && screenState !== "waiting" && screenState !== "connecting")
      await client.call("screen.session", { device_id: phone.id, resolution: "1080p", fps: 20, quality: "high" });
    // Phone → Apps shows the request, the code to scan if the phone did not get it, and the live card.
    setShowApps((value) => value + 1);
  };
  const preferences = phonePreferences(state.settings);
  const wallpaper = preferences.wallpaper && phone?.wallpaper ? phone.wallpaper : "";
  // A stable list, so the memoised tabs do not re-render with every state update.
  const hiddenKey = hiddenTabs(preferences).join("|");
  const hidden = useMemo(() => hiddenKey ? hiddenKey.split("|") : [], [hiddenKey]);
  // Only what the quick controls can actually show. Phones list their quick actions in their status (Hub and Saiph Cloud).
  const quick = phone && (["ringer", "ring", "dnd"].some((name) => phone.capabilities.includes(name)) || Boolean((phone.hosted || phone.status) && quickHint(phone))
    || (preferences.audio_player && state.phone_features?.media?.some((row) => row.device_id === phone.id && row.sessions.length)) || (state.dnd?.enabled && hub?.paired));
  // The wizard stays after approval so the owner sees the phone connect before the page changes under them.
  if ((!phone && !hub?.paired) || finishingSetup) return active ? <PhoneSetup state={state} client={client} onApproved={() => setFinishingSetup(true)} onDone={() => setFinishingSetup(false)} /> : null;
  return <div className="relative isolate flex min-h-[560px] flex-col gap-5 lg:h-[calc(100dvh-168px)]">
    {/* Settings → Phone → Use phone wallpaper: a soft, blurred backdrop behind the page. */}
    {wallpaper && <div aria-hidden="true" data-testid="phone-wallpaper" className="pointer-events-none absolute -inset-6 -z-10 overflow-hidden rounded-[18px]">
      <div className="absolute inset-0 scale-110 bg-cover bg-center opacity-35 blur-2xl" style={{ backgroundImage: `url("${wallpaper}")` }} />
      <div className="absolute inset-0 [background-image:linear-gradient(180deg,color-mix(in_srgb,var(--background)_45%,transparent),var(--background)_70%)]" />
    </div>}
    <header className="flex flex-wrap items-center gap-x-5 gap-y-3" aria-label="Device">
      {wallpaper
        ? <img src={wallpaper} alt="" className="h-[52px] w-8 shrink-0 rounded-[9px] border border-secondary-border object-cover" />
        : <span aria-hidden="true" className="flex h-[52px] w-8 shrink-0 items-center justify-center rounded-[9px] border border-secondary-border text-wave-2 [background-image:linear-gradient(155deg,color-mix(in_srgb,var(--wave-1)_24%,var(--card)),var(--card)_65%,color-mix(in_srgb,var(--wave-3)_22%,var(--card)))] [&_svg]:size-4"><Smartphone strokeWidth={1.5} /></span>}
      <div className="grid min-w-0 gap-1">
        <DeviceSwitcher phones={phones} phone={phone} choose={setSelected} />
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1"><DeviceStatus phone={phone} />{phone && <NetworkStatus phone={phone} />}{phone && <BatteryLevel phone={phone} />}
          {phone?.capabilities.includes("status") && <Action variant="ghost" size="icon-sm" className="-my-1 size-7" ariaLabel="Refresh phone status"
            title={phone.online ? "Ask " + phone.name + " for its latest status" : phone.name + " is offline"} disabled={!phone.online}
            run={() => client.call("phone.refresh", { device_id: phone.id })}><RefreshCw /></Action>}</div>
      </div>
      {liveNow.length > 0 && <LiveBadge className="self-center" title={liveLabel(liveNow)}
        label={liveNow.length === 2 ? "Live · camera + screen" : liveNow[0] === "camera" ? "Live · camera" : "Live · screen"} />}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {phone && <Action variant="secondary" size="sm" title={"Show " + phone.name + "'s screen on this computer over your Wi-Fi"} run={mirror}><MonitorSmartphone />Mirror screen</Action>}
        {camera && !cameraLive && <Popover>
          <PopoverTrigger asChild><Button variant="secondary" size="sm" title="Use your phone as this computer's webcam"><Video />Webcam</Button></PopoverTrigger>
          <PopoverContent className="w-96 p-0"><PhoneCamera camera={state.camera} config={state.settings?.link?.camera} deviceId={phone?.online && !phone.hosted ? phone.id : undefined} cloudPhone={phone?.online && phone.hosted ? { id: phone.id, name: phone.name } : undefined} client={client} /></PopoverContent>
        </Popover>}
        {microphone && !microphoneLive && <Popover>
          <PopoverTrigger asChild><Button variant="secondary" size="sm" title="Use your phone as this computer's microphone"><Mic />Microphone</Button></PopoverTrigger>
          <PopoverContent className="w-80 p-0"><PhoneMicrophone microphone={state.microphone} deviceId={phone?.online && !phone.hosted ? phone.id : undefined} deviceName={phone?.name} client={client} /></PopoverContent>
        </Popover>}
        {(hub?.paired || state.hosted?.available) && <Dialog open={adding} onOpenChange={addDevice}>
          <DialogTrigger asChild><Button variant="tonal" size="sm"><Plus />Add a device</Button></DialogTrigger>
          <DialogContent className={hub?.paired ? undefined : "w-[min(640px,calc(100vw-32px))]"}>
            <DialogHeader>
              <DialogTitle>Add a device</DialogTitle>
              <DialogDescription>{hub?.paired ? "Pair another phone or computer with this one." : "Connect a phone here. Another computer asks to join from its own Saiph; you approve it in a pop-up here."}</DialogDescription>
            </DialogHeader>
            {!hub?.paired ? state.hosted && <HostedPhoneSetup hosted={state.hosted} client={client} phones={info?.devices} onDone={() => setAdding(false)} /> : <>
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
    {cameraLive && state.camera?.local_state === "live" && <Card className="string-edge live-outline w-full max-w-[760px] shrink-0 gap-0 self-start border-secondary-border py-0" aria-label="Live phone camera">
      <div className="flex px-4 pt-3"><LiveBadge title="Your phone camera is live on this computer" /></div>
      <PhoneCamera camera={state.camera} config={state.settings?.link?.camera} client={client} />
    </Card>}
    <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)] gap-5 max-[1100px]:grid-cols-[272px_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col gap-4" aria-label="Phone status and notifications">
        {phone && !phone.online && <p className="m-0 rounded-[12px] border border-border bg-card/90 px-4 py-3 text-[12.5px] leading-relaxed text-muted-foreground" role="status">
          {phone.last_seen_at ? `Last seen ${new Date(phone.last_seen_at).toLocaleString()}. ` : ""}
          {phone.status?.paused
            ? "Paused: Sync over mobile data is off on your phone. Saiph resumes when it is on Wi-Fi."
            : phone.hosted
            ? "Open Saiph on your phone and check that Saiph Cloud is connected. Saved content remains available."
            : "Open Saiph on your phone and check that both devices can reach your server. Saved content remains available."}</p>}
        {!phone && hostedOn && <p className="m-0 rounded-[12px] border border-border bg-card/90 px-4 py-3 text-[12.5px] leading-relaxed text-muted-foreground" role="status">
          With Saiph Cloud, your approved phone appears here when it connects with an up-to-date Saiph app.
          To see texts and calls, turn on Texts and calls in Saiph Cloud on the phone.</p>}
        {/* The phone shares its clipboard only while Saiph's helper runs; this computer starts it with adb. */}
        {hostedOn && state.hosted?.clipboard_notice && <p role="status" className="m-0 rounded-[12px] border border-border bg-card/90 px-4 py-3 text-[12.5px] text-muted-foreground">{state.hosted.clipboard_notice}</p>}
        {phone?.online && !phone.hosted && state.settings?.link?.clipboard !== false && !phone.capabilities.includes("clipboard") && <ClipboardNotice phone={phone} />}
        {((cameraLive && state.camera?.local_state !== "live") || microphoneLive) && <Card className={cn("string-edge shrink-0 gap-0 border-secondary-border py-0", cameraLive && "live-outline")} aria-label="Capturing now">
          {cameraLive && state.camera?.local_state !== "live" && <PhoneCamera camera={state.camera} config={state.settings?.link?.camera} deviceId={phone?.online && !phone.hosted ? phone.id : undefined} cloudPhone={phone?.online && phone.hosted ? { id: phone.id, name: phone.name } : undefined} client={client} />}
          {cameraLive && state.camera?.local_state !== "live" && microphoneLive && <Separator />}
          {microphoneLive && <PhoneMicrophone microphone={state.microphone} deviceId={phone?.online && !phone.hosted ? phone.id : undefined} deviceName={phones.find(row=>row.id===state.microphone?.device_id)?.name} client={client} />}
        </Card>}
        {quick && <Card className="shrink-0 gap-4 p-4" aria-label="Quick controls">
          <PhonePanel features={state.phone_features} phone={phone} client={client} audio={preferences.audio_player} />
          <DoNotDisturb state={state} client={client} />
        </Card>}
        {preferences.features.notifications ? <Card className="min-h-[240px] flex-1 gap-0 overflow-hidden py-0" aria-label="Notifications">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-3">
            <h2 className="m-0 flex-1 text-[15px] font-semibold">Notifications</h2>
            {noticeCount > 0 && <Badge tone="default" className="tabular">{noticeCount}</Badge>}
            {notices.length > 1 && canAct && <Button variant="ghost" size="sm" className="h-7 px-2.5 text-[12.5px]" onClick={() => dismiss(notices.map((n) => n.id))}>Clear all</Button>}
          </div>
          {undoable > 0 && <div className="flex shrink-0 items-center gap-2 bg-secondary px-4 py-2 text-[12.5px]" role="status">
            <span className="flex-1">{undoable === 1 ? "Notification dismissed" : `${undoable} notifications dismissed`} on all devices.</span>
            <Button variant="link" className="text-[12.5px]" onClick={undo}>Undo</Button>
          </div>}
          {dismissError && <p className="inline-error m-0 px-4 pt-2 text-[12.5px]" role="alert">{dismissError}</p>}
          <div className="grid min-h-0 flex-1 content-start gap-2.5 overflow-y-auto p-4">
            <HubSuggestions state={state} client={client} />
            {phone?.hosted
              ? <NotificationList rows={cloudNotices} online={phone.online} dismiss={(ids) => Promise.all(ids.map((id) => client.call("hosted.notification.dismiss", { id })))}
                  client={client} commands={{ method: "hosted.notification", open: phone.capabilities.includes("notification-actions") }}
                  empty={<NotificationsEmpty title="No notifications yet">On your phone, tap Allow notifications in Saiph.</NotificationsEmpty>} />
              : <NotificationList rows={notices} client={client} online={canAct} dismiss={dismiss}
                  empty={<NotificationsEmpty title={!phone ? "Connect your phone" : !phone.online ? "Phone disconnected" : !canAct ? "Allow notifications" : "All clear"}>
                    {!phone ? "Pair your phone to see its notifications here." : !phone.online ? "Notifications will update when your phone reconnects."
                      : !canAct ? "Allow notification access in Saiph on your phone." : "Your phone notifications appear here automatically."}</NotificationsEmpty>} />}
            {!phone?.hosted && notices.length > 0 && !canAct && <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">{phone?.online
              ? "Allow notification access in Saiph on your phone to use these actions."
              : "Showing saved notifications. Reconnect your phone to reply or dismiss."}</p>}
          </div>
        </Card> : <p className="m-0 rounded-[12px] border border-border bg-card/90 px-4 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
          Notifications are turned off in Settings → Phone.</p>}
      </aside>
      <Card className="min-h-0 gap-0 overflow-hidden py-0" aria-label="Phone features and sharing">
        <PhoneTabs active={active} features={state.phone_features} phone={phone} client={client}
          cloudOffers={state.hosted?.offers} cloudTransfers={state.hosted?.transfers} screen={state.phone_screen}
          handoffs={state.handoffs || []} devices={info?.devices || []} currentDeviceId={state.settings?.hub?.device_id}
          onTab={countingTabs ? countTab : undefined} hidden={hidden} showApps={showApps} usbDebugging={preferences.usb_debugging} callAudio={state.call_audio} />
      </Card>
    </div>
  </div>;
}
