// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useRef, useState } from "react";
import { Battery, Bell, BellOff, MessageSquare, Smartphone, X } from "lucide-react";
import type { Client, PhoneNotification, State } from "./types";
import { Action, Empty, Form } from "./ui";
import { HubInbox } from "./HubInbox";
import { PhoneTabs } from "./PhoneTabs";
import { PhonePanel } from "./PhonePanel";
import { Handoff } from "./Handoff";
import { Enrollment } from "./Enrollment";
import { PhoneCamera } from "./PhoneCamera";
import { PhoneMicrophone } from "./PhoneMicrophone";
import { PairingQr, validQr, type PairingQrCode } from "./PairingQr";

function Notification({ row, client, online }: { row: PhoneNotification; client: Client; online: boolean }) {
  const [reply, setReply] = useState("");
  const [sent, setSent] = useState(false);
  const command = (operation: string, extra = {}) => client.call("phone.notification", { id: row.id, operation, ...extra });
  return <article className="phone-notification">
    <div className="section-head"><small>{row.app}</small>
      <Action className="icon-button" title="Dismiss on all devices" ariaLabel="Dismiss on all devices" disabled={!online} run={() => command("dismiss")}><X size={15} /></Action>
    </div>
    <h3>{row.title}</h3><p>{row.text}</p>
    <div className="phone-notification-actions">
      {row.actions.map((action) => <Action key={action.index} className="text-button" disabled={!online} run={() => command("action", { index: action.index })}>{action.label}</Action>)}
      {row.code && <Action className="text-button" run={() => client.call("phone.code.copy", { id: row.id })}>Copy code {row.code}</Action>}
      <Action className="text-button" disabled={!online} run={() => command("open")}>Open on phone</Action>
    </div>
    {row.reply_key && <Form submit={async () => { await command("reply", { reply_key: row.reply_key, text: reply }); setReply(""); setSent(true); }}>
      <label>Reply to {row.app}<input aria-label={"Reply to " + row.title} value={reply} maxLength={4096} onChange={(e) => { setReply(e.target.value); setSent(false); }} disabled={!online} /></label>
      <button disabled={!online || !reply.trim()}><MessageSquare size={14} />Send reply</button>
      {sent && <small role="status">Reply queued for your phone.</small>}
    </Form>}
  </article>;
}

/** Shared Do Not Disturb: the newest change from any paired device wins. */
export function DoNotDisturb({ state, client }: { state: State; client: Client }) {
  const dnd = state.dnd;
  if (!dnd?.enabled || !state.settings?.hub?.paired) return null;
  const from = dnd.source && dnd.source !== state.settings.hub.device_id ? state.phone?.devices.find((d) => d.id === dnd.source)?.name : "";
  return <div className="dnd-toggle" role="group" aria-label="Do Not Disturb">
    <span>{dnd.active ? <BellOff size={16} /> : <Bell size={16} />}<b>Do Not Disturb</b> <small>{dnd.active ? "On" + (from ? " · from " + from : "") : "Off"}</small></span>
    <Action className="text-button" ariaLabel={(dnd.active ? "Turn off" : "Turn on") + " Do Not Disturb on all devices"} run={() => client.call("continuity.dnd", { active: !dnd.active })}>{dnd.active ? "Turn off" : "Turn on"}</Action>
  </div>;
}

export function Phone({ state, client }: { state: State; client: Client }) {
  const info = state.phone;
  const phones = info?.devices.filter((d) => d.capabilities.includes("battery")) || [];
  const [selected, setSelected] = useState("");
  const phone = phones.find((d) => d.id === selected) || phones[0];
  const notices = (info?.notifications || []).filter((n) => !phone || n.device_id === phone.id);
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
  return <div className="phone-layout">
    <aside className="phone-rail" aria-label="Phone status and notifications">
      <div className="phone-device">
        <Action className="phone-silhouette" title="Mirror your phone" ariaLabel="Mirror your phone" disabled={!phone?.online} run={() => client.call("phone.mirror", {device_id:phone?.id})}><Smartphone size={52} strokeWidth={1} /></Action>
        <div><h2>{phone?.name || "Your phone"}</h2>
          {phones.length > 1 && <label>Phone<select value={phone?.id} onChange={(e) => setSelected(e.target.value)}>{phones.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>}
          <p className={phone?.online ? "phone-online" : "muted"}>{phone?.online ? "Online" : phone ? "Offline" : "Pair once to get started"}</p>
          <DoNotDisturb state={state} client={client} />
          <PhonePanel features={state.phone_features} phone={phone} client={client} />
          {phone?.online && phone.capabilities.includes("ring") && <Action className="text-button" run={() => client.call("phone.ring", { device_id: phone.id })}>Ring {phone.name}</Action>}
          {phone?.battery && <small className="phone-battery"><Battery size={16} />{phone.battery.battery_level}%{phone.battery.is_charging ? " · charging" : ""}{!phone.online ? " · last reported" : ""}</small>}
          {state.settings?.hub?.paired && <div className="add-device" role="group" aria-label="Add a device">
            <small>Add a device</small>
            <Action className="text-button" disabled={Boolean(pairing)} run={showPairingQr}>Show pairing QR</Action>
            <Action className="text-button" run={() => client.call("enrollment.export")}>Save invitation file</Action>
            {state.user_verification === "unavailable" && <small className="muted">Set up Windows Hello so adding a device needs your face, fingerprint or PIN.</small>}
          </div>}
        </div>
      </div>
      {state.settings?.link?.camera?.enabled !== false && <PhoneCamera camera={state.camera} config={state.settings?.link?.camera} deviceId={phone?.online ? phone.id : undefined} client={client} />}
      {(state.settings?.link?.microphone?.enabled === true || state.microphone?.running) && <PhoneMicrophone microphone={state.microphone} deviceId={phone?.online ? phone.id : undefined} deviceName={state.microphone?.running ? phones.find(row=>row.id===state.microphone?.device_id)?.name : phone?.name} client={client} />}
      <div className="section-head"><h2>Notifications</h2><Bell size={17} /></div>
      {notices.length ? notices.map((row) => <Notification key={row.id} row={row} client={client} online={canAct} />) : <Empty title="All clear">Your phone notifications appear here automatically.</Empty>}
      <HubInbox state={state} client={client} />
    </aside>
    <section className="phone-detail" aria-label="Phone features and sharing">
      <Enrollment state={state} client={client} />
      {pairing && <PairingQr qr={pairing.qr} shownAt={pairing.shownAt} onExpire={expirePairing} onClose={() => setPairing(null)} />}
      {pairingNotice && !pairing && <p className="pairing-notice muted" role="status">{pairingNotice}</p>}
      <PhoneTabs features={state.phone_features} phone={phone} client={client} />
      <details className="phone-handoff"><summary>Continue on another device</summary><Handoff items={state.handoffs || []} devices={info?.devices || []} currentDeviceId={state.settings?.hub?.device_id} client={client} /></details>
    </section>
  </div>;
}
