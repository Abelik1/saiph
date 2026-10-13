// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useState } from "react";
import { Check, Cloud, Server } from "lucide-react";
import type { Client, State } from "./types";
import { Action, Card, Form } from "./ui";
import { Enrollment } from "./Enrollment";
import { HostedApproveDevice, HostedRootCode } from "./HostedSettings";
import { PairingQr, validQr, type PairingQrCode } from "./PairingQr";
import { SaiphMark, WaveLoader, WaveProgress } from "./waves";

type Mode = "hosted" | "hub";
type Step = "welcome" | "connect" | "phone" | "features" | "tools" | "done";
const steps: Step[] = ["welcome", "connect", "phone", "features", "tools", "done"];
const titles: Record<Step, string> = { welcome: "Welcome", connect: "Connect this computer", phone: "Add your phone", features: "Choose features", tools: "Optional tools", done: "All set" };

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
function Progress({ step }: { step: Step }) {
  return <WaveProgress steps={tracked.map((name) => titles[name])} current={tracked.indexOf(step)} />;
}

function phoneOf(state: State) {
  return state.phone?.devices.find((d) => d.capabilities.includes("battery"));
}

/** First-run setup: connect, add a phone, choose features and optional tools. */
export function SetupWizard({ state, client, close }: { state: State; client: Client; close: () => void }) {
  const [step, setStep] = useState<Step>("welcome");
  const [mode, setMode] = useState<Mode | null>(state.setup?.mode || null);
  const link = state.settings?.link as Record<string, unknown> | undefined;
  const [choices, setChoices] = useState<Record<string, boolean>>(() => Object.fromEntries(features.map((f) =>
    [f.key, f.key === "remote" ? (link?.remote as { enabled?: boolean } | undefined)?.enabled === true
      : f.key === "deskflow" ? (link?.deskflow as { enabled?: boolean } | undefined)?.enabled === true
      : link?.[f.key] === undefined ? f.default : link[f.key] === true])));
  const [hubAddress, setHubAddress] = useState(state.settings?.hub?.base_url || "");
  const [hubCode, setHubCode] = useState("");
  const [qr, setQr] = useState<{ qr: PairingQrCode; shownAt: number } | null>(null);
  const hosted = state.hosted;
  const signedIn = hosted?.account?.status === "signed_in";
  const connected = mode === "hub" ? Boolean(state.settings?.hub?.paired) : Boolean(hosted?.identity && signedIn);
  const phone = phoneOf(state);
  const hostedPhones = hosted?.roster?.members.filter((m) => !m.root) || [];
  const phoneReady = mode === "hub" ? Boolean(phone) : hostedPhones.length > 0;
  const shown = features.filter((f) => mode !== "hosted" || f.hosted);
  const finish = async () => { await client.call("settings.save", { setup: { completed: true } }); close(); };
  const expire = useCallback(() => setQr(null), []);
  const next = (to: Step) => () => setStep(to);

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
    {step !== "welcome" && step !== "done" && <Progress step={step} />}
    <div className="setup-step" key={step}>

    {step === "welcome" && <div className="setup-hero"><SaiphMark size={96} /><p>Your phone and your computers, in tune.</p></div>}
    {step === "welcome" && <Card title="How do you want to connect your devices?" subtitle="You can change this later in Settings.">
      <div className="setup-choices">
        <button type="button" className={"setup-choice" + (mode === "hosted" ? " selected" : "")} disabled={hosted?.available === false} onClick={() => setMode("hosted")}>
          <Cloud size={28} /><b>Saiph account</b><span>Sign in with your Saiph account. No server or network setup is needed.</span>
          {hosted?.available === false && <small>This build does not include Saiph accounts.</small>}</button>
        <button type="button" className={"setup-choice" + (mode === "hub" ? " selected" : "")} onClick={() => setMode("hub")}>
          <Server size={28} /><b>My own Hub</b><span>Use a Saiph Hub you run on your private network, with an invitation from it.</span></button>
      </div>
      <div className="actions"><button type="button" disabled={!mode} onClick={next("connect")}>Continue</button></div>
    </Card>}

    {step === "connect" && <Card title={mode === "hosted" ? "Sign in with your Saiph account" : "Pair with your Hub"}>
      {mode === "hosted" && hosted && <>
        {hosted.self_hosted_paired ? <p>This computer is already paired with your own Hub. A device uses one or the other.</p>
          : !hosted.configured && !hosted.enabled ? <p>This build has no Saiph account settings. Enter them under Settings → Connections → Saiph Hosted, or choose My own Hub.</p>
          : <>
            {!hosted.enabled && <Action run={() => client.call("hosted.enable", { enabled: true })}>Turn on Saiph account</Action>}
            {hosted.enabled && !signedIn && <><p>{hosted.account?.status === "signing_in" ? "Finish signing in in your browser." : "Activate your beta code on the Saiph website first, then sign in here."}</p>
              <Action disabled={hosted.account?.status === "signing_in"} run={() => client.call("hosted.sign_in")}>Sign in with your browser</Action></>}
            {signedIn && !hosted.identity && <><p>This computer becomes the device that approves your others. Keep it online now and then so approvals stay current.</p>
              <Action run={() => client.call("hosted.setup_root")}>Set up this computer</Action></>}
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
        <p>1. On your phone, sign in with the same Saiph account and scan this computer's code.</p>
        <HostedRootCode hosted={hosted} client={client} />
        <p>2. Paste the request your phone shows, compare the fingerprint and approve it.</p>
        <HostedApproveDevice hosted={hosted} client={client} />
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
        <div className="grow"><b>{name === "scrcpy" ? "scrcpy" : "Deskflow"}</b><small>{tool.purpose}</small></div>
        {tool.found ? <span className="setup-ok"><Check size={16} />Installed</span> : <Action className="text-button" run={() => client.call("setup.open", { link: tool.link })}>Download</Action>}
      </div>)}
      {helpers.length > 0 && <>
        <h3>Linux helpers</h3>
        {helpers.map(([name, h]) => <div className="list-row" key={name}><div className="grow"><b>{name}</b><small>{h.purpose}</small></div>
          {h.found ? <span className="setup-ok"><Check size={16} />Installed</span> : <span className="muted">Not installed</span>}</div>)}
        {missing.length > 0 && <label>Install the missing helpers with this command<input readOnly aria-label="Install command" value={"sudo apt install " + [...new Set(missing.map(([, h]) => h.package))].join(" ")} onFocus={(e) => e.target.select()} /></label>}
      </>}
      <div className="actions"><button type="button" className="text-button" onClick={next("features")}>Back</button><button type="button" onClick={next("done")}>Continue</button></div>
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
