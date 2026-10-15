// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useState } from "react";
import { Check, Cloud, Server } from "lucide-react";
import type { Client, State } from "./types";
import { Action, Card, Form } from "./ui";
import { Enrollment } from "./Enrollment";
import { HostedApproveDevice, HostedRootCode } from "./HostedSettings";
import { HostedJoin } from "./HostedJoin";
import { HostedSignIn, signInToSaiph } from "./HostedSignIn";
import { PairingQr, validQr, type PairingQrCode } from "./PairingQr";
import { UsageChoice, UsageExplanation } from "./UsageSharing";
import { SaiphMark, WaveLoader, WaveProgress } from "./waves";

type Mode = "hosted" | "hub";
type Step = "welcome" | "connect" | "phone" | "features" | "tools" | "privacy" | "done";
const toolNames: Record<string, string> = { adb: "Android platform tools (adb)", scrcpy: "scrcpy", deskflow: "Deskflow" };
const steps: Step[] = ["welcome", "connect", "phone", "features", "tools", "privacy", "done"];
const titles: Record<Step, string> = { welcome: "Welcome", connect: "Connect this computer", phone: "Add your phone", features: "Choose features", tools: "Optional tools", privacy: "Usage statistics", done: "All set" };

type Feature = { key: string; label: string; detail: string; default: boolean; hosted?: boolean };
// Plain-language choices with the same defaults the settings use.
const features: Feature[] = [
  { key: "clipboard", label: "Share the clipboard", detail: "Copy on one device, paste on another.", default: true, hosted: true },
  { key: "dnd_sync", label: "Sync Do Not Disturb", detail: "Turning it on or off anywhere quiets every device.", default: true },
  { key: "new_photo_notices", label: "Offer new screenshots and photos", detail: "Copy or save what you just captured on your phone.", default: true },
  { key: "battery_alerts", label: "Low phone battery alerts", detail: "One notice when your phone drops to 20%.", default: true },
  { key: "ring_computer", label: "Let my phone find this computer", detail: "Your phone can make this computer play a sound.", default: true },
  { key: "pause_media_on_calls", label: "Pause music during calls", detail: "Resumes only what was playing.", default: true },
  { key: "auto_copy_codes", label: "Copy verification codes automatically", detail: "Off: you can still copy codes with one click.", default: false },
  { key: "remote", label: "Phone remote", detail: "Control media, presentations and more from your phone. You choose the phones.", default: false },
  { key: "deskflow", label: "Share keyboard and mouse with another computer", detail: "Needs Deskflow on both computers.", default: false },
];

const tracked = steps.slice(1, -1);
function Progress({ step, usage }: { step: Step; usage: boolean }) {
  // The usage question appears only in builds that can send anonymous counts.
  const shown = tracked.filter((name) => name !== "privacy" || usage);
  return <WaveProgress steps={shown.map((name) => titles[name])} current={shown.indexOf(step)} />;
}

function phoneOf(state: State) {
  return state.phone?.devices.find((d) => d.capabilities.includes("battery"));
}

/** First-run setup: connect, add a phone, choose features and optional tools. */
export function SetupWizard({ state, client, close }: { state: State; client: Client; close: () => void }) {
  const [step, setStep] = useState<Step>("welcome");
  // A Saiph account is the default; your own Hub is only for people who self-host.
  const [mode, setMode] = useState<Mode | null>(state.setup?.mode || (state.hosted?.available === false ? null : "hosted"));
  const link = state.settings?.link as Record<string, unknown> | undefined;
  const [choices, setChoices] = useState<Record<string, boolean>>(() => Object.fromEntries(features.map((f) =>
    [f.key, f.key === "remote" ? (link?.remote as { enabled?: boolean } | undefined)?.enabled === true
      : f.key === "deskflow" ? (link?.deskflow as { enabled?: boolean } | undefined)?.enabled === true
      : link?.[f.key] === undefined ? f.default : link[f.key] === true])));
  const [hubAddress, setHubAddress] = useState(state.settings?.hub?.base_url || "");
  const [hubCode, setHubCode] = useState("");
  const [qr, setQr] = useState<{ qr: PairingQrCode; shownAt: number } | null>(null);
  const hosted = state.hosted;
  const signedIn = hosted?.enabled && hosted.account?.status === "signed_in";
  // A computer that joined as another computer is connected once its main computer approves it.
  const joining = hosted?.role === "member" && hosted.status === "awaiting_approval";
  const connected = mode === "hub" ? Boolean(state.settings?.hub?.paired) : Boolean(hosted?.identity && signedIn && !joining);
  const phone = phoneOf(state);
  const hostedPhones = hosted?.roster?.members.filter((m) => !m.root && !m.self) || [];
  const phoneReady = mode === "hub" ? Boolean(phone) : hostedPhones.length > 0;
  const shown = features.filter((f) => mode !== "hosted" || f.hosted);
  const finish = async () => { await client.call("settings.save", { setup: { completed: true } }); close(); };
  const expire = useCallback(() => setQr(null), []);
  const next = (to: Step) => () => setStep(to);
  const chooseMode = async () => {
    await client.call("settings.save", { setup: { mode } });
    if (mode === "hosted" && hosted?.configured && !signedIn) await signInToSaiph(client, hosted);
    setStep("connect");
  };

  async function saveFeatures() {
    const update: Record<string, unknown> = {};
    for (const f of shown) {
      if (f.key === "remote") {
        const phones = (state.phone?.devices || []).filter((d) => d.capabilities.includes("battery")).map((d) => d.id);
        update.remote = { enabled: choices.remote, ...(choices.remote ? { devices: phones } : {}) };
      } else if (f.key === "deskflow") update.deskflow = { enabled: choices.deskflow };
      else update[f.key] = choices[f.key];
    }
    await client.call("settings.save", { link: update });
    setStep("tools");
  }

  const tools = state.setup?.tools;
  const helpers = Object.entries(state.setup?.linux || {});
  const missing = helpers.filter(([, h]) => !h.found);
  return <div className="setup-wizard" role="dialog" aria-label="Saiph setup">
    <header className="setup-header">{step !== "welcome" && <SaiphMark size={40} />}<h1 key={step}>{titles[step]}</h1>
      {step !== "done" && <button type="button" className="text-button" onClick={() => void finish()}>Set up later</button>}</header>
    {step !== "welcome" && step !== "done" && <Progress step={step} usage={Boolean(state.usage?.available)} />}
    <div className="setup-step" key={step}>

    {step === "welcome" && <div className="setup-hero"><SaiphMark size={96} /><p>Your phone and your computers, in tune.</p></div>}
    {step === "welcome" && <Card title="How do you want to connect your devices?" subtitle="You can change this later in Settings.">
      <div className="setup-choices">
        <button type="button" className={"setup-choice" + (mode === "hosted" ? " selected" : "")} disabled={hosted?.available === false} onClick={() => setMode("hosted")}>
          <Cloud size={28} /><b>Saiph account</b><span>Sign in with your Saiph account. No server or network setup is needed.</span>
          {hosted?.available === false && <small>This build does not include Saiph accounts.</small>}</button>
        <button type="button" className={"setup-choice" + (mode === "hub" ? " selected" : "")} onClick={() => setMode("hub")}>
          <Server size={28} /><b>I self-host my own Hub</b><span>Only if you run a Saiph Hub on your own private network. You'll need an invitation from it.</span></button>
      </div>
      {mode === "hosted" && hosted?.available && !hosted.configured && <p role="status">This build cannot connect to Saiph accounts. Download the current beta from your account page.</p>}
      <div className="actions"><Action disabled={!mode || (mode === "hosted" && (!hosted?.configured || hosted.account?.status === "signing_in"))} run={chooseMode}>{mode === "hosted" && !signedIn ? "Sign in to Saiph" : "Continue"}</Action></div>
    </Card>}

    {step === "connect" && <Card title={mode === "hosted" ? "Sign in with your Saiph account" : "Pair with your Hub"}>
      {mode === "hosted" && hosted && <>
        {hosted.self_hosted_paired ? <p>This computer is already paired with your own Hub. A device uses one or the other.</p>
          : !hosted.configured ? <p>This build cannot connect to Saiph accounts. Download the current beta from your account page.</p>
          : <>
            {!signedIn && <HostedSignIn hosted={hosted} client={client} />}
            {signedIn && !hosted.identity && <><p>This computer becomes the device that approves your others. Keep it online now and then so approvals stay current.</p>
              <Action run={() => client.call("hosted.setup_root")}>Set up this computer</Action>
              <details><summary>Already use Saiph Hosted on another computer?</summary><HostedJoin client={client} waiting={false} /></details></>}
            {signedIn && joining && <HostedJoin client={client} waiting />}
            {connected && <p role="status" className="setup-ok"><Check size={16} />Signed in and set up.</p>}
            {hosted.account?.error && <p role="alert">{hosted.account.error}</p>}
          </>}
      </>}
      {mode === "hub" && <>
        {state.settings?.hub?.paired ? <p role="status" className="setup-ok"><Check size={16} />This computer is paired with your Hub.</p> : <>
          <Enrollment state={state} client={client} />
          <details><summary>Pair with a Hub address and code instead</summary>
            <Form submit={async () => { await client.call("hub.pair", { base_url: hubAddress, code: hubCode, name: state.settings?.machine?.name || "Saiph desktop" }); setHubCode(""); }}>
              <label>Hub address<input aria-label="Setup Hub address" value={hubAddress} onChange={(e) => setHubAddress(e.target.value)} /></label>
              <label>One-time pairing code<input aria-label="Setup pairing code" value={hubCode} inputMode="numeric" maxLength={8} onChange={(e) => setHubCode(e.target.value)} /></label>
              <button>Pair this computer</button>
            </Form>
          </details>
        </>}
      </>}
      <div className="actions"><button type="button" className="text-button" onClick={next("welcome")}>Back</button><button type="button" disabled={!connected} onClick={next("phone")}>Continue</button></div>
    </Card>}

    {step === "phone" && <Card title="Add your Android phone" subtitle="Install Saiph on your phone from your tester invitation, then open it.">
      {mode === "hub" && <>
        {phone ? <p role="status" className="setup-ok"><Check size={16} />{phone.name} is connected.</p> : <>
          <p>In the Saiph app on your phone, tap Scan pairing QR.</p>
          {qr ? <PairingQr qr={qr.qr} shownAt={qr.shownAt} onExpire={expire} onClose={() => setQr(null)} />
            : <Action run={async () => { const shownAt = Date.now(); const value = await client.call<unknown>("enrollment.qr"); if (!validQr(value)) throw new Error("The pairing QR could not be shown."); setQr({ qr: value, shownAt }); }}>Show pairing QR</Action>}
          <WaveLoader label="Waiting for your phone…" />
        </>}
      </>}
      {mode === "hosted" && hosted && <>
        {phoneReady && <p role="status" className="setup-ok"><Check size={16} />{hostedPhones.map((m) => m.label).join(", ")} approved.</p>}
        {hosted.role === "member" ? <p>Phones are added on your main computer: open Settings → Saiph Hosted there, show its code to your phone and approve the phone's request.</p> : <>
          <p>1. On your phone, sign in with the same Saiph account and scan this computer's code.</p>
          <HostedRootCode hosted={hosted} client={client} />
          <p>2. Paste the request your phone shows, compare the fingerprint and approve it.</p>
          <HostedApproveDevice hosted={hosted} client={client} />
        </>}
      </>}
      <Action className="text-button" run={() => client.call("setup.open", { link: "android" })}>Where do I get the Android app?</Action>
      <div className="actions"><button type="button" className="text-button" onClick={next("connect")}>Back</button>
        <button type="button" onClick={next("features")}>{phoneReady ? "Continue" : "Skip for now"}</button></div>
    </Card>}

    {step === "features" && <Card title="What should Saiph do?" subtitle="Change any of these later in Settings → Connections.">
      {mode === "hosted" && <p className="muted">With a Saiph account, Saiph currently shares the clipboard, notifications and files you choose. More features need your own Hub for now.</p>}
      <div className="setup-features">{shown.map((f) => <label className="check" key={f.key}>
        <input type="checkbox" checked={choices[f.key]} onChange={(e) => setChoices((c) => ({ ...c, [f.key]: e.target.checked }))} />
        <span><b>{f.label}</b><small>{f.detail}</small></span></label>)}</div>
      <div className="actions"><button type="button" className="text-button" onClick={next("phone")}>Back</button><Action run={saveFeatures}>Continue</Action></div>
    </Card>}

    {step === "tools" && <Card title="Optional tools" subtitle="Only needed for some features. Saiph links to each project's official download.">
      {tools && Object.entries(tools).filter(([name]) => name !== "deskflow" || choices.deskflow).map(([name, tool]) => <div className="list-row" key={name}>
        <div className="grow"><b>{toolNames[name] || name}</b><small>{tool.purpose}</small></div>
        {tool.found ? <span className="setup-ok"><Check size={16} />Installed</span> : <Action className="text-button" run={() => client.call("setup.open", { link: tool.link })}>Download</Action>}
      </div>)}
      {helpers.length > 0 && <>
        <h3>Linux helpers</h3>
        {helpers.map(([name, h]) => <div className="list-row" key={name}><div className="grow"><b>{name}</b><small>{h.purpose}</small></div>
          {h.found ? <span className="setup-ok"><Check size={16} />Installed</span> : <span className="muted">Not installed</span>}</div>)}
        {missing.length > 0 && <label>Install the missing helpers with this command<input readOnly aria-label="Install command" value={"sudo apt install " + [...new Set(missing.map(([, h]) => h.package))].join(" ")} onFocus={(e) => e.target.select()} /></label>}
      </>}
      <div className="actions"><button type="button" className="text-button" onClick={next("features")}>Back</button><button type="button" onClick={next(state.usage?.available ? "privacy" : "done")}>Continue</button></div>
    </Card>}

    {step === "privacy" && <Card title="Help improve Saiph?" subtitle="Your choice. Saiph works the same either way.">
      <UsageExplanation />
      {state.usage?.consent && <p role="status" className="muted">{state.usage.consent === "granted" ? "You're sharing anonymous usage." : "You're not sharing usage."} Change it any time in Settings.</p>}
      <UsageChoice client={client} onDone={next("done")} />
      <div className="actions"><button type="button" className="text-button" onClick={next("tools")}>Back</button></div>
    </Card>}

    {step === "done" && <Card title="Saiph is ready" subtitle="Your devices now work together.">
      <ul>
        <li>{mode === "hosted" ? "Connected with your Saiph account." : "Paired with your own Hub."}</li>
        <li>{phoneReady ? "Your phone is connected." : "Add your phone any time from the Phone page."}</li>
        <li>Find every setting again in Settings, and run this guide again from Settings → General.</li>
      </ul>
      <div className="actions"><Action run={finish}>Open Saiph</Action></div>
    </Card>}
    </div>
  </div>;
}
