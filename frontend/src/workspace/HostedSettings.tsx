// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client, HostedConfig, HostedState } from "./types";
import { Action, Card, Form } from "./ui";
import { validQr } from "./PairingQr";

type RootCode = {code: string; fingerprint: string; modules: string[]; expires_at: string; expires_in: number};
type Request = {device_id: string; fingerprint: string; expires_at: number};
const emptyConfig: HostedConfig = {service_url: "", issuer: "", audience: "", client_id: "", refresh_tokens: false};
const statuses: Record<string, string> = {off: "Off", starting: "Starting", setup: "Set up this computer as root", active: "Connected", signed_out: "Signed out", sign_in_required: "Sign in again", offline: "Offline; reconnecting", renewal_pending: "Waiting to renew device approvals", retrying: "Reconnecting", clock: "Check this computer's clock", keys_unavailable: "Hosted keys could not be unlocked"};

/** Tells the person whether approving or removing devices needs their face, fingerprint or PIN. */
export function VerificationNote({value}: {value?: string}) {
  if (value === "windows_hello") return <p className="muted">Windows Hello confirms it's you before a device is added or removed.</p>;
  if (value === "unavailable") return <p className="muted">Anyone using this computer while it is unlocked can add a device. On Windows, set up Windows Hello in Settings → Accounts → Sign-in options so adding a device needs your face, fingerprint or PIN.</p>;
  return null;
}

/** Opt-in preview. Deployment values are public configuration; credentials stay native. */
export function HostedSettings({hosted, client}: {hosted?: HostedState; client: Client}) {
  const [config, setConfig] = useState<HostedConfig>(() => hosted?.config || emptyConfig);
  const [root, setRoot] = useState<RootCode | null>(null);
  const [code, setCode] = useState("");
  const [request, setRequest] = useState<Request | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [label, setLabel] = useState("");
  const [forget, setForget] = useState(false);
  const [target, setTarget] = useState("");
  const members = hosted?.roster?.members.filter(member => !member.root) || [];
  const enabled = hosted?.enabled === true;
  const signedIn = hosted?.account?.status === "signed_in";
  const active = enabled && signedIn && !!hosted?.roster;
  async function showRoot(method: string) {
    const result = await client.call<RootCode>(method);
    if (!validQr(result)) throw new Error("Could not display the root QR code.");
    setRoot(result);
  }
  return <Card title="Saiph Hosted preview" subtitle="Sign in with your Saiph account after activating your beta invitation.">
    <p role="status">{statuses[hosted?.status || "off"] || "Starting"}</p>
    {!hosted?.available ? <p>This build does not include Hosted support.</p> : <>
      <p className="muted">This computer is the root device. Keep it online to renew approvals every 8 hours. Devices stop syncing after 12 hours without renewal. Lost root keys cannot be recovered or transferred yet.</p>
      <details><summary>Deployment settings</summary><Form submit={() => client.call("hosted.configure", {...config})}>
        {([['service_url', 'Hosted service address'], ['issuer', 'Sign-in issuer'], ['audience', 'API audience'], ['client_id', 'Desktop client ID']] as const).map(([key, title]) => <label key={key}>{title}<input value={config[key]} required disabled={enabled} onChange={event => setConfig({...config, [key]: event.target.value})} /></label>)}
        <label><input type="checkbox" checked={config.refresh_tokens} disabled={enabled} onChange={event => setConfig({...config, refresh_tokens: event.target.checked})} /> Keep me signed in using a protected rotating refresh token (requires deployment support)</label>
        <button disabled={enabled}>Save deployment</button>
      </Form></details>
      {hosted.self_hosted_paired ? <p>This computer is paired with a self-hosted Hub. Use a separate profile for this preview.</p> : <Action disabled={!enabled && !hosted.configured} run={() => client.call("hosted.enable", {enabled: !enabled})}>{enabled ? "Turn off Hosted" : "Turn on Hosted"}</Action>}
      {enabled && <>
        <p>{hosted.account?.status === "signing_in" ? "Finish sign-in in your browser." : signedIn ? "Signed in" : "Sign in to continue"}</p>
        {signedIn ? <Action run={async () => {await client.call("hosted.sign_out"); setRoot(null);}}>Sign out</Action> : <Action disabled={hosted.account?.status === "signing_in"} run={() => client.call("hosted.sign_in")}>Sign in with your browser</Action>}
        {hosted.account?.error && <p role="alert">{hosted.account.error}</p>}
        {signedIn && <Action run={() => showRoot(hosted.identity ? "hosted.root_code" : "hosted.setup_root")}>{hosted.identity ? "Show root approval code" : "Set up this computer as root"}</Action>}
        {root && signedIn && <div>
          <p>On your phone, scan this QR or paste the root code, then compare the full fingerprint on both screens. The code expires at {new Date(root.expires_at).toLocaleTimeString()}.</p>
          <svg role="img" aria-label="Hosted root approval QR code" viewBox={`0 0 ${root.modules.length} ${root.modules.length}`} width="264" height="264" shapeRendering="crispEdges"><rect width="100%" height="100%" fill="white" /><path fill="black" d={root.modules.map((row, y) => [...row].map((cell, x) => cell === "1" ? `M${x} ${y}h1v1h-1z` : "").join("")).join("")} /></svg>
          <label>Root code<textarea readOnly value={root.code} /></label><p className="muted">Full root fingerprint</p><code>{root.fingerprint}</code>
          <button type="button" onClick={() => setRoot(null)}>Hide root code</button>
        </div>}
        {active && <>
          <Form submit={async () => {const inspected = await client.call<Request>("hosted.request.inspect", {code}); setRequest(inspected); setConfirmed(false);}}>
            <label>Phone request code<textarea value={code} required onChange={event => {setCode(event.target.value); setRequest(null); setConfirmed(false);}} /></label><button>Check request</button>
          </Form>
          {request && <Form submit={async () => {await client.call("hosted.approve", {code, label, confirmed}); setRequest(null); setCode(""); setConfirmed(false);}}>
            <p>Compare this full device fingerprint with the phone:</p><code>{request.fingerprint}</code>
            <label>Device name<input value={label} maxLength={40} required onChange={event => setLabel(event.target.value)} /></label>
            <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /> The full fingerprint matches my phone</label><button disabled={!confirmed}>Approve device</button>
          </Form>}
          <VerificationNote value={hosted.user_verification} />
          <p>Approvals expire at {new Date(hosted.roster!.expires_at * 1000).toLocaleString()}.</p>
          {members.map(member => <div className="list-row" key={member.id}><div className="grow"><b>{member.label}</b><small>{member.fingerprint}</small></div><Action run={() => client.call("hosted.revoke", {device_id: member.id})}>Revoke {member.label}</Action></div>)}
          {members.length > 0 && <><label>Send file to<select value={target} onChange={event => setTarget(event.target.value)}><option value="">Choose device</option>{members.map(member => <option key={member.id} value={member.id}>{member.label}</option>)}</select></label><Action disabled={!target} run={() => client.call("hosted.file.choose", {target})}>Choose file to send</Action></>}
          {hosted.offers?.map(offer => <div className="list-row" key={offer.id}><span>{offer.name} ({offer.size} bytes)</span><Action run={() => client.call("hosted.file.save", {id: offer.id})}>Save {offer.name}</Action></div>)}
          {!!hosted.security_events?.length && <details><summary>Recent device changes</summary>{hosted.security_events.map(event => <p key={event.id}>{event.kind === "added" ? "Approved" : "Removed"} {event.label} · {new Date(event.at * 1000).toLocaleString()}</p>)}</details>}
          {hosted.notifications?.map(item => <div key={item.id}><b>{item.app}: {item.title}</b><p>{item.text}</p><Action run={() => client.call("hosted.notification.dismiss", {id: item.id})}>Dismiss notification</Action></div>)}
        </>}
        {hosted.error && <p role="alert">{hosted.error}</p>}
      </>}
      {!enabled && hosted.identity && <><label><input type="checkbox" checked={forget} onChange={event => setForget(event.target.checked)} /> Retire this computer's root identity; other devices will stop syncing when approvals expire</label><Action disabled={!forget} run={() => client.call("hosted.forget", {confirm: true})}>Forget Hosted on this computer</Action></>}
    </>}
  </Card>;
}
