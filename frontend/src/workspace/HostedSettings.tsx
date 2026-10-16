// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useRef, useState } from "react";
import type { Client, HostedConfig, HostedState } from "./types";
import { Action, Card, Form } from "./ui";
import { validQr } from "./PairingQr";
import { HostedJoin } from "./HostedJoin";
import { HostedSignIn } from "./HostedSignIn";
import { useSettingsNavigation } from "./settingsNavigation";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Field, Label } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";

type RootCode = {code: string; fingerprint: string; modules: string[]; expires_at: string; expires_in: number};
type Request = {device_id: string; fingerprint: string; expires_at: number};
type Offered = Request & {code: string};
const emptyConfig: HostedConfig = {service_url: "", issuer: "", audience: "", client_id: "", refresh_tokens: false};
const statuses: Record<string, string> = {off: "Off", starting: "Starting", setup: "Set up this computer", active: "Connected", signed_out: "Signed out", sign_in_required: "Sign in again", offline: "Offline; reconnecting", renewal_pending: "Waiting to renew device approvals", retrying: "Reconnecting", clock: "Check this computer's clock", keys_unavailable: "Hosted keys could not be unlocked", awaiting_approval: "Waiting for your main computer to approve this computer", removed: "Removed by your main computer"};

/** Tells the person whether approving or removing devices needs their face, fingerprint or PIN. */
export function VerificationNote({value}: {value?: string}) {
  if (value === "windows_hello") return <p className="muted">Windows Hello confirms it's you before a device is added or removed.</p>;
  if (value === "unavailable") return <p className="muted">Anyone using this computer while it is unlocked can add a device. On Windows, set up Windows Hello in Settings → Accounts → Sign-in options so adding a device needs your face, fingerprint or PIN.</p>;
  return null;
}

/** The signed computer code. Opening guided pairing shows it automatically. */
export function HostedRootCode({hosted, client, autoShow = false, compact = false}: {hosted: HostedState; client: Client; autoShow?: boolean; compact?: boolean}) {
  const [root, setRoot] = useState<RootCode | null>(null);
  const [error, setError] = useState("");
  async function showRoot(method: string) {
    const result = await client.call<RootCode>(method);
    if (!validQr(result)) throw new Error("Could not display the computer's QR code. Try again.");
    setRoot(result);
    setError("");
  }
  // In the setup guide the next step is scanning, so the code is shown straight away.
  useEffect(() => {
    let alive = true;
    if (autoShow && hosted.identity) {
      void client.call<RootCode>("hosted.root_code").then(result => {
        if (!validQr(result)) throw new Error("Could not display the computer's QR code. Try again.");
        if (alive) { setRoot(result); setError(""); }
      }).catch(failure => { if (alive) setError(failure instanceof Error ? failure.message : String(failure)); });
    }
    return () => { alive = false; };
  }, [autoShow, hosted.identity, client]);
  return <div className="grid min-w-0 gap-3 text-sm leading-relaxed [&_p]:m-0">
    {root && <div className={compact ? "grid items-start gap-4 sm:grid-cols-[264px_minmax(0,1fr)]" : undefined}>
      <svg className={(compact ? "" : "my-3 ") + "h-auto w-full max-w-[264px] rounded-field"} role="img" aria-label="Hosted root approval QR code" viewBox={`0 0 ${root.modules.length} ${root.modules.length}`} width="264" height="264" shapeRendering="crispEdges"><rect width="100%" height="100%" fill="white" /><path fill="black" d={root.modules.map((row, y) => [...row].map((cell, x) => cell === "1" ? `M${x} ${y}h1v1h-1z` : "").join("")).join("")} /></svg>
      <div className="min-w-0">
      <p className="text-muted-foreground">This computer's security code</p>
      <code className="my-2 block break-words rounded-field border border-border bg-field p-3 text-sm">{root.fingerprint}</code>
      <p className="text-muted-foreground">Compare every group when your phone asks. QR expires at {new Date(root.expires_at).toLocaleTimeString()}.</p>
      <Disclosure className="mt-3" summary="Can't scan? Copy a code instead"><label>Computer code<textarea readOnly value={root.code} /></label></Disclosure>
      </div>
    </div>}
    {error && !root && <p role="alert">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <Action variant="tonal" run={() => showRoot(hosted.identity ? "hosted.root_code" : "hosted.setup_root")}>{!hosted.identity ? "Set up this computer" : root ? "Refresh QR code" : "Show QR code"}</Action>
      {root && !autoShow && <Button onClick={() => setRoot(null)}>Hide QR code</Button>}
    </div>
  </div>;
}

/** Approve a device's signed request after the owner compares its full fingerprint.
 * Devices that signed in offer their request through the service, so it appears here by
 * itself; the code is verified on this computer and pasting stays as a fallback. */
export function HostedApproveDevice({hosted, client, onApproved}: {hosted: HostedState; client: Client; onApproved?: (label: string) => void}) {
  const id = useId();
  const revision = useRef(0);
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
    return () => { alive = false; revision.current += 1; window.clearInterval(timer); };
  }, [client]);
  const review = (item: Offered) => { revision.current += 1; setCode(item.code); setRequest(item); setConfirmed(false); setLabel(""); };
  const reset = () => { revision.current += 1; setRequest(null); setCode(""); setConfirmed(false); setLabel(""); };
  return <div className="grid min-w-0 gap-4 text-sm leading-relaxed [&_p]:m-0">
    {!request && (offered.length ? <div className="hosted-offered" aria-live="polite">
      {offered.map(item => <div key={item.device_id} className="hosted-offered-item">
        <p><b>A device is ready to connect.</b></p>
        <Button variant="tonal" onClick={() => review(item)}>Review and approve</Button>
      </div>)}
    </div> : <p className="muted" aria-live="polite">Waiting for your device… After it signs in and checks this computer's code, it appears here.</p>)}
    {request && <Form className="[&_fieldset]:grid [&_fieldset]:gap-4" submit={async () => {const current = revision.current; await client.call("hosted.approve", {code, label, confirmed}); if (revision.current === current) { const approved = label; reset(); onApproved?.(approved); }}}>
      <p>Compare every group of this security code with the one on the device you are adding:</p>
      <code className="block break-words rounded-field border border-border bg-field p-3 text-sm">{request.fingerprint}</code>
      <Field label="Device name" htmlFor={id + "-name"} className="[&_label]:text-sm"><Input id={id + "-name"} value={label} maxLength={40} required placeholder="For example: My phone" onChange={event => setLabel(event.target.value)} /></Field>
      <Label className="items-start gap-3 text-sm text-foreground"><input data-slot="checkbox" className="mt-0.5 size-4 shrink-0 accent-primary" type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /><span>Every group matches my device</span></Label>
      <div className="flex flex-wrap gap-2"><Button variant="secondary" onClick={reset}>Not this device</Button><Button type="submit" variant="default" disabled={!confirmed}>Approve device</Button></div>
    </Form>}
    {!request && <Disclosure summary="My device hasn't appeared">
      <p>On your phone, share its request code, then paste it here. You still compare the full security code before approving.</p>
      <Form className="[&_fieldset]:grid [&_fieldset]:gap-4" submit={async () => {const current = ++revision.current; const inspected = await client.call<Request>("hosted.request.inspect", {code}); if (revision.current === current) { setRequest(inspected); setConfirmed(false); }}}>
        <Field label="Device request code" htmlFor={id + "-request"}><Textarea id={id + "-request"} value={code} required onChange={event => {revision.current += 1; setCode(event.target.value); setRequest(null); setConfirmed(false);}} /></Field><div><Button type="submit" variant="tonal">Check request</Button></div>
      </Form>
    </Disclosure>}
    <VerificationNote value={hosted.user_verification} />
  </div>;
}

/** Opt-in preview. Deployment values are public configuration; credentials stay native. */
export function HostedSettings({hosted, client}: {hosted?: HostedState; client: Client}) {
  const { connectPhone } = useSettingsNavigation();
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
      {hosted.identity && <Disclosure summary="Connection details">{isMember
        ? <p className="muted">This computer joined your account as another computer. Your main computer approves and removes devices and renews approvals; keep it online at least every 12 hours.</p>
        : <p className="muted">This computer approves your other devices. Keep it online to renew approvals every 8 hours. Devices stop syncing after 12 hours without renewal. Lost root keys cannot be recovered or transferred yet.</p>}</Disclosure>}
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
        {signedIn && !isMember && (connectPhone ? <Button variant="tonal" onClick={connectPhone}>Connect a phone</Button> : <HostedRootCode hosted={hosted} client={client} />)}
        {signedIn && !hosted.identity && <details><summary>Join as another computer</summary><HostedJoin client={client} waiting={false} /></details>}
        {signedIn && isMember && hosted.status === "awaiting_approval" && <HostedJoin client={client} waiting />}
        {isMember && hosted.root_fingerprint && <p className="muted">Main computer fingerprint: <code>{hosted.root_fingerprint}</code></p>}
        {active && <>
          {!isMember && !connectPhone && <HostedApproveDevice hosted={hosted} client={client} />}
          <Disclosure summary="Approved devices">
          <p>Approvals expire at {new Date(hosted.roster!.expires_at * 1000).toLocaleString()}.</p>
          {members.map(member => <div className="list-row" key={member.id}><div className="grow"><b>{member.label}</b><small>{member.fingerprint}</small></div>{!isMember && <Action run={() => client.call("hosted.revoke", {device_id: member.id})}>Revoke {member.label}</Action>}</div>)}
          </Disclosure>
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
