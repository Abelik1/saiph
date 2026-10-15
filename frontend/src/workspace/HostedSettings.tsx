// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import type { Client, HostedConfig, HostedState } from "./types";
import { Action, Card, Form } from "./ui";
import { validQr } from "./PairingQr";
import { HostedJoin } from "./HostedJoin";
import { HostedSignIn } from "./HostedSignIn";

type RootCode = {code: string; fingerprint: string; modules: string[]; expires_at: string; expires_in: number};
type Request = {device_id: string; fingerprint: string; expires_at: number};
type Offered = Request & {code: string};
const emptyConfig: HostedConfig = {service_url: "", issuer: "", audience: "", client_id: "", refresh_tokens: false};
const statuses: Record<string, string> = {off: "Off", starting: "Starting", setup: "Set up this computer as root", active: "Connected", signed_out: "Signed out", sign_in_required: "Sign in again", offline: "Offline; reconnecting", renewal_pending: "Waiting to renew device approvals", retrying: "Reconnecting", clock: "Check this computer's clock", keys_unavailable: "Hosted keys could not be unlocked", awaiting_approval: "Waiting for your main computer to approve this computer", removed: "Removed by your main computer"};

/** Tells the person whether approving or removing devices needs their face, fingerprint or PIN. */
export function VerificationNote({value}: {value?: string}) {
  if (value === "windows_hello") return <p className="muted">Windows Hello confirms it's you before a device is added or removed.</p>;
  if (value === "unavailable") return <p className="muted">Anyone using this computer while it is unlocked can add a device. On Windows, set up Windows Hello in Settings → Accounts → Sign-in options so adding a device needs your face, fingerprint or PIN.</p>;
  return null;
}

/** The signed root code a phone scans to trust this computer. Shown only on request. */
export function HostedRootCode({hosted, client, autoShow = false}: {hosted: HostedState; client: Client; autoShow?: boolean}) {
  const [root, setRoot] = useState<RootCode | null>(null);
  const [error, setError] = useState("");
  async function showRoot(method: string) {
    const result = await client.call<RootCode>(method);
    if (!validQr(result)) throw new Error("Could not display the root QR code.");
    setRoot(result);
  }
  // In the setup guide the next step is scanning, so the code is shown straight away.
  useEffect(() => {
    if (autoShow && hosted.identity) showRoot("hosted.root_code").catch(failure => setError(failure instanceof Error ? failure.message : String(failure)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoShow, hosted.identity]);
  return <>
    {root && <div>
      <p>On your phone, scan this code, then check that the full fingerprint matches on both screens. It expires at {new Date(root.expires_at).toLocaleTimeString()}.</p>
      <svg role="img" aria-label="Hosted root approval QR code" viewBox={`0 0 ${root.modules.length} ${root.modules.length}`} width="264" height="264" shapeRendering="crispEdges"><rect width="100%" height="100%" fill="white" /><path fill="black" d={root.modules.map((row, y) => [...row].map((cell, x) => cell === "1" ? `M${x} ${y}h1v1h-1z` : "").join("")).join("")} /></svg>
      <p className="muted">Full root fingerprint</p><code>{root.fingerprint}</code>
      <details><summary>Can't scan? Copy the code instead</summary><label>Root code<textarea readOnly value={root.code} /></label></details>
      <button type="button" onClick={() => setRoot(null)}>Hide root code</button>
    </div>}
    {error && !root && <p role="alert">{error}</p>}
    <Action run={() => showRoot(hosted.identity ? "hosted.root_code" : "hosted.setup_root")}>{!hosted.identity ? "Set up this computer as root" : root ? "Show a new code" : "Show root approval code"}</Action>
  </>;
}

/** Approve a device's signed request after the owner compares its full fingerprint.
 * Devices that signed in offer their request through the service, so it appears here by
 * itself; the code is verified on this computer and pasting stays as a fallback. */
export function HostedApproveDevice({hosted, client}: {hosted: HostedState; client: Client}) {
  const [code, setCode] = useState("");
  const [request, setRequest] = useState<Request | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [label, setLabel] = useState("");
  const [offered, setOffered] = useState<Offered[]>([]);
  useEffect(() => {
    let alive = true;
    const look = () => client.call<{requests: Offered[]}>("hosted.requests")
      .then(value => { if (alive) setOffered(Array.isArray(value?.requests) ? value.requests : []); }).catch(() => undefined);
    void look();
    const timer = window.setInterval(look, 4000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [client]);
  const review = (item: Offered) => { setCode(item.code); setRequest(item); setConfirmed(false); setLabel(""); };
  const reset = () => { setRequest(null); setCode(""); setConfirmed(false); setLabel(""); };
  return <>
    {!request && (offered.length ? <div className="hosted-offered" aria-live="polite">
      {offered.map(item => <div key={item.device_id} className="hosted-offered-item">
        <p><b>A device is asking to join your Saiph account.</b></p>
        <p className="muted">Its fingerprint begins <code>{item.fingerprint.split(" ").slice(0, 2).join(" ")}</code>.</p>
        <button type="button" onClick={() => review(item)}>Review and approve</button>
      </div>)}
    </div> : <p className="muted" aria-live="polite">Waiting for your device… After it signs in and checks this computer's code, it appears here.</p>)}
    {request && <Form submit={async () => {await client.call("hosted.approve", {code, label, confirmed}); reset();}}>
      <p>Compare every group of this fingerprint with the one on the device you are adding:</p><code>{request.fingerprint}</code>
      <label>Device name<input value={label} maxLength={40} required placeholder="For example: My phone" onChange={event => setLabel(event.target.value)} /></label>
      <label className="check"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /> The full fingerprint matches the device</label>
      <div className="actions"><button type="button" className="text-button" onClick={reset}>Not this device</button><button disabled={!confirmed}>Approve device</button></div>
    </Form>}
    {!request && <details><summary>Paste a request code instead</summary>
      <Form submit={async () => {const inspected = await client.call<Request>("hosted.request.inspect", {code}); setRequest(inspected); setConfirmed(false);}}>
        <label>Device request code<textarea value={code} required onChange={event => {setCode(event.target.value); setRequest(null); setConfirmed(false);}} /></label><button>Check request</button>
      </Form>
    </details>}
    <VerificationNote value={hosted.user_verification} />
  </>;
}

/** Opt-in preview. Deployment values are public configuration; credentials stay native. */
export function HostedSettings({hosted, client}: {hosted?: HostedState; client: Client}) {
  const [config, setConfig] = useState<HostedConfig>(() => hosted?.config || emptyConfig);
  const [forget, setForget] = useState(false);
  const [target, setTarget] = useState("");
  // Every other approved device; a joined computer also sends to its main computer.
  const members = hosted?.roster?.members.filter(member => member.self === undefined ? !member.root : !member.self) || [];
  const isMember = hosted?.role === "member";
  const enabled = hosted?.enabled === true;
  const signedIn = enabled && hosted?.account?.status === "signed_in";
  const active = enabled && signedIn && !!hosted?.roster;
  return <Card title="Saiph account" subtitle="Your phone and computers, connected through Saiph Hosted.">
    <p role="status">{statuses[hosted?.status || "off"] || "Starting"}</p>
    {!hosted?.available ? <p>This build does not include Hosted support.</p> : <>
      {hosted.identity && (isMember
        ? <p className="muted">This computer joined your account as another computer. Your main computer approves and removes devices and renews approvals; keep it online at least every 12 hours.</p>
        : <p className="muted">This computer approves your other devices. Keep it online to renew approvals every 8 hours. Devices stop syncing after 12 hours without renewal. Lost root keys cannot be recovered or transferred yet.</p>)}
      {!hosted.configured && <><p>This build cannot connect to Saiph accounts. Download the current beta from your account page.</p>
      <details><summary>Custom service (advanced)</summary><Form submit={() => client.call("hosted.configure", {...config})}>
        {([['service_url', 'Hosted service address'], ['issuer', 'Sign-in issuer'], ['audience', 'API audience'], ['client_id', 'Desktop client ID']] as const).map(([key, title]) => <label key={key}>{title}<input value={config[key]} required disabled={enabled} onChange={event => setConfig({...config, [key]: event.target.value})} /></label>)}
        <label><input type="checkbox" checked={config.refresh_tokens} disabled={enabled} onChange={event => setConfig({...config, refresh_tokens: event.target.checked})} /> Keep me signed in using a protected rotating refresh token (requires deployment support)</label>
        <button disabled={enabled}>Save deployment</button>
      </Form></details></>}
      {hosted.self_hosted_paired ? <p>This computer is paired with a self-hosted Hub. Use a separate profile for Saiph Hosted.</p>
        : !signedIn && hosted.configured && <HostedSignIn hosted={hosted} client={client} />}
      {hosted.account?.error && <p role="alert">{hosted.account.error}</p>}
      {enabled && <>
        {signedIn && <><p>Signed in</p><Action run={() => client.call("hosted.sign_out")}>Sign out</Action></>}
        {signedIn && !isMember && <HostedRootCode hosted={hosted} client={client} />}
        {signedIn && !hosted.identity && <details><summary>Join as another computer</summary><HostedJoin client={client} waiting={false} /></details>}
        {signedIn && isMember && hosted.status === "awaiting_approval" && <HostedJoin client={client} waiting />}
        {isMember && hosted.root_fingerprint && <p className="muted">Main computer fingerprint: <code>{hosted.root_fingerprint}</code></p>}
        {active && <>
          {!isMember && <HostedApproveDevice hosted={hosted} client={client} />}
          <p>Approvals expire at {new Date(hosted.roster!.expires_at * 1000).toLocaleString()}.</p>
          {members.map(member => <div className="list-row" key={member.id}><div className="grow"><b>{member.label}</b><small>{member.fingerprint}</small></div>{!isMember && <Action run={() => client.call("hosted.revoke", {device_id: member.id})}>Revoke {member.label}</Action>}</div>)}
          {members.length > 0 && <><label>Send file to<select value={target} onChange={event => setTarget(event.target.value)}><option value="">Choose device</option>{members.map(member => <option key={member.id} value={member.id}>{member.label}</option>)}</select></label><Action disabled={!target} run={() => client.call("hosted.file.choose", {target})}>Choose file to send</Action></>}
          {hosted.offers?.map(offer => <div className="list-row" key={offer.id}><span>{offer.name} ({offer.size} bytes)</span><Action run={() => client.call("hosted.file.save", {id: offer.id})}>Save {offer.name}</Action></div>)}
          {!!hosted.security_events?.length && <details><summary>Recent device changes</summary>{hosted.security_events.map(event => <p key={event.id}>{event.kind === "added" ? "Approved" : "Removed"} {event.label} · {new Date(event.at * 1000).toLocaleString()}</p>)}</details>}
          {hosted.notifications?.map(item => <div key={item.id}><b>{item.app}: {item.title}</b><p>{item.text}</p><Action run={() => client.call("hosted.notification.dismiss", {id: item.id})}>Dismiss notification</Action></div>)}
        </>}
        {hosted.error && <p role="alert">{hosted.error}</p>}
        <Action run={() => client.call("hosted.enable", {enabled: false})}>Turn off Hosted</Action>
      </>}
      {!enabled && hosted.identity && <><label><input type="checkbox" checked={forget} onChange={event => setForget(event.target.checked)} /> {isMember ? "Retire this computer's Hosted identity; remove it on your main computer too" : "Retire this computer's root identity; other devices will stop syncing when approvals expire"}</label><Action disabled={!forget} run={() => client.call("hosted.forget", {confirm: true})}>Forget Hosted on this computer</Action></>}
    </>}
  </Card>;
}
