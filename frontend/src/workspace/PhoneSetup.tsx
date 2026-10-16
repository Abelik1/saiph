// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Check, Cloud, Server, Smartphone } from "lucide-react";
import type { Client, HostedState, State } from "./types";
import { Action } from "./ui";
import { Enrollment } from "./Enrollment";
import { HostedApproveDevice, HostedRootCode } from "./HostedSettings";
import { HostedJoin } from "./HostedJoin";
import { HostedSignIn } from "./HostedSignIn";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Disclosure } from "@/components/ui/disclosure";
import { Button } from "@/components/ui/button";
import { WaveLoader, WaveProgress } from "./waves";

const connectionSteps = ["Account", "Computer", "Scan", "Approve"];
type ConnectedPhone = { name: string; hosted?: boolean; online: boolean };
type Offered = { device_id: string };

function ConnectionStep({ step, children }: { step: number; children: ReactNode }) {
  return <div className="grid min-w-0 gap-6">
    <WaveProgress steps={connectionSteps} current={step} />
    {children}
  </div>;
}

function PhonePairingSteps({ hosted, client, phones = [], onApproved, onDone }: {
  hosted: HostedState; client: Client; phones?: ConnectedPhone[]; onApproved?: (label: string) => void; onDone?: () => void;
}) {
  const headingId = useId();
  const [step, setStep] = useState<"scan" | "approve" | "approved">("scan");
  const [approvedLabel, setApprovedLabel] = useState("");
  // Requests already on the list when the owner goes back to scanning: they wait for an explicit Continue.
  const ignored = useRef<string[]>([]);
  const heading = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    heading.current?.focus();
  }, [step]);
  // The phone's request arrives by itself after it scans; the wizard moves on with it.
  useEffect(() => {
    if (step !== "scan" || !hosted.identity) return;
    let alive = true;
    const look = () => client.call<{ requests: Offered[] }>("hosted.requests").then(value => {
      const requests = Array.isArray(value?.requests) ? value.requests : [];
      if (alive && requests.some(item => !ignored.current.includes(item.device_id))) setStep("approve");
    }).catch(() => undefined);
    void look();
    const timer = window.setInterval(look, 4000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [step, hosted.identity, client]);
  const backToScan = async () => {
    const value = await client.call<{ requests: Offered[] }>("hosted.requests").catch(() => null);
    ignored.current = Array.isArray(value?.requests) ? value.requests.map(item => item.device_id) : [];
    setStep("scan");
  };
  const connected = phones.find(phone => phone.hosted && phone.online && phone.name === approvedLabel);
  return <ConnectionStep step={step === "scan" ? 2 : 3}>
    <section className="grid min-w-0 gap-4" aria-labelledby={headingId}>
      <h3 id={headingId} ref={heading} tabIndex={-1} className="m-0 text-lg font-semibold outline-none">
        {step === "scan" ? "Scan on your phone" : step === "approve" ? "Approve your phone" : connected ? "Phone connected" : "Phone approved"}
      </h3>
      {step === "scan" ? <>
        <p className="m-0 text-sm leading-relaxed text-muted-foreground">Open Saiph on your phone, sign in with the same account and tap Scan the code on your computer. This screen moves on by itself once your phone has scanned.</p>
        <HostedRootCode hosted={hosted} client={client} autoShow compact />
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
          <p role="status" className="m-0 text-sm text-muted-foreground">Waiting for your phone…</p>
          <Button variant="secondary" onClick={() => setStep("approve")}>Continue to approval</Button>
        </div>
      </> : step === "approve" ? <>
        <p className="m-0 text-sm leading-relaxed text-muted-foreground">Choose your phone below, then compare its security code with the phone's screen.</p>
        <HostedApproveDevice hosted={hosted} client={client} onApproved={label => { setApprovedLabel(label); setStep("approved"); onApproved?.(label); }} />
        <Disclosure summary="Why compare security codes?">
          <p className="m-0">A security code is the fingerprint of a device's encryption keys. Signing in finds your account; comparing every group on both screens checks which device you are trusting.</p>
        </Disclosure>
        <div className="border-t border-border pt-4"><Button variant="secondary" onClick={() => void backToScan()}>Back to scanning</Button></div>
      </> : connected ? <>
        <p role="status" className="m-0 flex items-center gap-2 text-status-on"><Check className="size-4" />{connected.name} is connected</p>
        <p className="m-0 text-muted-foreground">Your phone and this computer are now in tune. Notifications, files and photos you share appear in the Phone tab.</p>
        {onDone && <div className="flex justify-end"><Button variant="default" onClick={onDone}>Done</Button></div>}
      </> : <>
        <p role="status" className="m-0 flex items-center gap-2 text-status-on"><Check className="size-4" />Approval complete</p>
        <WaveLoader label="Waiting for your phone to connect…" size={80} />
        <p className="m-0 text-sm text-muted-foreground">Your phone is finishing the connection. Keep Saiph open on it; this screen updates when it connects.</p>
        {onDone && <div className="flex justify-end"><Button variant="secondary" onClick={onDone}>Done</Button></div>}
      </>}
    </section>
  </ConnectionStep>;
}

/** One connection wizard, shared by Phone, its dialog and the optional setup guide. */
export function HostedPhoneSetup({ hosted, client, phones, onApproved, onDone }: {
  hosted: HostedState; client: Client; phones?: ConnectedPhone[]; onApproved?: (label: string) => void; onDone?: () => void;
}) {
  const signedIn = hosted.enabled && hosted.account?.status === "signed_in";
  if (!hosted.available) return <p>This build does not include Saiph accounts.</p>;
  if (hosted.self_hosted_paired) return <p>This computer uses your own Hub. Keep using its pairing invitation.</p>;
  if (!hosted.configured) return <p>This build cannot connect to Saiph accounts. Download the current beta from your account page.</p>;
  if (!signedIn) return <ConnectionStep step={0}><div className="grid gap-4">
    <h3 className="m-0 text-lg font-semibold">Sign in to connect your phone</h3>
    <HostedSignIn hosted={hosted} client={client} />
    {hosted.account?.error && <p role="alert">{hosted.account.error}</p>}
  </div></ConnectionStep>;
  if (hosted.role === "member") return <ConnectionStep step={1}>{hosted.status === "awaiting_approval"
    ? <HostedJoin client={client} waiting />
    : <div className="grid gap-3"><h3 className="m-0 text-lg font-semibold">Use your main computer to add a phone</h3>
      <p className="m-0 text-muted-foreground">Phones are added on your main computer. Open its Phone tab and choose Connect a phone. After approval, your phone can connect to this computer too.</p></div>}</ConnectionStep>;
  if (!hosted.identity) return <ConnectionStep step={1}><div className="grid gap-4">
    <p className="m-0 flex items-center gap-2 text-status-on"><Check className="size-4" />You're signed in</p>
    <h3 className="m-0 text-lg font-semibold">Set up your main computer</h3>
    <p className="m-0 text-muted-foreground">This computer will approve your phone and other devices. Keep it online regularly so they stay connected.</p>
    <div><Action variant="default" run={() => client.call("hosted.setup_root")}>Set up this computer</Action></div>
    <Disclosure summary="Already use Saiph on another computer?"><HostedJoin client={client} waiting={false} /></Disclosure>
  </div></ConnectionStep>;
  return <PhonePairingSteps hosted={hosted} client={client} phones={phones} onApproved={onApproved} onDone={onDone} />;
}

/** A fresh desktop opens here, in Phone, rather than sending the owner through Settings. */
export function PhoneSetup({ state, client, onApproved, onDone }: { state: State; client: Client; onApproved?: (label: string) => void; onDone?: () => void }) {
  const [chosenMode, setMode] = useState<"hosted" | "hub">(state.setup?.mode || (state.hosted?.available === false ? "hub" : "hosted"));
  const mode = state.enrollment?.ready ? "hub" : chosenMode;
  const choose = async (next: "hosted" | "hub") => {
    await client.call("settings.save", { setup: { mode: next } });
    setMode(next);
  };
  return <div className="mx-auto grid w-full max-w-2xl gap-6" aria-label="Connect your phone">
    <header className="grid gap-2">
      <span className="flex items-center gap-3"><Smartphone className="size-6 text-secondary-foreground" /><h2 className="m-0 text-[26px] font-semibold tracking-tight">Connect your phone</h2></span>
      <p className="m-0 text-muted-foreground">Sign in, scan and approve. Everything starts here in the Phone tab.</p>
    </header>
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">{mode === "hosted" ? <><Cloud className="size-5" />Phone connection</> : <><Server className="size-5" />Connect to your own Hub</>}</CardTitle>
        <CardDescription>{mode === "hosted" ? "Connect without setting up a server or private network." : "Use an invitation from the Saiph Hub you manage."}</CardDescription></CardHeader>
      <CardContent className="grid gap-4">
        {mode === "hosted" && state.hosted ? <HostedPhoneSetup hosted={state.hosted} client={client} phones={state.phone?.devices} onApproved={onApproved} onDone={onDone} /> : mode === "hosted"
          ? <p>Saiph account support is unavailable in this build.</p> : <Enrollment state={state} client={client} />}
        <div className="flex flex-wrap gap-3 border-t border-border pt-4">
          {mode === "hosted" ? !state.hosted?.identity && !state.hosted?.enabled && <Action variant="secondary" run={() => choose("hub")}>Use my own Hub instead</Action>
            : !state.enrollment?.ready && state.hosted?.available !== false && <Action variant="secondary" run={() => choose("hosted")}>Use a Saiph account instead</Action>}
          <Action variant="tonal" run={() => client.call("setup.open", { link: "android" })}>Get the Android app</Action>
        </div>
      </CardContent>
    </Card>
  </div>;
}
